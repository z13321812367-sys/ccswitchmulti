#!/usr/bin/env python3
from pathlib import Path


def read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    Path(path).write_text(text, encoding="utf-8")


def replace_once(path: str, old: str, new: str, label: str, expected: int = 1) -> None:
    text = read(path)
    count = text.count(old)
    if count != expected:
        raise SystemExit(f"{label}: expected {expected}, found {count}")
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


# ---------------------------------------------------------------------------
# Hermes configuration root: fallible API is the production boundary.
# Test-only compatibility wrappers may panic, production Result APIs may not.
# ---------------------------------------------------------------------------
path = "src-tauri/src/hermes_config.rs"
replace_once(
    path,
    "use crate::config::{atomic_write, get_app_config_dir};\n",
    "use crate::config::atomic_write;\n",
    "Hermes obsolete infallible app-root import",
)
replace_region(
    path,
    "/// 获取 Hermes 配置目录\n",
    "fn hermes_write_lock() -> &'static Mutex<()> {",
    '''/// Resolve the Hermes configuration root without hiding HOME failure behind a panic.
///
/// Resolution order matches Hermes, but every accepted root is absolute:
/// 1. validated CC Switch `hermes_config_dir` override;
/// 2. absolute `HERMES_HOME`;
/// 3. platform default rooted in an absolute user home / LOCALAPPDATA.
pub fn try_get_hermes_dir() -> Result<PathBuf, AppError> {
    if let Some(override_dir) = get_hermes_override_dir() {
        if override_dir.is_absolute() {
            return Ok(override_dir);
        }
        return Err(AppError::Config(format!(
            "hermes_config_dir must be absolute: {}",
            override_dir.display()
        )));
    }

    if let Some(raw) = std::env::var_os("HERMES_HOME") {
        let value = raw.to_string_lossy();
        let trimmed = value.trim();
        if !trimmed.is_empty() {
            let path = PathBuf::from(trimmed);
            if path.is_absolute() {
                return Ok(path);
            }
            log::warn!("Ignoring relative HERMES_HOME: {}", path.display());
        }
    }

    default_hermes_dir()
}

#[cfg(target_os = "windows")]
fn default_hermes_dir() -> Result<PathBuf, AppError> {
    let home = crate::config::try_get_home_dir().map_err(AppError::Config)?;
    Ok(windows_local_hermes_dir(
        std::env::var_os("LOCALAPPDATA").as_deref(),
        &home,
    ))
}

#[cfg(not(target_os = "windows"))]
fn default_hermes_dir() -> Result<PathBuf, AppError> {
    Ok(crate::config::try_get_home_dir()
        .map_err(AppError::Config)?
        .join(".hermes"))
}

#[cfg(any(target_os = "windows", test))]
fn windows_local_hermes_dir(localappdata: Option<&std::ffi::OsStr>, home: &Path) -> PathBuf {
    localappdata
        .map(|value| PathBuf::from(value.to_string_lossy().trim().to_string()))
        .filter(|path| path.is_absolute())
        .unwrap_or_else(|| home.join("AppData").join("Local"))
        .join("hermes")
}

pub fn try_get_hermes_config_path() -> Result<PathBuf, AppError> {
    Ok(try_get_hermes_dir()?.join("config.yaml"))
}

// Tests deliberately control CC_SWITCH_TEST_HOME and may use concise path helpers.
// Production code must use the fallible functions above.
#[cfg(test)]
pub fn get_hermes_dir() -> PathBuf {
    try_get_hermes_dir().expect("Hermes test root")
}

#[cfg(test)]
pub fn get_hermes_config_path() -> PathBuf {
    try_get_hermes_config_path().expect("Hermes test config path")
}

''',
    "Hermes fallible root API",
)
replace_once(
    path,
    "    let path = get_hermes_config_path();\n",
    "    let path = try_get_hermes_config_path()?;\n",
    "Hermes read config path",
)
replace_once(
    path,
    '    let backup_dir = get_app_config_dir().join("backups").join("hermes");\n',
    '''    let backup_dir = crate::config::try_get_app_config_dir()
        .map_err(AppError::Config)?
        .join("backups")
        .join("hermes");
''',
    "Hermes backup app root",
)
replace_once(
    path,
    "    let config_path = get_hermes_config_path();\n",
    "    let config_path = try_get_hermes_config_path()?;\n",
    "Hermes write config path",
)
replace_region(
    path,
    "fn memories_dir() -> PathBuf {",
    "\n/// Read a Hermes memory file as a markdown blob.",
    '''fn memories_dir() -> Result<PathBuf, AppError> {
    Ok(try_get_hermes_dir()?.join("memories"))
}
''',
    "Hermes memory root",
)
replace_once(
    path,
    "    let path = memories_dir().join(kind.filename());\n",
    "    let path = memories_dir()?.join(kind.filename());\n",
    "Hermes memory path propagation",
    expected=2,
)

# Permanent checks should make regression to production panic wrappers impossible.
guard = "scripts/check_rust_failure_boundaries.py"
text = read(guard)
marker = "]\n\nfailures = []"
if text.count(marker) != 1:
    raise SystemExit(f"Hermes guard marker count={text.count(marker)}")
checks = '''    ("hermes_config.rs", re.compile(r"pub fn read_hermes_config\\([^)]*\\) -> Result[\\s\\S]{0,240}get_hermes_config_path\\(\\)"), "Hermes config reads must propagate root resolution errors"),
    ("hermes_config.rs", re.compile(r"let config_path = get_hermes_config_path\\(\\);"), "Hermes config writes must propagate root resolution errors"),
    ("hermes_config.rs", re.compile(r"let backup_dir = get_app_config_dir\\(\\)"), "Hermes backup persistence must not hide app-root failures"),
    ("session_manager/providers/hermes.rs", re.compile(r"use crate::hermes_config::get_hermes_dir"), "Hermes session discovery must use the fallible root API"),
'''
text = text.replace(marker, checks + marker, 1)
write(guard, text)


# ---------------------------------------------------------------------------
# Skill is already a Result API: Hermes-specific root must propagate naturally.
# ---------------------------------------------------------------------------
replace_once(
    "src-tauri/src/services/skill.rs",
    'AppType::Hermes => crate::hermes_config::get_hermes_dir().join("skills"),',
    '''AppType::Hermes => crate::hermes_config::try_get_hermes_dir()
                .map_err(|err| anyhow!(err))?
                .join("skills"),''',
    "Skill Hermes root propagation",
)


# ---------------------------------------------------------------------------
# Hermes session discovery: no hidden HOME panic and no empty-list conversion
# for SQLite/open/query/read_dir failures. Missing DB/table/dir remain legitimate
# empty states; malformed individual JSONL files are warned and skipped.
# ---------------------------------------------------------------------------
path = "src-tauri/src/session_manager/providers/hermes.rs"
replace_once(
    path,
    "use crate::hermes_config::get_hermes_dir;\n",
    "use crate::hermes_config::try_get_hermes_dir;\n",
    "Hermes session fallible import",
)
replace_region(
    path,
    "fn get_hermes_db_path() -> PathBuf {",
    "\nfn sqlite_row_to_session_meta",
    '''fn get_hermes_db_path() -> Result<PathBuf, String> {
    Ok(try_get_hermes_dir()
        .map_err(|err| err.to_string())?
        .join("state.db"))
}

/// Scan sessions from both SQLite database and JSONL transcript files,
/// with SQLite taking precedence on ID conflicts.
pub fn scan_sessions() -> Result<Vec<SessionMeta>, String> {
    let root = try_get_hermes_dir().map_err(|err| err.to_string())?;
    let sqlite_sessions = scan_sessions_sqlite(&root.join("state.db"))?;
    let jsonl_sessions = scan_sessions_jsonl(&root.join("sessions"))?;

    if sqlite_sessions.is_empty() {
        return Ok(jsonl_sessions);
    }
    if jsonl_sessions.is_empty() {
        return Ok(sqlite_sessions);
    }

    let sqlite_ids: std::collections::HashSet<String> = sqlite_sessions
        .iter()
        .map(|session| session.session_id.clone())
        .collect();
    let mut merged = sqlite_sessions;
    for session in jsonl_sessions {
        if !sqlite_ids.contains(&session.session_id) {
            merged.push(session);
        }
    }
    Ok(merged)
}

// ── SQLite scanning ─────────────────────────────────────────────────

fn scan_sessions_sqlite(db_path: &Path) -> Result<Vec<SessionMeta>, String> {
    if !db_path.exists() {
        return Ok(Vec::new());
    }

    let conn = Connection::open_with_flags(
        db_path,
        rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY | rusqlite::OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )
    .map_err(|err| format!("Failed to open Hermes session database {}: {err}", db_path.display()))?;

    let has_sessions: bool = conn
        .query_row(
            "SELECT COUNT(*) > 0 FROM sqlite_master WHERE type='table' AND name='sessions'",
            [],
            |row| row.get(0),
        )
        .map_err(|err| format!("Failed to inspect Hermes session schema: {err}"))?;
    if !has_sessions {
        return Ok(Vec::new());
    }

    let columns = get_table_columns(&conn, "sessions")?;
    let mut stmt = conn
        .prepare("SELECT * FROM sessions ORDER BY rowid DESC LIMIT 500")
        .map_err(|err| format!("Failed to prepare Hermes session query: {err}"))?;
    let rows = stmt
        .query_map([], |row| Ok(row_to_json(row, &columns)))
        .map_err(|err| format!("Failed to query Hermes sessions: {err}"))?;

    let db_source = format!("sqlite:{}", db_path.display());
    let mut sessions = Vec::new();
    for row_result in rows {
        let row = row_result.map_err(|err| format!("Failed to decode Hermes session row: {err}"))?;
        match sqlite_row_to_session_meta(&row, &db_source) {
            Some(meta) => sessions.push(meta),
            None => log::warn!("Skipping malformed Hermes SQLite session row without a usable id"),
        }
    }
    Ok(sessions)
}

''',
    "Hermes session root and SQLite observability",
)
replace_region(
    path,
    "fn get_table_columns(conn: &Connection, table: &str) -> Vec<String> {",
    "\n/// Convert a SQLite row to a JSON Value",
    '''fn get_table_columns(conn: &Connection, table: &str) -> Result<Vec<String>, String> {
    let query = format!("PRAGMA table_info({table})");
    let mut stmt = conn
        .prepare(&query)
        .map_err(|err| format!("Failed to inspect Hermes table columns: {err}"))?;
    let rows = stmt
        .query_map([], |row| row.get::<_, String>(1))
        .map_err(|err| format!("Failed to query Hermes table columns: {err}"))?;
    let mut columns = Vec::new();
    for row in rows {
        columns.push(row.map_err(|err| format!("Failed to decode Hermes table column: {err}"))?);
    }
    Ok(columns)
}

''',
    "Hermes table-column observability",
)
replace_once(
    path,
    "    let expected_db_path = get_hermes_db_path()\n",
    "    let expected_db_path = get_hermes_db_path()?\n",
    "Hermes delete expected DB root",
)
replace_region(
    path,
    "fn scan_sessions_jsonl() -> Vec<SessionMeta> {",
    "\nfn parse_jsonl_session(path: &Path)",
    '''fn scan_sessions_jsonl(sessions_dir: &Path) -> Result<Vec<SessionMeta>, String> {
    if !sessions_dir.exists() {
        return Ok(Vec::new());
    }

    let entries = std::fs::read_dir(sessions_dir)
        .map_err(|err| format!("Failed to read Hermes sessions directory {}: {err}", sessions_dir.display()))?;
    let mut sessions = Vec::new();
    for entry in entries {
        let entry = entry.map_err(|err| format!("Failed to enumerate Hermes session entry: {err}"))?;
        let path = entry.path();
        let ext = path.extension().and_then(|ext| ext.to_str());
        if ext != Some("jsonl") && ext != Some("json") {
            continue;
        }
        match parse_jsonl_session(&path) {
            Some(meta) => sessions.push(meta),
            None => log::warn!("Skipping malformed or unreadable Hermes session file: {}", path.display()),
        }
    }
    Ok(sessions)
}

''',
    "Hermes JSONL discovery observability",
)

# Aggregator already returns Result after the structural follow-up; Hermes now joins like OpenCode.
replace_once(
    "src-tauri/src/session_manager/mod.rs",
    '''        let r6 = h6.join().map_err(|_| "Hermes session scan panicked".to_string())?;''',
    '''        let r6 = h6
            .join()
            .map_err(|_| "Hermes session scan panicked".to_string())??;''',
    "Hermes session Result propagation",
)
replace_once(
    "src-tauri/src/session_manager/mod.rs",
    '"hermes" => vec![crate::hermes_config::get_hermes_dir().join("sessions")],',
    '''"hermes" => vec![crate::hermes_config::try_get_hermes_dir()
            .map_err(|err| err.to_string())?
            .join("sessions")],''',
    "Hermes deletion root propagation",
)

print("Applied Hermes fallible failure boundary")
