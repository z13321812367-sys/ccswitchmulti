#!/usr/bin/env python3
from pathlib import Path
import re


def read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    Path(path).write_text(text, encoding="utf-8")


def replace_exact(path: str, old: str, new: str, label: str, expected: int = 1) -> None:
    text = read(path)
    count = text.count(old)
    if count != expected:
        raise SystemExit(f"{label}: expected {expected} matches, found {count}")
    write(path, text.replace(old, new))


def replace_region(path: str, start: str, end: str, new: str, label: str) -> None:
    text = read(path)
    if text.count(start) != 1:
        raise SystemExit(f"{label}: start count={text.count(start)}")
    i = text.index(start)
    try:
        j = text.index(end, i)
    except ValueError:
        raise SystemExit(f"{label}: end marker missing")
    write(path, text[:i] + new + text[j:])


# Command boundary: Option means genuine absence; Result means Store/path failure.
replace_region(
    "src-tauri/src/commands/settings.rs",
    "pub async fn get_app_config_dir_override(app: AppHandle) -> Result<Option<String>, String> {",
    "\n}\n\n/// 设置 app_config_dir 覆盖配置",
    '''pub async fn get_app_config_dir_override(app: AppHandle) -> Result<Option<String>, String> {
    let value = crate::app_store::refresh_app_config_dir_override(&app)
        .map_err(|err| err.to_string())?;
    Ok(value.map(|path| path.to_string_lossy().to_string()))
''',
    "settings command propagation",
)


# Skill path APIs already return Result, so they must not hide panic-based path wrappers.
replace_exact(
    "src-tauri/src/services/skill.rs",
    "use crate::config::get_app_config_dir;\n",
    "",
    "remove infallible skill import",
)
replace_exact(
    "src-tauri/src/services/skill.rs",
    'SkillStorageLocation::CcSwitch => get_app_config_dir().join("skills"),',
    '''SkillStorageLocation::CcSwitch => crate::config::try_get_app_config_dir()
                .map_err(|err| anyhow!(err))?
                .join("skills"),''',
    "skill cc-switch roots",
    expected=2,
)
replace_exact(
    "src-tauri/src/services/skill.rs",
    'let dir = get_app_config_dir().join("skill-backups");',
    '''let dir = crate::config::try_get_app_config_dir()
            .map_err(|err| anyhow!(err))?
            .join("skill-backups");''',
    "skill backup root",
)
# The remaining infallible HOME call in this module is the default app skills root.
replace_exact(
    "src-tauri/src/services/skill.rs",
    "let home = crate::config::get_home_dir();",
    "let home = crate::config::try_get_home_dir().map_err(|err| anyhow!(err))?;",
    "skill app HOME",
)


# CLI discovery is best-effort: loss of HOME removes HOME-scoped candidates, not the feature.
replace_region(
    "src-tauri/src/commands/misc.rs",
    "fn build_tool_search_paths(tool: &str) -> Vec<std::path::PathBuf> {",
    '\n#[cfg(target_os = "windows")]\nfn is_windows_command_script',
    '''fn build_tool_search_paths(tool: &str) -> Vec<std::path::PathBuf> {
    let home = crate::config::try_get_home_dir().ok();
    let mut search_paths: Vec<std::path::PathBuf> = Vec::new();

    if let Some(home) = home.as_ref() {
        push_unique_path(&mut search_paths, home.join(".local/bin"));
        push_unique_path(&mut search_paths, home.join(".npm-global/bin"));
        push_unique_path(&mut search_paths, home.join("n/bin"));
        push_unique_path(&mut search_paths, home.join(".volta/bin"));
        extend_mise_node_search_paths(&mut search_paths, home);

        for base in [home.join(".local/state/fnm_multishells"), home.join(".nvm/versions/node")] {
            if let Ok(entries) = std::fs::read_dir(&base) {
                for entry in entries.flatten() {
                    let bin_path = entry.path().join("bin");
                    if bin_path.exists() {
                        push_unique_path(&mut search_paths, bin_path);
                    }
                }
            }
        }
    } else {
        log::warn!("HOME unavailable while discovering CLI tools; skipping home-scoped candidates");
    }

    #[cfg(target_os = "macos")]
    {
        push_unique_path(&mut search_paths, std::path::PathBuf::from("/opt/homebrew/bin"));
        push_unique_path(&mut search_paths, std::path::PathBuf::from("/usr/local/bin"));
        if tool == "hermes" {
            if let Some(home) = home.as_ref() {
                let python_base = home.join("Library").join("Python");
                if let Ok(entries) = std::fs::read_dir(&python_base) {
                    for entry in entries.flatten() {
                        let bin_path = entry.path().join("bin");
                        if bin_path.exists() {
                            push_unique_path(&mut search_paths, bin_path);
                        }
                    }
                }
            }
        }
    }

    #[cfg(target_os = "linux")]
    {
        push_unique_path(&mut search_paths, std::path::PathBuf::from("/usr/local/bin"));
        push_unique_path(&mut search_paths, std::path::PathBuf::from("/usr/bin"));
    }

    #[cfg(target_os = "windows")]
    {
        if let Some(appdata) = dirs::data_dir() {
            push_unique_path(&mut search_paths, appdata.join("npm"));
            if tool == "hermes" {
                let python_base = appdata.join("Python");
                if let Ok(entries) = std::fs::read_dir(&python_base) {
                    for entry in entries.flatten() {
                        let scripts_path = entry.path().join("Scripts");
                        if scripts_path.exists() {
                            push_unique_path(&mut search_paths, scripts_path);
                        }
                    }
                }
            }
        }
        if tool == "hermes" {
            if let Some(local_data) = dirs::data_local_dir() {
                let programs_python = local_data.join("Programs").join("Python");
                if let Ok(entries) = std::fs::read_dir(&programs_python) {
                    for entry in entries.flatten() {
                        let scripts_path = entry.path().join("Scripts");
                        if scripts_path.exists() {
                            push_unique_path(&mut search_paths, scripts_path);
                        }
                    }
                }
            }
        }
        push_unique_path(&mut search_paths, std::path::PathBuf::from("C:\\Program Files\\nodejs"));
        if let Some(home) = home.as_ref() {
            extend_windows_cli_manager_search_paths(&mut search_paths, home);
        }
    }

    if tool == "opencode" {
        let empty_home = Path::new("");
        for path in opencode_extra_search_paths(
            home.as_deref().unwrap_or(empty_home),
            std::env::var_os("OPENCODE_INSTALL_DIR"),
            std::env::var_os("XDG_BIN_DIR"),
            std::env::var_os("GOPATH"),
        ) {
            push_unique_path(&mut search_paths, path);
        }
    }

    // PATH intentionally retains shell/OS semantics; explicit manager/install roots above do not.
    extend_from_cli_path_env(&mut search_paths, std::env::var_os("PATH"));
    search_paths
}
''',
    "CLI discovery HOME semantics",
)
# Explicit installation-root environment variables are roots, not shell PATH entries: reject CWD-relative values.
replace_region(
    "src-tauri/src/commands/misc.rs",
    "fn push_env_single_dir(paths: &mut Vec<std::path::PathBuf>, value: Option<std::ffi::OsString>) {",
    "\n}\n\nfn extend_from_path_list",
    '''fn push_env_single_dir(paths: &mut Vec<std::path::PathBuf>, value: Option<std::ffi::OsString>) {
    if let Some(raw) = value {
        let path = std::path::PathBuf::from(raw);
        if path.is_absolute() {
            push_unique_path(paths, path);
        } else if !path.as_os_str().is_empty() {
            log::warn!("Ignoring relative CLI install root: {}", path.display());
        }
    }
''',
    "absolute CLI install roots",
)
replace_region(
    "src-tauri/src/commands/misc.rs",
    "fn extend_from_path_list(\n",
    "\n}\n\nfn extend_from_cli_path_env",
    '''fn extend_from_path_list(
    paths: &mut Vec<std::path::PathBuf>,
    value: Option<std::ffi::OsString>,
    suffix: Option<&str>,
) {
    if let Some(raw) = value {
        for base in std::env::split_paths(&raw) {
            if !base.is_absolute() {
                if !base.as_os_str().is_empty() {
                    log::warn!("Ignoring relative CLI path-list root: {}", base.display());
                }
                continue;
            }
            let dir = match suffix {
                Some(suffix) => base.join(suffix),
                None => base,
            };
            push_unique_path(paths, dir);
        }
    }
''',
    "absolute CLI path-list roots",
)


# OpenCode session roots are fallible and existing SQLite errors must be visible.
replace_region(
    "src-tauri/src/session_manager/providers/opencode.rs",
    "pub(crate) fn get_opencode_base_dir() -> PathBuf {",
    "\n/// Parse a SQLite source reference",
    '''fn try_get_opencode_base_dir() -> Result<PathBuf, String> {
    if let Ok(xdg) = std::env::var("XDG_DATA_HOME") {
        let xdg = PathBuf::from(xdg.trim());
        if xdg.is_absolute() {
            return Ok(xdg.join("opencode"));
        }
        if !xdg.as_os_str().is_empty() {
            log::warn!("Ignoring relative XDG_DATA_HOME for OpenCode discovery: {}", xdg.display());
        }
    }
    Ok(crate::config::try_get_home_dir()?.join(".local/share/opencode"))
}

pub(crate) fn get_opencode_data_dir() -> Result<PathBuf, String> {
    Ok(try_get_opencode_base_dir()?.join("storage"))
}

fn get_opencode_db_path() -> Result<PathBuf, String> {
    Ok(try_get_opencode_base_dir()?.join("opencode.db"))
}

pub fn scan_sessions() -> Result<Vec<SessionMeta>, String> {
    let json_sessions = scan_sessions_json()?;
    let sqlite_sessions = scan_sessions_sqlite()?;
    if sqlite_sessions.is_empty() {
        return Ok(json_sessions);
    }
    if json_sessions.is_empty() {
        return Ok(sqlite_sessions);
    }
    let sqlite_ids: std::collections::HashSet<String> = sqlite_sessions
        .iter().map(|session| session.session_id.clone()).collect();
    let mut merged = sqlite_sessions;
    for session in json_sessions {
        if !sqlite_ids.contains(&session.session_id) {
            merged.push(session);
        }
    }
    Ok(merged)
}

fn scan_sessions_json() -> Result<Vec<SessionMeta>, String> {
    let storage = get_opencode_data_dir()?;
    let session_dir = storage.join("session");
    if !session_dir.exists() {
        return Ok(Vec::new());
    }
    let mut json_files = Vec::new();
    collect_json_files(&session_dir, &mut json_files);
    let mut sessions = Vec::new();
    for path in json_files {
        if let Some(meta) = parse_session(&storage, &path) {
            sessions.push(meta);
        }
    }
    Ok(sessions)
}
''',
    "OpenCode fallible roots",
)
replace_region(
    "src-tauri/src/session_manager/providers/opencode.rs",
    "fn scan_sessions_sqlite() -> Vec<SessionMeta> {",
    "\npub fn load_messages(path: &Path)",
    '''fn scan_sessions_sqlite() -> Result<Vec<SessionMeta>, String> {
    let db_path = get_opencode_db_path()?;
    if !db_path.exists() {
        return Ok(Vec::new());
    }
    let conn = Connection::open_with_flags(
        &db_path,
        rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY | rusqlite::OpenFlags::SQLITE_OPEN_NO_MUTEX,
    ).map_err(|err| format!("Failed to open OpenCode session database {}: {err}", db_path.display()))?;
    let mut stmt = conn.prepare(
        "SELECT id, title, directory, time_created, time_updated FROM session ORDER BY time_updated DESC",
    ).map_err(|err| format!("Failed to prepare OpenCode session query: {err}"))?;
    let db_display = db_path.display().to_string();
    let rows = stmt.query_map([], |row| {
        Ok((
            row.get::<_, String>(0)?,
            row.get::<_, String>(1)?,
            row.get::<_, String>(2)?,
            row.get::<_, i64>(3)?,
            row.get::<_, i64>(4)?,
        ))
    }).map_err(|err| format!("Failed to query OpenCode sessions: {err}"))?;
    let mut sessions = Vec::new();
    for row in rows {
        let (session_id, title, directory, created, updated) =
            row.map_err(|err| format!("Failed to decode OpenCode session row: {err}"))?;
        let display_title = if title.is_empty() { path_basename(&directory) } else { Some(title) };
        sessions.push(SessionMeta {
            provider_id: PROVIDER_ID.to_string(),
            session_id: session_id.clone(),
            title: display_title.clone(),
            summary: display_title,
            project_dir: if directory.is_empty() { None } else { Some(directory) },
            created_at: Some(created),
            last_active_at: Some(updated),
            source_path: Some(format!("sqlite:{db_display}:{session_id}")),
            resume_command: Some(format!("opencode session resume {session_id}")),
        });
    }
    Ok(sessions)
}
''',
    "OpenCode SQLite observability",
)
replace_exact(
    "src-tauri/src/session_manager/providers/opencode.rs",
    "let expected_db_path = get_opencode_db_path()\n",
    "let expected_db_path = get_opencode_db_path()?\n",
    "OpenCode delete root",
)


# Session worker panic is an error, not an empty provider result.
replace_region(
    "src-tauri/src/session_manager/mod.rs",
    "pub fn scan_sessions() -> Vec<SessionMeta> {",
    "\npub fn load_messages",
    '''pub fn scan_sessions() -> Result<Vec<SessionMeta>, String> {
    let (r1, r2, r3, r4, r5, r6) = std::thread::scope(|scope| -> Result<_, String> {
        let h1 = scope.spawn(codex::scan_sessions);
        let h2 = scope.spawn(claude::scan_sessions);
        let h3 = scope.spawn(opencode::scan_sessions);
        let h4 = scope.spawn(openclaw::scan_sessions);
        let h5 = scope.spawn(gemini::scan_sessions);
        let h6 = scope.spawn(hermes::scan_sessions);

        let r1 = h1.join().map_err(|_| "Codex session scan panicked".to_string())?;
        let r2 = h2.join().map_err(|_| "Claude session scan panicked".to_string())?;
        let r3 = h3.join().map_err(|_| "OpenCode session scan panicked".to_string())??;
        let r4 = h4.join().map_err(|_| "OpenClaw session scan panicked".to_string())?;
        let r5 = h5.join().map_err(|_| "Gemini session scan panicked".to_string())?;
        let r6 = h6.join().map_err(|_| "Hermes session scan panicked".to_string())?;
        Ok((r1, r2, r3, r4, r5, r6))
    })?;

    let mut sessions = Vec::new();
    sessions.extend(r1);
    sessions.extend(r2);
    sessions.extend(r3);
    sessions.extend(r4);
    sessions.extend(r5);
    sessions.extend(r6);
    sessions.sort_by(|a, b| {
        b.last_active_at.or(b.created_at).unwrap_or(0)
            .cmp(&a.last_active_at.or(a.created_at).unwrap_or(0))
    });
    Ok(sessions)
}
''',
    "session worker observability",
)
replace_exact(
    "src-tauri/src/session_manager/mod.rs",
    '"opencode" => vec![opencode::get_opencode_data_dir()],',
    '"opencode" => vec![opencode::get_opencode_data_dir()?],',
    "OpenCode provider deletion root",
)
replace_region(
    "src-tauri/src/commands/session_manager.rs",
    "pub async fn list_sessions() -> Result<Vec<session_manager::SessionMeta>, String> {",
    "\n}\n\n#[tauri::command]\npub async fn get_session_messages",
    '''pub async fn list_sessions() -> Result<Vec<session_manager::SessionMeta>, String> {
    tauri::async_runtime::spawn_blocking(session_manager::scan_sessions)
        .await
        .map_err(|err| format!("Failed to scan sessions task: {err}"))?
''',
    "session command propagation",
)


# Hermes configuration roots must not be process-relative even when supplied by environment.
path = "src-tauri/src/hermes_config.rs"
text = read(path)
old = '''    if let Some(raw) = std::env::var_os("HERMES_HOME") {
        let value = raw.to_string_lossy();
        let trimmed = value.trim();
        if !trimmed.is_empty() {
            return PathBuf::from(trimmed);
        }
    }
'''
new = '''    if let Some(raw) = std::env::var_os("HERMES_HOME") {
        let value = raw.to_string_lossy();
        let trimmed = value.trim();
        if !trimmed.is_empty() {
            let path = PathBuf::from(trimmed);
            if path.is_absolute() {
                return path;
            }
            log::warn!("Ignoring relative HERMES_HOME: {}", path.display());
        }
    }
'''
if text.count(old) != 1:
    raise SystemExit(f"Hermes HOME validation: count={text.count(old)}")
text = text.replace(old, new, 1)
old = '''    localappdata
        .map(|value| value.to_string_lossy().trim().to_string())
        .filter(|value| !value.is_empty())
        .map(PathBuf::from)
        .unwrap_or_else(|| home.join("AppData").join("Local"))
        .join("hermes")
'''
new = '''    localappdata
        .map(|value| PathBuf::from(value.to_string_lossy().trim().to_string()))
        .filter(|path| path.is_absolute())
        .unwrap_or_else(|| home.join("AppData").join("Local"))
        .join("hermes")
'''
if text.count(old) != 1:
    raise SystemExit(f"Hermes LOCALAPPDATA validation: count={text.count(old)}")
text = text.replace(old, new, 1)
write(path, text)


# Permanent guards: encode semantics, not current test outcomes.
guard = "scripts/check_rust_failure_boundaries.py"
text = read(guard)
marker = "]\n\nfailures = []"
if text.count(marker) != 1:
    raise SystemExit(f"guard FILE_CHECKS marker count={text.count(marker)}")
checks = '''    ("services/model_fetch.rs", re.compile(r'HTTP \\{status\\}: \\{body\\}'), "model-discovery errors must not expose raw upstream response bodies"),
    ("app_store.rs", re.compile(r"fn read_override_from_store\\([^)]*\\) -> Option<PathBuf>"), "Store read failure must not collapse into an absent app_config_dir override"),
    ("app_store.rs", re.compile(r"fn resolve_path\\(raw: &str\\) -> PathBuf"), "app_config_dir parsing must be fallible and reject relative persistence roots"),
    ("settings.rs", re.compile(r"fn settings_path\\(\\) -> Option<PathBuf>"), "settings path resolution must expose HOME failures instead of a fake Option contract"),
    ("services/skill.rs", re.compile(r"(?:get_app_config_dir|crate::config::get_home_dir)\\(\\)"), "Skill Result APIs must propagate fallible persistence roots instead of panicking"),
    ("commands/misc.rs", re.compile(r"let home = crate::config::get_home_dir\\(\\);"), "CLI discovery must degrade without HOME instead of panicking"),
    ("session_manager/mod.rs", re.compile(r"join\\(\\)\\.unwrap_or_default\\(\\)"), "session worker panics must be observable, not converted to empty results"),
    ("session_manager/providers/opencode.rs", re.compile(r"crate::config::get_home_dir\\(\\)"), "OpenCode session path resolution must be fallible"),
    ("hermes_config.rs", re.compile(r"return PathBuf::from\\(trimmed\\)"), "HERMES_HOME must not create a process-relative configuration root"),
'''
text = text.replace(marker, checks + marker, 1)
anchor = "# User-home resolution is a persistence boundary shared by DB/config/backup/CLI paths. A direct\n"
if text.count(anchor) != 1:
    raise SystemExit(f"guard HOME anchor count={text.count(anchor)}")
extra = '''# Persistence compatibility must not reintroduce CWD-relative roots inside config.rs itself.
config_text = (RUST_ROOT / "config.rs").read_text(encoding="utf-8")
if 'let legacy_dir = PathBuf::from(trimmed).join(".cc-switch")' in config_text:
    failures.append("src-tauri/src/config.rs: Windows legacy HOME must be validated before DB fallback")

'''
text = text.replace(anchor, extra + anchor, 1)
write(guard, text)

print("Applied structural design-invariant follow-up")
