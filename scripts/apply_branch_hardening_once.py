#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected exactly one match, found {count}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


# 1. Cross-platform boundary: no dead non-Windows stub for a Windows-only probe.
replace_once(
    "src-tauri/src/codex_desktop.rs",
    '''#[cfg(not(target_os = "windows"))]\nfn find_latest_windows_codex_executable() -> Option<PathBuf> {\n    None\n}\n\n''',
    "",
)

# 2. settings.json durability + corruption evidence + error propagation.
replace_once(
    "src-tauri/src/settings.rs",
    '''use serde::{Deserialize, Serialize};\nuse std::fs;\n#[cfg(unix)]\nuse std::io::Write;\nuse std::path::PathBuf;\nuse std::sync::{OnceLock, RwLock};\n''',
    '''use serde::{Deserialize, Serialize};\nuse sha2::{Digest, Sha256};\nuse std::fs;\nuse std::path::{Path, PathBuf};\nuse std::sync::{OnceLock, RwLock};\n''',
)

replace_once(
    "src-tauri/src/settings.rs",
    '''    fn load_from_file() -> Self {\n        let Some(path) = Self::settings_path() else {\n            return Self::default();\n        };\n        if let Ok(content) = fs::read_to_string(&path) {\n            match serde_json::from_str::<AppSettings>(&content) {\n                Ok(mut settings) => {\n                    settings.normalize_paths();\n                    settings\n                }\n                Err(err) => {\n                    log::warn!(\n                        "解析设置文件失败，将使用默认设置。路径: {}, 错误: {}",\n                        path.display(),\n                        err\n                    );\n                    Self::default()\n                }\n            }\n        } else {\n            Self::default()\n        }\n    }\n}\n\nfn save_settings_file(settings: &AppSettings) -> Result<(), AppError> {\n    let mut normalized = settings.clone();\n    normalized.normalize_paths();\n    let Some(path) = AppSettings::settings_path() else {\n        return Err(AppError::Config("无法获取用户主目录".to_string()));\n    };\n\n    if let Some(parent) = path.parent() {\n        fs::create_dir_all(parent).map_err(|e| AppError::io(parent, e))?;\n    }\n\n    let json = serde_json::to_string_pretty(&normalized)\n        .map_err(|e| AppError::JsonSerialize { source: e })?;\n    #[cfg(unix)]\n    {\n        use std::fs::OpenOptions;\n        use std::os::unix::fs::OpenOptionsExt;\n\n        let mut file = OpenOptions::new()\n            .create(true)\n            .write(true)\n            .truncate(true)\n            .mode(0o600)\n            .open(&path)\n            .map_err(|e| AppError::io(&path, e))?;\n        file.write_all(json.as_bytes())\n            .map_err(|e| AppError::io(&path, e))?;\n    }\n\n    #[cfg(not(unix))]\n    {\n        fs::write(&path, json).map_err(|e| AppError::io(&path, e))?;\n    }\n\n    Ok(())\n}\n''',
    '''    fn load_from_file() -> Self {\n        let Some(path) = Self::settings_path() else {\n            return Self::default();\n        };\n        Self::load_from_path(&path)\n    }\n\n    fn load_from_path(path: &Path) -> Self {\n        match fs::read_to_string(path) {\n            Ok(content) => match serde_json::from_str::<AppSettings>(&content) {\n                Ok(mut settings) => {\n                    settings.normalize_paths();\n                    settings\n                }\n                Err(err) => {\n                    preserve_corrupt_settings_file(path, &content);\n                    log::warn!(\n                        "解析设置文件失败，将使用默认设置。路径: {}, 错误: {}",\n                        path.display(),\n                        err\n                    );\n                    Self::default()\n                }\n            },\n            Err(err) if err.kind() == std::io::ErrorKind::NotFound => Self::default(),\n            Err(err) => {\n                log::warn!(\n                    "读取设置文件失败，将使用默认设置。路径: {}, 错误: {}",\n                    path.display(),\n                    err\n                );\n                Self::default()\n            }\n        }\n    }\n}\n\nfn corrupt_settings_backup_path(path: &Path, content: &str) -> PathBuf {\n    let digest = Sha256::digest(content.as_bytes());\n    let fingerprint = digest[..8]\n        .iter()\n        .map(|byte| format!("{byte:02x}"))\n        .collect::<String>();\n    let file_name = path\n        .file_name()\n        .and_then(|name| name.to_str())\n        .unwrap_or("settings.json");\n    path.with_file_name(format!("{file_name}.corrupt-{fingerprint}"))\n}\n\nfn preserve_corrupt_settings_file(path: &Path, content: &str) {\n    let backup_path = corrupt_settings_backup_path(path, content);\n    if backup_path.exists() {\n        return;\n    }\n\n    match crate::config::atomic_write(&backup_path, content.as_bytes()) {\n        Ok(()) => log::warn!(\n            "已保留损坏设置文件快照: {}",\n            backup_path.display()\n        ),\n        Err(err) => log::error!(\n            "保留损坏设置文件快照失败。原文件仍保留在 {}，备份路径: {}，错误: {}",\n            path.display(),\n            backup_path.display(),\n            err\n        ),\n    }\n}\n\nfn save_settings_file(settings: &AppSettings) -> Result<(), AppError> {\n    let Some(path) = AppSettings::settings_path() else {\n        return Err(AppError::Config("无法获取用户主目录".to_string()));\n    };\n    save_settings_file_to_path(settings, &path)\n}\n\nfn save_settings_file_to_path(settings: &AppSettings, path: &Path) -> Result<(), AppError> {\n    let mut normalized = settings.clone();\n    normalized.normalize_paths();\n\n    if let Some(parent) = path.parent() {\n        fs::create_dir_all(parent).map_err(|e| AppError::io(parent, e))?;\n    }\n\n    let json = serde_json::to_string_pretty(&normalized)\n        .map_err(|e| AppError::JsonSerialize { source: e })?;\n    crate::config::atomic_write(path, json.as_bytes())\n}\n''',
)

replace_once(
    "src-tauri/src/settings.rs",
    '''        let _ = set_current_provider(app_type, None);\n''',
    '''        set_current_provider(app_type, None)?;\n''',
)

replace_once(
    "src-tauri/src/settings.rs",
    '''    use crate::app_config::AppType;\n\n    #[test]\n    fn visible_apps_old_settings_default_claude_desktop_visible() {\n''',
    '''    use crate::app_config::AppType;\n\n    #[test]\n    fn corrupt_settings_are_backed_up_once_before_default_recovery() {\n        let dir = tempfile::tempdir().expect("tempdir");\n        let path = dir.path().join("settings.json");\n        let corrupt = r#"{\"webdavSync\":{"#;\n        fs::write(&path, corrupt).expect("write corrupt settings");\n\n        let loaded = AppSettings::load_from_path(&path);\n        assert_eq!(loaded.show_in_tray, AppSettings::default().show_in_tray);\n\n        let backup = corrupt_settings_backup_path(&path, corrupt);\n        assert_eq!(\n            fs::read_to_string(&backup).expect("read corruption backup"),\n            corrupt\n        );\n\n        let _ = AppSettings::load_from_path(&path);\n        let backup_count = fs::read_dir(dir.path())\n            .expect("read tempdir")\n            .filter_map(Result::ok)\n            .filter(|entry| {\n                entry\n                    .file_name()\n                    .to_string_lossy()\n                    .starts_with("settings.json.corrupt-")\n            })\n            .count();\n        assert_eq!(backup_count, 1, "same corruption should not create backup spam");\n    }\n\n    #[test]\n    fn settings_save_uses_common_atomic_persistence_boundary() {\n        let dir = tempfile::tempdir().expect("tempdir");\n        let path = dir.path().join("settings.json");\n        let mut settings = AppSettings::default();\n        settings.show_in_tray = false;\n\n        save_settings_file_to_path(&settings, &path).expect("save settings");\n        let saved: AppSettings = serde_json::from_str(\n            &fs::read_to_string(&path).expect("read settings"),\n        )\n        .expect("parse saved settings");\n        assert!(!saved.show_in_tray);\n\n        #[cfg(unix)]\n        {\n            use std::os::unix::fs::PermissionsExt;\n            let mode = fs::metadata(&path)\n                .expect("settings metadata")\n                .permissions()\n                .mode()\n                & 0o777;\n            assert_eq!(mode, 0o600);\n        }\n    }\n\n    #[test]\n    fn visible_apps_old_settings_default_claude_desktop_visible() {\n''',
)

# 3. Deep-link raw input is secret-bearing. Only parser/import may receive raw values.
replace_once(
    "src-tauri/src/lib.rs",
    '''    log::info!("✓ Deep link URL detected from {source}: {redacted_url}");\n    log::debug!("Deep link URL (raw) from {source}: {url_str}");\n''',
    '''    log::info!("✓ Deep link URL detected from {source}: {redacted_url}");\n    log::debug!(\n        "Deep link URL metadata from {source}: length={}, redacted={redacted_url}",\n        url_str.len()\n    );\n''',
)

replace_once(
    "src-tauri/src/lib.rs",
    '''        Err(e) => {\n            log::error!("✗ Failed to parse deep link URL: {e}");\n\n            if let Err(emit_err) = app.emit(\n                "deeplink-error",\n                serde_json::json!({\n                    "url": url_str,\n                    "error": e.to_string()\n                }),\n            ) {\n''',
    '''        Err(e) => {\n            log::error!("✗ Failed to parse deep link URL ({redacted_url}): {e}");\n\n            if let Err(emit_err) = app.emit(\n                "deeplink-error",\n                serde_json::json!({\n                    "url": redacted_url,\n                    "error": e.to_string()\n                }),\n            ) {\n''',
)

lib_path = ROOT / "src-tauri/src/lib.rs"
lib_text = lib_path.read_text(encoding="utf-8")
if "mod sensitive_deeplink_boundary_tests" in lib_text:
    raise SystemExit("src-tauri/src/lib.rs: sensitive deep-link tests already exist")
lib_text += '''\n\n#[cfg(test)]\nmod sensitive_deeplink_boundary_tests {\n    use super::redact_url_for_log;\n\n    #[test]\n    fn deep_link_log_redaction_keeps_keys_but_never_secret_values() {\n        let raw = "ccswitch://v1/import?resource=provider&name=demo&apiKey=sk-secret&usageAccessToken=token-secret#fragment-secret";\n        let redacted = redact_url_for_log(raw);\n\n        assert!(redacted.contains("apiKey"));\n        assert!(redacted.contains("usageAccessToken"));\n        assert!(!redacted.contains("sk-secret"));\n        assert!(!redacted.contains("token-secret"));\n        assert!(!redacted.contains("fragment-secret"));\n    }\n\n    #[test]\n    fn malformed_deep_link_redaction_drops_query_values() {\n        let raw = "ccswitch://v1/import?apiKey=top-secret%ZZ";\n        let redacted = redact_url_for_log(raw);\n        assert!(!redacted.contains("top-secret"));\n        assert!(redacted.contains("?[redacted]") || redacted.contains("?[keys:"));\n    }\n}\n'''
lib_path.write_text(lib_text, encoding="utf-8")

# 4. Auto-sync must not swallow the secondary persistence failure.
for path, type_name, updater, label in [
    (
        "src-tauri/src/services/webdav_auto_sync.rs",
        "WebDavSyncSettings",
        "update_webdav_sync_status",
        "WebDAV",
    ),
    (
        "src-tauri/src/services/s3_auto_sync.rs",
        "S3SyncSettings",
        "update_s3_sync_status",
        "S3",
    ),
]:
    replace_once(
        path,
        f'''fn persist_auto_sync_error(settings: &mut {type_name}, error: &AppError) {{\n    settings.status.last_error = Some(error.to_string());\n    settings.status.last_error_source = Some("auto".to_string());\n    let _ = settings::{updater}(settings.status.clone());\n}}\n''',
        f'''fn persist_auto_sync_error(\n    settings: &mut {type_name},\n    error: &AppError,\n) -> Result<(), AppError> {{\n    settings.status.last_error = Some(error.to_string());\n    settings.status.last_error_source = Some("auto".to_string());\n    settings::{updater}(settings.status.clone())\n}}\n''',
    )
    replace_once(
        path,
        '''        Err(err) => {\n            persist_auto_sync_error(&mut sync_settings, &err);\n            emit_auto_sync_status_updated(app, "error", Some(&err.to_string()));\n            Err(err)\n        }\n''',
        f'''        Err(err) => {{\n            if let Err(persist_err) = persist_auto_sync_error(&mut sync_settings, &err) {{\n                log::error!(\n                    "[{label}][AutoSync] Upload failed and persisting the error status also failed: upload_error={{err}}; persistence_error={{persist_err}}"\n                );\n            }}\n            emit_auto_sync_status_updated(app, "error", Some(&err.to_string()));\n            Err(err)\n        }}\n''',
    )

# 5. Permanent guard for these exact failure boundaries.
guard = ROOT / "scripts/check_rust_failure_boundaries.py"
guard.write_text(
    '''#!/usr/bin/env python3\nfrom pathlib import Path\nimport re\nimport sys\n\nROOT = Path(__file__).resolve().parents[1]\nCHECKS = [\n    (ROOT / "src-tauri/src/lib.rs", re.compile(r'Deep link URL \\(raw\\)|"url"\\s*:\\s*url_str'), "raw deep-link data must not cross the diagnostics/event boundary"),\n    (ROOT / "src-tauri/src/settings.rs", re.compile(r"let _ = set_current_provider\\("), "current-provider persistence errors must propagate"),\n    (ROOT / "src-tauri/src/services/webdav_auto_sync.rs", re.compile(r"let _ = settings::update_webdav_sync_status\\("), "WebDAV auto-sync status persistence errors must be observable"),\n    (ROOT / "src-tauri/src/services/s3_auto_sync.rs", re.compile(r"let _ = settings::update_s3_sync_status\\("), "S3 auto-sync status persistence errors must be observable"),\n]\n\nfailures = []\nfor path, pattern, message in CHECKS:\n    if pattern.search(path.read_text(encoding="utf-8")):\n        failures.append(f"{path.relative_to(ROOT)}: {message}")\n\nif failures:\n    print("Rust failure-boundary policy violations:", file=sys.stderr)\n    for failure in failures:\n        print(f"- {failure}", file=sys.stderr)\n    raise SystemExit(1)\n\nprint("Rust failure-boundary policy checks passed")\n''',
    encoding="utf-8",
)

print("One-shot branch hardening patches applied")
