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


# ---------------------------------------------------------------------------
# Shared file reader: a line-level I/O error is not EOF. Preserve it so the
# provider parser can classify the file as dirty/unreadable and warn+skip it.
# ---------------------------------------------------------------------------
path = "src-tauri/src/session_manager/providers/utils.rs"
replace_exact(
    path,
    "        let all: Vec<String> = reader.lines().map_while(Result::ok).collect();\n",
    "        let all: Vec<String> = reader.lines().collect::<io::Result<Vec<_>>>()?;\n",
    "small session file line I/O",
)
replace_exact(
    path,
    "    let head: Vec<String> = reader.lines().take(head_n).map_while(Result::ok).collect();\n",
    "    let head: Vec<String> = reader.lines().take(head_n).collect::<io::Result<Vec<_>>>()?;\n",
    "session head line I/O",
)
replace_exact(
    path,
    "    let all_tail: Vec<String> = tail_reader.lines().map_while(Result::ok).collect();\n",
    "    let all_tail: Vec<String> = tail_reader.lines().collect::<io::Result<Vec<_>>>()?;\n",
    "session tail line I/O",
)


# ---------------------------------------------------------------------------
# Codex: Ok(None) is reserved for explicitly filtered subagent sessions.
# I/O or structurally unusable history is Err and is warned+skipped by scanning.
# ---------------------------------------------------------------------------
path = "src-tauri/src/session_manager/providers/codex.rs"
replace_exact(
    path,
    '''    for path in files {
        if let Some(meta) = parse_session(&path) {
            sessions.push(meta);
        }
    }
''',
    '''    for path in files {
        match parse_session_checked(&path) {
            Ok(Some(meta)) => sessions.push(meta),
            Ok(None) => {}
            Err(err) => log::warn!("Skipping unreadable Codex session {}: {err}", path.display()),
        }
    }
''',
    "Codex dirty-session scan policy",
)
replace_exact(
    path,
    '''    let meta = parse_session(path)
        .ok_or_else(|| format!("Failed to parse Codex session metadata: {}", path.display()))?;
''',
    '''    let meta = parse_session_checked(path)?
        .ok_or_else(|| format!("Codex session is intentionally filtered: {}", path.display()))?;
''',
    "Codex delete parser boundary",
)
replace_exact(
    path,
    "fn parse_session(path: &Path) -> Option<SessionMeta> {\n",
    "fn parse_session_checked(path: &Path) -> Result<Option<SessionMeta>, String> {\n",
    "Codex checked parser signature",
)
replace_exact(
    path,
    "    let (head, tail) = read_head_tail_lines(path, 10, 30).ok()?;\n",
    '''    let (head, tail) = read_head_tail_lines(path, 10, 30)
        .map_err(|err| format!("Failed to read Codex session {}: {err}", path.display()))?;
''',
    "Codex parser I/O propagation",
)
replace_exact(
    path,
    '''                if is_subagent_source(payload.get("source")) {
                    return None;
                }
''',
    '''                if is_subagent_source(payload.get("source")) {
                    return Ok(None);
                }
''',
    "Codex intentional subagent filter",
)
replace_exact(
    path,
    "    let session_id = session_id?;\n",
    '''    let session_id = session_id.ok_or_else(|| {
        format!("Codex session has no usable session id: {}", path.display())
    })?;
''',
    "Codex missing-id corruption",
)
replace_exact(
    path,
    "    Some(SessionMeta {\n",
    "    Ok(Some(SessionMeta {\n",
    "Codex checked parser result",
)
replace_exact(
    path,
    '''        resume_command: Some(format!("codex resume {session_id}")),
    })
}

fn is_subagent_source''',
    '''        resume_command: Some(format!("codex resume {session_id}")),
    }))
}

#[cfg(test)]
fn parse_session(path: &Path) -> Option<SessionMeta> {
    parse_session_checked(path).expect("parse Codex test session")
}

fn is_subagent_source''',
    "Codex test compatibility wrapper",
)


# ---------------------------------------------------------------------------
# Claude: agent-* histories are explicit policy filters. Other unreadable or
# structurally unusable histories are dirty files and remain observable.
# ---------------------------------------------------------------------------
path = "src-tauri/src/session_manager/providers/claude.rs"
replace_exact(
    path,
    '''    for path in files {
        if let Some(meta) = parse_session(&path) {
            sessions.push(meta);
        }
    }
''',
    '''    for path in files {
        match parse_session_checked(&path) {
            Ok(Some(meta)) => sessions.push(meta),
            Ok(None) => {}
            Err(err) => log::warn!("Skipping unreadable Claude session {}: {err}", path.display()),
        }
    }
''',
    "Claude dirty-session scan policy",
)
replace_exact(
    path,
    '''    let meta = parse_session(path).ok_or_else(|| {
        format!(
            "Failed to parse Claude session metadata: {}",
            path.display()
        )
    })?;
''',
    '''    let meta = parse_session_checked(path)?
        .ok_or_else(|| format!("Claude agent session is intentionally filtered: {}", path.display()))?;
''',
    "Claude delete parser boundary",
)
replace_exact(
    path,
    "fn parse_session(path: &Path) -> Option<SessionMeta> {\n",
    "fn parse_session_checked(path: &Path) -> Result<Option<SessionMeta>, String> {\n",
    "Claude checked parser signature",
)
replace_exact(
    path,
    '''    if is_agent_session(path) {
        return None;
    }

    let (head, tail) = read_head_tail_lines(path, 10, 30).ok()?;
''',
    '''    if is_agent_session(path) {
        return Ok(None);
    }

    let (head, tail) = read_head_tail_lines(path, 10, 30)
        .map_err(|err| format!("Failed to read Claude session {}: {err}", path.display()))?;
''',
    "Claude filter and I/O semantics",
)
replace_exact(
    path,
    "    let session_id = session_id?;\n",
    '''    let session_id = session_id.ok_or_else(|| {
        format!("Claude session has no usable session id: {}", path.display())
    })?;
''',
    "Claude missing-id corruption",
)
replace_exact(
    path,
    "    Some(SessionMeta {\n",
    "    Ok(Some(SessionMeta {\n",
    "Claude checked parser result",
)
replace_exact(
    path,
    '''        resume_command: Some(format!("claude --resume {session_id}")),
    })
}

fn is_agent_session''',
    '''        resume_command: Some(format!("claude --resume {session_id}")),
    }))
}

#[cfg(test)]
fn parse_session(path: &Path) -> Option<SessionMeta> {
    parse_session_checked(path).expect("parse Claude test session")
}

fn is_agent_session''',
    "Claude test compatibility wrapper",
)


# ---------------------------------------------------------------------------
# Gemini: no intentional filter exists in metadata parsing. Any unreadable or
# structurally unusable session is dirty history; warn+skip during listing.
# ---------------------------------------------------------------------------
path = "src-tauri/src/session_manager/providers/gemini.rs"
replace_exact(
    path,
    '''            if let Some(meta) = parse_session(&path) {
                sessions.push(SessionMeta {
                    project_dir: project_dir.clone(),
                    ..meta
                });
            }
''',
    '''            match parse_session_checked(&path) {
                Ok(meta) => sessions.push(SessionMeta {
                    project_dir: project_dir.clone(),
                    ..meta
                }),
                Err(err) => log::warn!("Skipping unreadable Gemini session {}: {err}", path.display()),
            }
''',
    "Gemini dirty-session scan policy",
)
replace_exact(
    path,
    '''    let meta = parse_session(path).ok_or_else(|| {
        format!(
            "Failed to parse Gemini session metadata: {}",
            path.display()
        )
    })?;
''',
    "    let meta = parse_session_checked(path)?;\n",
    "Gemini delete parser boundary",
)
replace_exact(
    path,
    "fn parse_session(path: &Path) -> Option<SessionMeta> {\n",
    "fn parse_session_checked(path: &Path) -> Result<SessionMeta, String> {\n",
    "Gemini checked parser signature",
)
replace_exact(
    path,
    '''    let data = std::fs::read_to_string(path).ok()?;
    let value: Value = serde_json::from_str(&data).ok()?;

    let session_id = value.get("sessionId").and_then(Value::as_str)?.to_string();
''',
    '''    let data = std::fs::read_to_string(path)
        .map_err(|err| format!("Failed to read Gemini session {}: {err}", path.display()))?;
    let value: Value = serde_json::from_str(&data)
        .map_err(|err| format!("Failed to parse Gemini session {}: {err}", path.display()))?;

    let session_id = value
        .get("sessionId")
        .and_then(Value::as_str)
        .ok_or_else(|| format!("Gemini session has no sessionId: {}", path.display()))?
        .to_string();
''',
    "Gemini parser corruption semantics",
)
replace_exact(
    path,
    "    Some(SessionMeta {\n",
    "    Ok(SessionMeta {\n",
    "Gemini checked parser result",
)
replace_exact(
    path,
    '''        resume_command: Some(format!("gemini --resume {session_id}")),
    })
}

#[cfg(test)]''',
    '''        resume_command: Some(format!("gemini --resume {session_id}")),
    })
}

#[cfg(test)]
fn parse_session(path: &Path) -> Option<SessionMeta> {
    parse_session_checked(path).ok()
}

#[cfg(test)]''',
    "Gemini test compatibility wrapper",
)


# ---------------------------------------------------------------------------
# OpenClaw: session file I/O is a dirty-file error. JSONL records inside an
# otherwise readable history may be malformed legacy lines and remain skippable.
# ---------------------------------------------------------------------------
path = "src-tauri/src/session_manager/providers/openclaw.rs"
replace_exact(
    path,
    '''            if let Some(meta) = parse_session(&path, Some(&display_names)) {
                sessions.push(meta);
            }
''',
    '''            match parse_session_checked(&path, Some(&display_names)) {
                Ok(meta) => sessions.push(meta),
                Err(err) => log::warn!("Skipping unreadable OpenClaw session {}: {err}", path.display()),
            }
''',
    "OpenClaw dirty-session scan policy",
)
replace_exact(
    path,
    '''    let meta = parse_session(path, None).ok_or_else(|| {
        format!(
            "Failed to parse OpenClaw session metadata: {}",
            path.display()
        )
    })?;
''',
    "    let meta = parse_session_checked(path, None)?;\n",
    "OpenClaw delete parser boundary",
)
replace_exact(
    path,
    "fn parse_session(\n",
    "fn parse_session_checked(\n",
    "OpenClaw checked parser name",
)
replace_exact(
    path,
    ") -> Option<SessionMeta> {\n    let (head, tail) = read_head_tail_lines(path, 10, 30).ok()?;\n",
    ''') -> Result<SessionMeta, String> {
    let (head, tail) = read_head_tail_lines(path, 10, 30)
        .map_err(|err| format!("Failed to read OpenClaw session {}: {err}", path.display()))?;
''',
    "OpenClaw checked parser signature",
)
replace_exact(
    path,
    "    let session_id = session_id?;\n",
    '''    let session_id = session_id.ok_or_else(|| {
        format!("OpenClaw session has no usable session id: {}", path.display())
    })?;
''',
    "OpenClaw missing-id corruption",
)
replace_exact(
    path,
    "    Some(SessionMeta {\n",
    "    Ok(SessionMeta {\n",
    "OpenClaw checked parser result",
)
# Preserve existing tests that exercise the legacy Option shape without exposing it to production.
replace_exact(
    path,
    '''        resume_command: Some(format!("openclaw --session {session_id}")),
    })
}

#[cfg(test)]''',
    '''        resume_command: Some(format!("openclaw --session {session_id}")),
    })
}

#[cfg(test)]
fn parse_session(
    path: &Path,
    display_names: Option<&HashMap<String, String>>,
) -> Option<SessionMeta> {
    parse_session_checked(path, display_names).ok()
}

#[cfg(test)]''',
    "OpenClaw test compatibility wrapper",
)


# ---------------------------------------------------------------------------
# OpenCode JSON metadata has no intentional ignore state. Existing dirty JSON
# is warned+skipped; structural tree/SQLite failures remain provider errors.
# ---------------------------------------------------------------------------
path = "src-tauri/src/session_manager/providers/opencode.rs"
replace_exact(
    path,
    '''    for path in json_files {
        if let Some(meta) = parse_session(&storage, &path) {
            sessions.push(meta);
        }
    }
''',
    '''    for path in json_files {
        match parse_session_checked(&storage, &path) {
            Ok(meta) => sessions.push(meta),
            Err(err) => log::warn!("Skipping unreadable OpenCode session {}: {err}", path.display()),
        }
    }
''',
    "OpenCode dirty-session scan policy",
)
replace_exact(
    path,
    "fn parse_session(storage: &Path, path: &Path) -> Option<SessionMeta> {\n",
    "fn parse_session_checked(storage: &Path, path: &Path) -> Result<SessionMeta, String> {\n",
    "OpenCode checked parser signature",
)
replace_exact(
    path,
    '''    let data = std::fs::read_to_string(path).ok()?;
    let value: Value = serde_json::from_str(&data).ok()?;

    let session_id = value.get("id").and_then(Value::as_str)?.to_string();
''',
    '''    let data = std::fs::read_to_string(path)
        .map_err(|err| format!("Failed to read OpenCode session {}: {err}", path.display()))?;
    let value: Value = serde_json::from_str(&data)
        .map_err(|err| format!("Failed to parse OpenCode session {}: {err}", path.display()))?;

    let session_id = value
        .get("id")
        .and_then(Value::as_str)
        .ok_or_else(|| format!("OpenCode session has no id: {}", path.display()))?
        .to_string();
''',
    "OpenCode parser corruption semantics",
)
replace_exact(
    path,
    "    Some(SessionMeta {\n",
    "    Ok(SessionMeta {\n",
    "OpenCode checked parser result",
)
replace_exact(
    path,
    '''        resume_command: Some(format!("opencode session resume {session_id}")),
    })
}

/// Read the first user message''',
    '''        resume_command: Some(format!("opencode session resume {session_id}")),
    })
}

#[cfg(test)]
fn parse_session(storage: &Path, path: &Path) -> Option<SessionMeta> {
    parse_session_checked(storage, path).ok()
}

/// Read the first user message''',
    "OpenCode test compatibility wrapper",
)


# ---------------------------------------------------------------------------
# Message streaming: line-level I/O failure is not a malformed JSON record.
# Propagate I/O errors; malformed historical JSON records remain skippable.
# ---------------------------------------------------------------------------
for provider in ("codex", "claude", "openclaw"):
    path = f"src-tauri/src/session_manager/providers/{provider}.rs"
    text = read(path)
    old = '''        let line = match line {
            Ok(value) => value,
            Err(_) => continue,
        };
'''
    new = f'''        let line = line.map_err(|err| {{
            format!("Failed to read {provider} session line from {{}}: {{err}}", path.display())
        }})?;
'''
    if text.count(old) != 1:
        raise SystemExit(f"{provider} message line I/O count={text.count(old)}")
    write(path, text.replace(old, new, 1))

print("Applied session dirty-history parse semantics")
