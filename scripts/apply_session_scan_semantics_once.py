#!/usr/bin/env python3
from pathlib import Path


def read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    Path(path).write_text(text, encoding="utf-8")


def replace_exact(path: str, old: str, new: str, label: str, expected: int = 1) -> None:
    text = read(path)
    count = text.count(old)
    if count != expected:
        raise SystemExit(f"{label}: expected {expected}, found {count}")
    write(path, text.replace(old, new, expected))


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
# Session-domain contract:
# - missing session storage is a valid empty result;
# - storage that exists but cannot be enumerated is an error;
# - provider worker panic is an error;
# - provider installation/availability is NOT inferred from session storage.
# Individual dirty history files are handled by the parse-policy layer separately.
# ---------------------------------------------------------------------------
path = "src-tauri/src/session_manager/mod.rs"
replace_region(
    path,
    "pub fn scan_sessions() -> Result<Vec<SessionMeta>, String> {",
    "\npub fn load_messages",
    '''#[derive(Debug, thiserror::Error)]
pub enum SessionScanError {
    #[error("{provider} session storage error at {path}: {detail}")]
    Storage {
        provider: &'static str,
        path: PathBuf,
        detail: String,
    },
    #[error("{provider} session scan failed: {detail}")]
    Provider {
        provider: &'static str,
        detail: String,
    },
    #[error("{provider} session worker panicked")]
    WorkerPanic { provider: &'static str },
}

impl SessionScanError {
    pub(crate) fn storage(
        provider: &'static str,
        path: impl Into<PathBuf>,
        err: impl std::fmt::Display,
    ) -> Self {
        Self::Storage {
            provider,
            path: path.into(),
            detail: err.to_string(),
        }
    }

    fn provider(provider: &'static str, detail: impl Into<String>) -> Self {
        Self::Provider {
            provider,
            detail: detail.into(),
        }
    }
}

pub fn scan_sessions() -> Result<Vec<SessionMeta>, SessionScanError> {
    let (r1, r2, r3, r4, r5, r6) =
        std::thread::scope(|scope| -> Result<_, SessionScanError> {
            let h1 = scope.spawn(codex::scan_sessions);
            let h2 = scope.spawn(claude::scan_sessions);
            let h3 = scope.spawn(opencode::scan_sessions);
            let h4 = scope.spawn(openclaw::scan_sessions);
            let h5 = scope.spawn(gemini::scan_sessions);
            let h6 = scope.spawn(hermes::scan_sessions);

            let r1 = h1
                .join()
                .map_err(|_| SessionScanError::WorkerPanic { provider: "Codex" })??;
            let r2 = h2
                .join()
                .map_err(|_| SessionScanError::WorkerPanic { provider: "Claude" })??;
            let r3 = h3
                .join()
                .map_err(|_| SessionScanError::WorkerPanic { provider: "OpenCode" })?
                .map_err(|err| SessionScanError::provider("OpenCode", err))?;
            let r4 = h4
                .join()
                .map_err(|_| SessionScanError::WorkerPanic { provider: "OpenClaw" })??;
            let r5 = h5
                .join()
                .map_err(|_| SessionScanError::WorkerPanic { provider: "Gemini" })??;
            let r6 = h6
                .join()
                .map_err(|_| SessionScanError::WorkerPanic { provider: "Hermes" })?
                .map_err(|err| SessionScanError::provider("Hermes", err))?;
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
        b.last_active_at
            .or(b.created_at)
            .unwrap_or(0)
            .cmp(&a.last_active_at.or(a.created_at).unwrap_or(0))
    });
    Ok(sessions)
}
''',
    "typed session aggregate boundary",
)

path = "src-tauri/src/commands/session_manager.rs"
replace_exact(
    path,
    '''    tauri::async_runtime::spawn_blocking(session_manager::scan_sessions)
        .await
        .map_err(|err| format!("Failed to scan sessions task: {err}"))?
''',
    '''    tauri::async_runtime::spawn_blocking(session_manager::scan_sessions)
        .await
        .map_err(|err| format!("Failed to scan sessions task: {err}"))?
        .map_err(|err| err.to_string())
''',
    "session command typed error boundary",
)


# ---------------------------------------------------------------------------
# Codex: both active and archived roots are optional, but an existing root that
# cannot be enumerated is not equivalent to "no sessions".
# ---------------------------------------------------------------------------
path = "src-tauri/src/session_manager/providers/codex.rs"
replace_exact(
    path,
    "use crate::session_manager::{SessionMessage, SessionMeta};\n",
    "use crate::session_manager::{SessionMessage, SessionMeta, SessionScanError};\n",
    "Codex session error import",
)
replace_region(
    path,
    "pub fn scan_sessions() -> Vec<SessionMeta> {",
    "\npub fn load_messages",
    '''pub fn scan_sessions() -> Result<Vec<SessionMeta>, SessionScanError> {
    let roots = session_roots();
    scan_sessions_in_roots(&roots)
}

pub fn session_roots() -> Vec<PathBuf> {
    let config_dir = get_codex_config_dir();
    vec![
        config_dir.join("sessions"),
        config_dir.join("archived_sessions"),
    ]
}

fn scan_sessions_in_roots(roots: &[PathBuf]) -> Result<Vec<SessionMeta>, SessionScanError> {
    let mut files = Vec::new();
    for root in roots {
        collect_jsonl_files(root, &mut files)?;
    }

    let mut sessions = Vec::new();
    for path in files {
        if let Some(meta) = parse_session(&path) {
            sessions.push(meta);
        }
    }
    Ok(sessions)
}
''',
    "Codex structural scan result",
)
replace_region(
    path,
    "fn collect_jsonl_files(root: &Path, files: &mut Vec<PathBuf>) {",
    "\n}\n\n#[cfg(test)]",
    '''fn collect_jsonl_files(root: &Path, files: &mut Vec<PathBuf>) -> Result<(), SessionScanError> {
    if !root.exists() {
        return Ok(());
    }

    let entries = std::fs::read_dir(root)
        .map_err(|err| SessionScanError::storage("Codex", root, err))?;
    for entry in entries {
        let entry = entry.map_err(|err| SessionScanError::storage("Codex", root, err))?;
        let path = entry.path();
        if path.is_dir() {
            collect_jsonl_files(&path, files)?;
        } else if path.extension().and_then(|ext| ext.to_str()) == Some("jsonl") {
            files.push(path);
        }
    }
    Ok(())
''',
    "Codex structural traversal",
)
replace_exact(
    path,
    "        let sessions = scan_sessions_in_roots(&[active, archived]);\n",
    "        let sessions = scan_sessions_in_roots(&[active, archived]).expect(\"scan sessions\");\n",
    "Codex scan test result contract",
)


# ---------------------------------------------------------------------------
# Claude: projects root may be absent, but read_dir/DirEntry failures are
# structural failures rather than empty history.
# ---------------------------------------------------------------------------
path = "src-tauri/src/session_manager/providers/claude.rs"
replace_exact(
    path,
    "use crate::session_manager::{SessionMessage, SessionMeta};\n",
    "use crate::session_manager::{SessionMessage, SessionMeta, SessionScanError};\n",
    "Claude session error import",
)
replace_region(
    path,
    "pub fn scan_sessions() -> Vec<SessionMeta> {",
    "\npub fn load_messages",
    '''pub fn scan_sessions() -> Result<Vec<SessionMeta>, SessionScanError> {
    let root = get_claude_config_dir().join("projects");
    let mut files = Vec::new();
    collect_jsonl_files(&root, &mut files)?;

    let mut sessions = Vec::new();
    for path in files {
        if let Some(meta) = parse_session(&path) {
            sessions.push(meta);
        }
    }
    Ok(sessions)
}
''',
    "Claude structural scan result",
)
replace_region(
    path,
    "fn collect_jsonl_files(root: &Path, files: &mut Vec<PathBuf>) {",
    "\n}\n\nfn remove_path_if_exists",
    '''fn collect_jsonl_files(root: &Path, files: &mut Vec<PathBuf>) -> Result<(), SessionScanError> {
    if !root.exists() {
        return Ok(());
    }

    let entries = std::fs::read_dir(root)
        .map_err(|err| SessionScanError::storage("Claude", root, err))?;
    for entry in entries {
        let entry = entry.map_err(|err| SessionScanError::storage("Claude", root, err))?;
        let path = entry.path();
        if path.is_dir() {
            collect_jsonl_files(&path, files)?;
        } else if path.extension().and_then(|ext| ext.to_str()) == Some("jsonl") {
            files.push(path);
        }
    }
    Ok(())
}
''',
    "Claude structural traversal",
)


# ---------------------------------------------------------------------------
# Gemini: tmp root and per-project chats directories are structural storage.
# Optional .project_root metadata can degrade with a warning.
# ---------------------------------------------------------------------------
path = "src-tauri/src/session_manager/providers/gemini.rs"
replace_exact(
    path,
    "use crate::session_manager::{SessionMessage, SessionMeta};\n",
    "use crate::session_manager::{SessionMessage, SessionMeta, SessionScanError};\n",
    "Gemini session error import",
)
replace_region(
    path,
    "pub fn scan_sessions() -> Vec<SessionMeta> {",
    "\npub fn load_messages",
    '''pub fn scan_sessions() -> Result<Vec<SessionMeta>, SessionScanError> {
    let gemini_dir = crate::gemini_config::get_gemini_dir();
    let tmp_dir = gemini_dir.join("tmp");
    if !tmp_dir.exists() {
        return Ok(Vec::new());
    }

    let project_dirs = std::fs::read_dir(&tmp_dir)
        .map_err(|err| SessionScanError::storage("Gemini", &tmp_dir, err))?;
    let mut sessions = Vec::new();
    for entry in project_dirs {
        let entry = entry.map_err(|err| SessionScanError::storage("Gemini", &tmp_dir, err))?;
        let chats_dir = entry.path().join("chats");
        if !chats_dir.is_dir() {
            continue;
        }

        let chat_files = std::fs::read_dir(&chats_dir)
            .map_err(|err| SessionScanError::storage("Gemini", &chats_dir, err))?;
        let project_root_file = entry.path().join(".project_root");
        let project_dir = match std::fs::read_to_string(&project_root_file) {
            Ok(value) => Some(value),
            Err(err) if err.kind() == std::io::ErrorKind::NotFound => None,
            Err(err) => {
                log::warn!(
                    "Gemini optional project-root metadata unreadable at {}: {err}",
                    project_root_file.display()
                );
                None
            }
        };

        for file_entry in chat_files {
            let file_entry =
                file_entry.map_err(|err| SessionScanError::storage("Gemini", &chats_dir, err))?;
            let path = file_entry.path();
            if path.extension().and_then(|ext| ext.to_str()) != Some("json") {
                continue;
            }
            if let Some(meta) = parse_session(&path) {
                sessions.push(SessionMeta {
                    project_dir: project_dir.clone(),
                    ..meta
                });
            }
        }
    }
    Ok(sessions)
}
''',
    "Gemini structural scan result",
)


# ---------------------------------------------------------------------------
# OpenClaw: agents/sessions trees are structural; sessions.json display-name
# metadata is optional and degrades observably rather than hiding an I/O error.
# ---------------------------------------------------------------------------
path = "src-tauri/src/session_manager/providers/openclaw.rs"
replace_exact(
    path,
    "    session_manager::{SessionMessage, SessionMeta},\n",
    "    session_manager::{SessionMessage, SessionMeta, SessionScanError},\n",
    "OpenClaw session error import",
)
replace_region(
    path,
    "pub fn scan_sessions() -> Vec<SessionMeta> {",
    "\npub fn load_messages",
    '''pub fn scan_sessions() -> Result<Vec<SessionMeta>, SessionScanError> {
    let agents_dir = get_openclaw_dir().join("agents");
    if !agents_dir.exists() {
        return Ok(Vec::new());
    }

    let agent_entries = std::fs::read_dir(&agents_dir)
        .map_err(|err| SessionScanError::storage("OpenClaw", &agents_dir, err))?;
    let mut sessions = Vec::new();
    for agent_entry in agent_entries {
        let agent_entry =
            agent_entry.map_err(|err| SessionScanError::storage("OpenClaw", &agents_dir, err))?;
        let agent_path = agent_entry.path();
        if !agent_path.is_dir() {
            continue;
        }

        let sessions_dir = agent_path.join("sessions");
        if !sessions_dir.is_dir() {
            continue;
        }
        let session_entries = std::fs::read_dir(&sessions_dir)
            .map_err(|err| SessionScanError::storage("OpenClaw", &sessions_dir, err))?;
        let display_names = load_display_names(&sessions_dir);

        for entry in session_entries {
            let entry = entry
                .map_err(|err| SessionScanError::storage("OpenClaw", &sessions_dir, err))?;
            let path = entry.path();
            if path.extension().and_then(|ext| ext.to_str()) != Some("jsonl") {
                continue;
            }
            if let Some(meta) = parse_session(&path, Some(&display_names)) {
                sessions.push(meta);
            }
        }
    }
    Ok(sessions)
}
''',
    "OpenClaw structural scan result",
)
replace_region(
    path,
    "fn load_display_names(sessions_dir: &Path) -> HashMap<String, String> {",
    "\n}\n\nfn parse_session(",
    '''fn load_display_names(sessions_dir: &Path) -> HashMap<String, String> {
    let index_path = sessions_dir.join("sessions.json");
    let content = match std::fs::read_to_string(&index_path) {
        Ok(content) => content,
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => return HashMap::new(),
        Err(err) => {
            log::warn!(
                "OpenClaw optional session index unreadable at {}: {err}",
                index_path.display()
            );
            return HashMap::new();
        }
    };
    let index: serde_json::Map<String, Value> = match serde_json::from_str(&content) {
        Ok(index) => index,
        Err(err) => {
            log::warn!(
                "OpenClaw optional session index malformed at {}: {err}",
                index_path.display()
            );
            return HashMap::new();
        }
    };

    let mut map = HashMap::new();
    for entry in index.values() {
        if let (Some(id), Some(name)) = (
            entry.get("sessionId").and_then(Value::as_str),
            entry.get("displayName").and_then(Value::as_str),
        ) {
            if !name.is_empty() {
                map.insert(id.to_string(), name.to_string());
            }
        }
    }
    map
}
''',
    "OpenClaw optional index observability",
)


# ---------------------------------------------------------------------------
# OpenCode JSON session tree: follow-up already makes the public scan Result;
# make structural enumeration failures observable without changing permissive
# helpers used by message rendering/deletion yet.
# ---------------------------------------------------------------------------
path = "src-tauri/src/session_manager/providers/opencode.rs"
replace_region(
    path,
    "fn scan_sessions_json() -> Result<Vec<SessionMeta>, String> {",
    "\n/// Parse a SQLite source reference",
    '''fn scan_sessions_json() -> Result<Vec<SessionMeta>, String> {
    let storage = get_opencode_data_dir()?;
    let session_dir = storage.join("session");
    if !session_dir.exists() {
        return Ok(Vec::new());
    }
    let mut json_files = Vec::new();
    collect_json_files_strict(&session_dir, &mut json_files)?;
    let mut sessions = Vec::new();
    for path in json_files {
        if let Some(meta) = parse_session(&storage, &path) {
            sessions.push(meta);
        }
    }
    Ok(sessions)
}

fn collect_json_files_strict(root: &Path, files: &mut Vec<PathBuf>) -> Result<(), String> {
    let entries = std::fs::read_dir(root)
        .map_err(|err| format!("Failed to enumerate OpenCode session storage {}: {err}", root.display()))?;
    for entry in entries {
        let entry = entry
            .map_err(|err| format!("Failed to enumerate OpenCode session entry in {}: {err}", root.display()))?;
        let path = entry.path();
        if path.is_dir() {
            collect_json_files_strict(&path, files)?;
        } else if path.extension().and_then(|ext| ext.to_str()) == Some("json") {
            files.push(path);
        }
    }
    Ok(())
}
''',
    "OpenCode structural JSON scan",
)

print("Applied session structural failure semantics")
