#!/usr/bin/env python3
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected 1 exact match, found {count}")
    return text.replace(old, new, 1)


def replace_between(text: str, start: str, end: str, new: str, label: str) -> str:
    if text.count(start) != 1:
        raise SystemExit(f"{label}: start marker count={text.count(start)}")
    start_idx = text.index(start)
    end_idx = text.index(end, start_idx)
    return text[:start_idx] + new + text[end_idx:]


# ---------------------------------------------------------------------------
# config.rs: make absolute persistence paths a common invariant, not a caller
# convention; expose fallible app-root resolution and validate Windows legacy
# HOME before compatibility fallback.
# ---------------------------------------------------------------------------
path = Path("src-tauri/src/config.rs")
text = path.read_text(encoding="utf-8")

marker = "const ATOMIC_TEMP_CREATE_ATTEMPTS: usize = 16;\n"
helper = '''

fn require_absolute_path(path: PathBuf, label: &str) -> Result<PathBuf, String> {
    if path.is_absolute() {
        Ok(path)
    } else {
        Err(format!("{label} 必须是绝对路径，收到: {}", path.display()))
    }
}
'''
if "fn require_absolute_path(" not in text:
    text = replace_once(text, marker, marker + helper, "config absolute-path helper")

text = replace_between(
    text,
    "fn resolve_home_dir(\n",
    "\n/// 获取用户主目录。",
    '''fn resolve_home_dir(
    test_override: Option<&str>,
    detected: Option<PathBuf>,
) -> Result<PathBuf, String> {
    if let Some(home) = test_override.map(str::trim).filter(|home| !home.is_empty()) {
        return require_absolute_path(PathBuf::from(home), "CC_SWITCH_TEST_HOME");
    }

    let path = detected.ok_or_else(|| {
        "无法获取用户主目录；拒绝回退到当前工作目录，以避免配置/数据库静默分叉".to_string()
    })?;
    require_absolute_path(path, "操作系统返回的用户主目录")
}
''',
    "config home resolver",
)

expand_start = "pub fn expand_home_path(raw: &str) -> Result<PathBuf, String> {"
expand_end = "\n/// Last-resort crash/exit observability directory"
expand_new = '''pub fn expand_home_path(raw: &str) -> Result<PathBuf, String> {
    if raw == "~" {
        return try_get_home_dir();
    }
    if let Some(stripped) = raw.strip_prefix("~/") {
        return Ok(try_get_home_dir()?.join(stripped));
    }
    if let Some(stripped) = raw.strip_prefix("~\\\\") {
        return Ok(try_get_home_dir()?.join(stripped));
    }
    Ok(PathBuf::from(raw))
}

/// Resolve a user-configurable persistence/configuration root.
///
/// Unlike generic path expansion, this contract never permits process-CWD-relative roots.
/// Callers may accept `~`, but the resolved value must be absolute before it can select a
/// database, backup, settings, or external CLI configuration tree.
pub fn resolve_persistence_path(raw: &str, label: &str) -> Result<PathBuf, String> {
    let trimmed = raw.trim();
    if trimmed.is_empty() {
        return Err(format!("{label} 不能为空"));
    }
    let path = expand_home_path(trimmed)?;
    require_absolute_path(path, label)
}
'''
text = replace_between(text, expand_start, expand_end, expand_new, "config persistence resolver")

app_start = "pub fn get_app_config_dir() -> PathBuf {"
app_end = "\n/// 获取应用配置文件路径"
app_new = '''pub fn try_get_app_config_dir() -> Result<PathBuf, String> {
    if let Some(custom) = crate::app_store::get_app_config_dir_override() {
        return require_absolute_path(custom, "app_config_dir override");
    }

    let default_dir = try_get_home_dir()?.join(".cc-switch");

    // 兼容 v3.10.3：当用户环境存在 HOME 且与真实用户目录不同，
    // v3.10.3 可能在 HOME/.cc-switch/ 下创建/使用了数据库。
    // 兼容候选本身也必须是绝对路径；相对 HOME 不能重新引入 CWD 绑定。
    #[cfg(windows)]
    {
        let default_db = default_dir.join("cc-switch.db");
        if !default_db.exists() {
            if let Ok(home_env) = std::env::var("HOME") {
                let trimmed = home_env.trim();
                if !trimmed.is_empty() {
                    let legacy_home = PathBuf::from(trimmed);
                    if legacy_home.is_absolute() {
                        let legacy_dir = legacy_home.join(".cc-switch");
                        if legacy_dir.join("cc-switch.db").exists() {
                            log::info!(
                                "Detected v3.10.3 legacy database at {}, using it instead of {}",
                                legacy_dir.display(),
                                default_dir.display()
                            );
                            return Ok(legacy_dir);
                        }
                    } else {
                        log::warn!(
                            "Ignoring relative legacy HOME while locating v3.10.3 database: {}",
                            legacy_home.display()
                        );
                    }
                }
            }
        }
    }

    Ok(default_dir)
}

/// Compatibility wrapper for legacy infallible path APIs. New fallible persistence operations
/// should call `try_get_app_config_dir` so configuration errors remain typed instead of panicking.
pub fn get_app_config_dir() -> PathBuf {
    try_get_app_config_dir().unwrap_or_else(|err| {
        log::error!("{err}");
        panic!("{err}");
    })
}
'''
text = replace_between(text, app_start, app_end, app_new, "config app root")

test_anchor = '''    #[test]
    fn explicit_relative_test_home_override_is_rejected() {
        assert!(resolve_home_dir(Some("relative-test-home"), None).is_err());
    }
'''
extra_tests = '''    #[test]
    fn explicit_relative_test_home_override_is_rejected() {
        assert!(resolve_home_dir(Some("relative-test-home"), None).is_err());
    }

    #[test]
    fn persistence_roots_reject_process_relative_paths() {
        assert!(resolve_persistence_path("relative/profile", "test root").is_err());
    }

    #[test]
    fn persistence_roots_accept_absolute_paths() {
        let path = std::env::temp_dir().join("cc-switch-persistence-root");
        let raw = path.to_string_lossy().to_string();
        assert_eq!(resolve_persistence_path(&raw, "test root").unwrap(), path);
    }
'''
text = replace_once(text, test_anchor, extra_tests, "config persistence tests")
path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# app_store.rs: Store access/migration failure is not equivalent to no override.
# Invalid/missing/non-directory roots fail closed, and user writes are validated
# before persistence. A successful no-op migration is marked complete as well.
# ---------------------------------------------------------------------------
path = Path("src-tauri/src/app_store.rs")
text = path.read_text(encoding="utf-8")

text = replace_between(
    text,
    "fn read_override_from_store(app: &tauri::AppHandle) -> Option<PathBuf> {",
    "\nfn legacy_migration_completed",
    '''fn read_override_from_store(app: &tauri::AppHandle) -> Result<Option<PathBuf>, AppError> {
    let store = open_paths_store(app)?;

    match store.get(STORE_KEY_APP_CONFIG_DIR) {
        Some(Value::String(path_str)) => {
            let path_str = path_str.trim();
            if path_str.is_empty() {
                return Ok(None);
            }

            let path = resolve_path(path_str)?;
            if !path.is_dir() {
                return Err(AppError::Config(format!(
                    "Store 中配置的 app_config_dir 不是现有目录: {}",
                    path.display()
                )));
            }

            log::info!("使用 Store 中的 app_config_dir: {path:?}");
            Ok(Some(path))
        }
        Some(_) => Err(AppError::Config(format!(
            "Store 中的 {STORE_KEY_APP_CONFIG_DIR} 类型不正确，应为字符串"
        ))),
        None => Ok(None),
    }
}
''',
    "app_store read override",
)

text = replace_between(
    text,
    "fn legacy_migration_completed(app: &tauri::AppHandle) -> bool {",
    "\n/// 从旧版",
    '''fn legacy_migration_completed(app: &tauri::AppHandle) -> Result<bool, AppError> {
    let store = open_paths_store(app)?;
    match store.get(STORE_KEY_APP_CONFIG_DIR_LEGACY_MIGRATED) {
        Some(Value::Bool(value)) => Ok(value),
        Some(_) => Err(AppError::Config(format!(
            "Store 中的 {STORE_KEY_APP_CONFIG_DIR_LEGACY_MIGRATED} 类型不正确，应为布尔值"
        ))),
        None => Ok(false),
    }
}
''',
    "app_store migration marker",
)

text = replace_between(
    text,
    "fn read_legacy_override_from_settings() -> Option<PathBuf> {",
    "\nfn persist_override_and_migration_marker",
    '''fn read_legacy_override_from_settings() -> Result<Option<PathBuf>, AppError> {
    let settings_path = crate::config::try_get_home_dir()
        .map_err(AppError::Config)?
        .join(".cc-switch")
        .join("settings.json");
    let content = match std::fs::read_to_string(&settings_path) {
        Ok(content) => content,
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(err) => return Err(AppError::io(&settings_path, err)),
    };

    let root: Value = serde_json::from_str(&content)
        .map_err(|err| AppError::json(&settings_path, err))?;

    for key in LEGACY_APP_CONFIG_DIR_KEYS {
        let Some(raw) = root.get(*key).and_then(Value::as_str) else {
            continue;
        };
        let trimmed = raw.trim();
        if trimmed.is_empty() {
            continue;
        }
        let resolved = resolve_path(trimmed)?;
        if !resolved.is_dir() {
            return Err(AppError::Config(format!(
                "旧 settings.json 的 {key} 不是现有目录: {}",
                resolved.display()
            )));
        }
        return Ok(Some(resolved));
    }

    Ok(None)
}
''',
    "app_store legacy reader",
)

text = replace_between(
    text,
    "fn migrate_legacy_override_if_needed(app: &tauri::AppHandle) -> Result<Option<PathBuf>, AppError> {",
    "\n/// 从 Store 刷新",
    '''fn migrate_legacy_override_if_needed(app: &tauri::AppHandle) -> Result<Option<PathBuf>, AppError> {
    if legacy_migration_completed(app)? {
        return Ok(None);
    }

    if let Some(existing_path) = read_override_from_store(app)? {
        // 已经存在新格式配置，只补迁移标记，绝不能用尚未初始化的缓存反写 Store。
        let path_string = existing_path.to_string_lossy().to_string();
        persist_override_and_migration_marker(app, Some(&path_string))?;
        return Ok(Some(existing_path));
    }

    match read_legacy_override_from_settings()? {
        Some(legacy_path) => {
            let path_string = legacy_path.to_string_lossy().to_string();
            persist_override_and_migration_marker(app, Some(&path_string))?;
            log::info!(
                "已将旧 settings.json 的 app_config_dir 自动迁移到 Store: {}",
                legacy_path.display()
            );
            Ok(Some(legacy_path))
        }
        None => {
            // A successful scan with no legacy value is still a completed one-time migration.
            // Persist the marker so a stale legacy field cannot unexpectedly resurrect later.
            persist_override_and_migration_marker(app, None)?;
            Ok(None)
        }
    }
}
''',
    "app_store migration",
)

text = replace_between(
    text,
    "pub fn refresh_app_config_dir_override(app: &tauri::AppHandle) -> Option<PathBuf> {",
    "\n/// 写入 app_config_dir",
    '''pub fn refresh_app_config_dir_override(
    app: &tauri::AppHandle,
) -> Result<Option<PathBuf>, AppError> {
    let migrated = migrate_legacy_override_if_needed(app)?;
    let value = match migrated {
        Some(path) => Some(path),
        None => read_override_from_store(app)?,
    };
    update_cached_override(value.clone());
    Ok(value)
}
''',
    "app_store refresh",
)

text = replace_between(
    text,
    "pub fn set_app_config_dir_to_store(\n",
    "\n/// 解析路径",
    '''pub fn set_app_config_dir_to_store(
    app: &tauri::AppHandle,
    path: Option<&str>,
) -> Result<(), AppError> {
    let resolved = match path.map(str::trim).filter(|value| !value.is_empty()) {
        Some(value) => {
            let path = resolve_path(value)?;
            if !path.is_dir() {
                return Err(AppError::InvalidInput(format!(
                    "app_config_dir 必须指向现有目录: {}",
                    path.display()
                )));
            }
            Some(path)
        }
        None => None,
    };
    let serialized = resolved
        .as_ref()
        .map(|path| path.to_string_lossy().to_string());
    persist_override_and_migration_marker(app, serialized.as_deref())?;
    update_cached_override(resolved.clone());

    match resolved {
        Some(value) => log::info!("已将 app_config_dir 写入 Store: {}", value.display()),
        None => log::info!("已从 Store 中删除 app_config_dir 配置"),
    }
    Ok(())
}
''',
    "app_store setter",
)

text = replace_between(
    text,
    "fn resolve_path(raw: &str) -> PathBuf {",
    "\n/// 从旧的 settings.json",
    '''fn resolve_path(raw: &str) -> Result<PathBuf, AppError> {
    crate::config::resolve_persistence_path(raw, "app_config_dir")
        .map_err(AppError::InvalidInput)
}
''',
    "app_store path resolver",
)

text = replace_between(
    text,
    "pub fn migrate_app_config_dir_from_settings(app: &tauri::AppHandle) -> Result<(), AppError> {",
    "\n#[cfg(test)]",
    '''pub fn migrate_app_config_dir_from_settings(app: &tauri::AppHandle) -> Result<(), AppError> {
    let migrated = migrate_legacy_override_if_needed(app)?;
    let value = match migrated {
        Some(path) => Some(path),
        None => read_override_from_store(app)?,
    };
    update_cached_override(value);
    Ok(())
}
''',
    "app_store compatibility entrypoint",
)

text = replace_once(
    text,
    "        assert_eq!(resolve_path(input), PathBuf::from(input));",
    "        assert_eq!(resolve_path(input).unwrap(), PathBuf::from(input));",
    "app_store absolute test",
)
legacy_test_anchor = '''    #[test]
    fn legacy_keys_cover_camel_and_snake_case() {'''
relative_test = '''    #[test]
    fn resolve_path_rejects_process_relative_app_root() {
        assert!(resolve_path("relative/.cc-switch").is_err());
    }

'''
text = replace_once(text, legacy_test_anchor, relative_test + legacy_test_anchor, "app_store relative test")
path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# settings.rs: make the settings path fallible instead of fake-Optional; enforce
# an in-memory invariant that all per-CLI config-dir overrides are absolute.
# Dirty legacy relative values are quarantined (logged + ignored), while new
# frontend writes are rejected with InvalidInput instead of silently normalizing.
# ---------------------------------------------------------------------------
path = Path("src-tauri/src/settings.rs")
text = path.read_text(encoding="utf-8")

insert_before = "impl AppSettings {\n"
settings_helpers = '''fn normalize_config_dir_override(field: &str, value: Option<String>) -> Option<String> {
    let raw = value?.trim().to_string();
    if raw.is_empty() {
        return None;
    }
    match crate::config::resolve_persistence_path(&raw, field) {
        Ok(path) => Some(path.to_string_lossy().to_string()),
        Err(err) => {
            log::error!("Ignoring invalid persisted {field}: {err}");
            None
        }
    }
}

fn validate_config_dir_overrides(settings: &AppSettings) -> Result<(), AppError> {
    let values = [
        ("claude_config_dir", settings.claude_config_dir.as_deref()),
        ("codex_config_dir", settings.codex_config_dir.as_deref()),
        ("gemini_config_dir", settings.gemini_config_dir.as_deref()),
        ("opencode_config_dir", settings.opencode_config_dir.as_deref()),
        ("openclaw_config_dir", settings.openclaw_config_dir.as_deref()),
        ("hermes_config_dir", settings.hermes_config_dir.as_deref()),
    ];
    for (field, raw) in values {
        if let Some(raw) = raw.map(str::trim).filter(|raw| !raw.is_empty()) {
            crate::config::resolve_persistence_path(raw, field)
                .map_err(AppError::InvalidInput)?;
        }
    }
    Ok(())
}

'''
if "fn normalize_config_dir_override(" not in text:
    text = replace_once(text, insert_before, settings_helpers + insert_before, "settings helpers")

text = replace_between(
    text,
    "    fn settings_path() -> Option<PathBuf> {",
    "\n    fn normalize_paths(&mut self) {",
    '''    fn settings_path() -> Result<PathBuf, AppError> {
        Ok(crate::config::try_get_home_dir()
            .map_err(AppError::Config)?
            .join(".cc-switch")
            .join("settings.json"))
    }
''',
    "settings path",
)

norm_start = "        self.claude_config_dir = self\n"
norm_end = "\n        self.language = self"
normalized_fields = '''        self.claude_config_dir = normalize_config_dir_override(
            "claude_config_dir",
            self.claude_config_dir.take(),
        );
        self.codex_config_dir = normalize_config_dir_override(
            "codex_config_dir",
            self.codex_config_dir.take(),
        );
        self.gemini_config_dir = normalize_config_dir_override(
            "gemini_config_dir",
            self.gemini_config_dir.take(),
        );
        self.opencode_config_dir = normalize_config_dir_override(
            "opencode_config_dir",
            self.opencode_config_dir.take(),
        );
        self.openclaw_config_dir = normalize_config_dir_override(
            "openclaw_config_dir",
            self.openclaw_config_dir.take(),
        );
        self.hermes_config_dir = normalize_config_dir_override(
            "hermes_config_dir",
            self.hermes_config_dir.take(),
        );
'''
text = replace_between(text, norm_start, norm_end, normalized_fields, "settings path normalization")

old_load = '''    fn load_from_file() -> Self {
        let Some(path) = Self::settings_path() else {
            return Self::default();
        };
        Self::load_from_path(&path)
    }
'''
new_load = '''    fn load_from_file() -> Self {
        match Self::settings_path() {
            Ok(path) => Self::load_from_path(&path),
            Err(err) => {
                log::error!("无法解析 settings.json 路径，将使用内存默认设置且禁止持久化: {err}");
                Self::default()
            }
        }
    }
'''
text = replace_once(text, old_load, new_load, "settings load path")

old_save = '''fn save_settings_file(settings: &AppSettings) -> Result<(), AppError> {
    let Some(path) = AppSettings::settings_path() else {
        return Err(AppError::Config("无法获取用户主目录".to_string()));
    };
    save_settings_file_to_path(settings, &path)
}
'''
new_save = '''fn save_settings_file(settings: &AppSettings) -> Result<(), AppError> {
    let path = AppSettings::settings_path()?;
    save_settings_file_to_path(settings, &path)
}
'''
text = replace_once(text, old_save, new_save, "settings save path")

old_resolver = '''fn resolve_override_path(raw: &str) -> PathBuf {
    crate::config::expand_home_path(raw).unwrap_or_else(|err| {
        log::error!("{err}");
        panic!("{err}");
    })
}
'''
new_resolver = '''fn resolve_override_path(raw: &str) -> Option<PathBuf> {
    let path = PathBuf::from(raw);
    if path.is_absolute() {
        Some(path)
    } else {
        log::error!("settings path invariant violated by relative override: {raw}");
        None
    }
}
'''
text = replace_once(text, old_resolver, new_resolver, "settings getter resolver")

if text.count(".map(|p| resolve_override_path(p))") != 6:
    raise SystemExit(
        f"settings override getter map count={text.count('.map(|p| resolve_override_path(p))')}"
    )
text = text.replace(".map(|p| resolve_override_path(p))", ".and_then(|p| resolve_override_path(p))")

old_update = '''pub fn update_settings(mut new_settings: AppSettings) -> Result<(), AppError> {
    new_settings.normalize_paths();
'''
new_update = '''pub fn update_settings(mut new_settings: AppSettings) -> Result<(), AppError> {
    validate_config_dir_overrides(&new_settings)?;
    new_settings.normalize_paths();
'''
text = replace_once(text, old_update, new_update, "settings update validation")
path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Startup/DB: propagate Store and app-root resolution failures rather than
# treating them as absence or panicking during normal setup.
# ---------------------------------------------------------------------------
path = Path("src-tauri/src/lib.rs")
text = path.read_text(encoding="utf-8")
old_setup = '''            // 预先刷新 Store 覆盖配置，确保后续路径读取正确（日志/数据库等）
            app_store::refresh_app_config_dir_override(app.handle());
            let app_config_dir = crate::config::get_app_config_dir();
            panic_hook::init_app_config_dir(app_config_dir.clone());
            app_exit_monitor::init_app_config_dir(app_config_dir);
'''
new_setup = '''            // 预先刷新 Store 覆盖配置，确保后续路径读取正确（日志/数据库等）。
            // Store/路径损坏不能伪装成“无 override”后切到另一个数据库根。
            app_store::refresh_app_config_dir_override(app.handle())?;
            let app_config_dir = crate::config::try_get_app_config_dir()
                .map_err(crate::error::AppError::Config)?;
            panic_hook::init_app_config_dir(app_config_dir.clone());
            app_exit_monitor::init_app_config_dir(app_config_dir.clone());
'''
text = replace_once(text, old_setup, new_setup, "startup app root")
text = replace_once(
    text,
    '''            // 初始化数据库
            let app_config_dir = crate::config::get_app_config_dir();
            let db_path = app_config_dir.join("cc-switch.db");
''',
    '''            // 初始化数据库
            let db_path = app_config_dir.join("cc-switch.db");
''',
    "startup reuse validated root",
)
path.write_text(text, encoding="utf-8")

path = Path("src-tauri/src/database/mod.rs")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "use crate::config::get_app_config_dir;",
    "use crate::config::try_get_app_config_dir;",
    "database import",
)
text = replace_once(
    text,
    '''        let db_path = get_app_config_dir().join("cc-switch.db");''',
    '''        let db_path = try_get_app_config_dir()
            .map_err(AppError::Config)?
            .join("cc-switch.db");''',
    "database app root",
)
path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# model_fetch.rs: fail-fast HTTP classification must not imply raw-body
# disclosure. Use common payload shape/fingerprint diagnostics instead.
# ---------------------------------------------------------------------------
path = Path("src-tauri/src/services/model_fetch.rs")
text = path.read_text(encoding="utf-8")
text = text.replace(
    '''/// 404/405 响应体截断长度：避免把几十 KB HTML 404 页整页保留到错误串里。
const ERROR_BODY_MAX_CHARS: usize = 512;

''',
    "",
)
old_http_error = '''        let body = truncate_body(response.text().await.unwrap_or_default());
        return Err(format!("HTTP {status}: {body}"));
'''
new_http_error = '''        let body_detail = match response.bytes().await {
            Ok(body) => {
                let rendered = String::from_utf8_lossy(&body);
                format!(
                    "body-shape={}, {}",
                    crate::diagnostics::text_shape_hint(&rendered),
                    crate::diagnostics::payload_fingerprint(&body)
                )
            }
            Err(error) => format!("body-unavailable={}", request_error_kind(&error)),
        };
        return Err(format!("HTTP {status}: {body_detail}"));
'''
text = replace_once(text, old_http_error, new_http_error, "model safe fail-fast detail")
truncate_start = "/// 截断响应体到 [`ERROR_BODY_MAX_CHARS`] 字符，避免 HTML 404 页占用错误串。\nfn truncate_body(body: String) -> String {"
if truncate_start in text:
    start = text.index(truncate_start)
    # Function is immediately followed by a blank line + the next item.
    next_item = text.find("\n\n", start)
    # Advance until the function's closing brace is covered; exact body is stable here.
    old_truncate = '''/// 截断响应体到 [`ERROR_BODY_MAX_CHARS`] 字符，避免 HTML 404 页占用错误串。
fn truncate_body(body: String) -> String {
    if body.chars().count() <= ERROR_BODY_MAX_CHARS {
        body
    } else {
        let mut s: String = body.chars().take(ERROR_BODY_MAX_CHARS).collect();
        s.push('…');
        s
    }
}

'''
    text = replace_once(text, old_truncate, "", "model obsolete raw-body helper")

# Add a pure diagnostic regression next to retry-policy tests when present.
test_anchor = '''    #[test]
    fn candidate_failure_details_are_bounded() {'''
if test_anchor in text and "fail_fast_http_diagnostics_do_not_require_raw_body" not in text:
    safe_test = '''    #[test]
    fn fail_fast_http_diagnostics_do_not_require_raw_body() {
        let secret = b"{\\\"token\\\":\\\"super-secret\\\"}";
        let rendered = String::from_utf8_lossy(secret);
        let detail = format!(
            "body-shape={}, {}",
            crate::diagnostics::text_shape_hint(&rendered),
            crate::diagnostics::payload_fingerprint(secret)
        );
        assert!(detail.contains("body-shape=json-like"));
        assert!(detail.contains("bytes="));
        assert!(!detail.contains("super-secret"));
    }

'''
    text = replace_once(text, test_anchor, safe_test + test_anchor, "model safe diagnostics test")
path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Permanent source-level guards encode the design invariants so future green
# tests cannot reintroduce the same architectural failure modes.
# ---------------------------------------------------------------------------
path = Path("scripts/check_rust_failure_boundaries.py")
text = path.read_text(encoding="utf-8")
old_checks_tail = '''    ("services/model_fetch.rs", re.compile(r'\\.json\\(\\)\\s*\\.await\\s*\\.map_err\\(\\|e\\| format!\\(\\"Failed to parse response:', re.S), "invalid successful model payloads must not abort compatibility candidate discovery"),
]'''
new_checks_tail = '''    ("services/model_fetch.rs", re.compile(r'\\.json\\(\\)\\s*\\.await\\s*\\.map_err\\(\\|e\\| format!\\(\\"Failed to parse response:', re.S), "invalid successful model payloads must not abort compatibility candidate discovery"),
    ("services/model_fetch.rs", re.compile(r'HTTP \\{status\\}: \\{body\\}'), "model-discovery errors must not expose raw upstream response bodies"),
    ("app_store.rs", re.compile(r"fn read_override_from_store\\([^)]*\\) -> Option<PathBuf>"), "Store read failure must not collapse into an absent app_config_dir override"),
    ("app_store.rs", re.compile(r"fn resolve_path\\(raw: &str\\) -> PathBuf"), "app_config_dir parsing must be fallible and reject relative persistence roots"),
    ("settings.rs", re.compile(r"fn settings_path\\(\\) -> Option<PathBuf>"), "settings path resolution must expose HOME failures instead of a fake Option contract"),
]'''
text = replace_once(text, old_checks_tail, new_checks_tail, "policy explicit checks")

extra_guard_anchor = '''# User-home resolution is a persistence boundary shared by DB/config/backup/CLI paths. A direct
# dirs::home_dir() call elsewhere can silently re-introduce CWD/relative fallback semantics or
# diverge from the validated CC_SWITCH_TEST_HOME behavior, so keep one common implementation.
'''
extra_guard = '''# Persistence roots must never accept a process-relative Store/settings override. These patterns
# previously bypassed the HOME guard while still binding DB/config state to the launch CWD.
config_text = (RUST_ROOT / "config.rs").read_text(encoding="utf-8")
if 'let legacy_dir = PathBuf::from(trimmed).join(".cc-switch")' in config_text:
    failures.append(
        "src-tauri/src/config.rs: Windows legacy HOME must be checked as absolute before DB fallback"
    )

'''
text = replace_once(text, extra_guard_anchor, extra_guard + extra_guard_anchor, "policy persistence guard")
path.write_text(text, encoding="utf-8")

print("Applied design-invariant hardening patch")
