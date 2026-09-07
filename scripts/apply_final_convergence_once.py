#!/usr/bin/env python3
from pathlib import Path
import runpy


def read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    Path(path).write_text(text, encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected 1 exact match, found {count}")
    return text.replace(old, new, 1)


def remove_region(text: str, start: str, end: str, label: str) -> str:
    if text.count(start) != 1:
        raise SystemExit(f"{label}: start count={text.count(start)}")
    i = text.index(start)
    try:
        j = text.index(end, i)
    except ValueError:
        raise SystemExit(f"{label}: end marker missing")
    return text[:i] + text[j:]


def assert_balanced_region(path: str, start: str, end: str, label: str) -> None:
    text = read(path)
    if start not in text:
        raise SystemExit(f"{label}: start marker missing after migration")
    i = text.index(start)
    if end not in text[i:]:
        raise SystemExit(f"{label}: end marker missing after migration")
    j = text.index(end, i)
    block = text[i:j]
    opens = block.count("{")
    closes = block.count("}")
    if opens != closes:
        print(f"--- generated {label} block ---")
        print(block)
        print(f"--- end generated {label} block; braces={opens}/{closes} ---")
        raise SystemExit(f"{label}: generated brace imbalance {opens} open / {closes} close")


def assert_traversal_boundaries(stage: str) -> None:
    assert_balanced_region(
        "src-tauri/src/session_manager/providers/codex.rs",
        "fn collect_jsonl_files(",
        "#[cfg(test)]",
        f"Codex collect_jsonl_files ({stage})",
    )
    assert_balanced_region(
        "src-tauri/src/session_manager/providers/claude.rs",
        "fn collect_jsonl_files(",
        "fn remove_path_if_exists",
        f"Claude collect_jsonl_files ({stage})",
    )
    assert_balanced_region(
        "src-tauri/src/session_manager/providers/openclaw.rs",
        "fn load_display_names(",
        "fn parse_session",
        f"OpenClaw load_display_names ({stage})",
    )


# The typed root APIs have replaced these production helpers. Keep the two
# deterministic pure helpers only for the tests that still exercise injected
# path inputs; remove the obsolete expansion and infallible Store adapter.
config_path = "src-tauri/src/config.rs"
text = read(config_path)
text = replace_once(
    text,
    "fn require_absolute_path(path: PathBuf, label: &str) -> Result<PathBuf, String> {",
    "#[cfg(test)]\nfn require_absolute_path(path: PathBuf, label: &str) -> Result<PathBuf, String> {",
    "gate legacy absolute-path helper to tests",
)
text = replace_once(
    text,
    "fn resolve_home_dir(\n",
    "#[cfg(test)]\nfn resolve_home_dir(\n",
    "gate injected HOME resolver to tests",
)
text = remove_region(
    text,
    "/// Expand `~`, `~/...`",
    "/// Resolve a user-configurable persistence/configuration root.\n",
    "remove obsolete expand_home_path compatibility helper",
)
write(config_path, text)

app_store_path = "src-tauri/src/app_store.rs"
text = read(app_store_path)
text = remove_region(
    text,
    "/// Legacy infallible adapter. It fails closed instead of turning a cached Store\n",
    "fn open_paths_store(\n",
    "remove obsolete infallible app-root cache adapter",
)
write(app_store_path, text)

# The structural migration's replacement blocks include their own final `}`.
# Its generic replace_region originally retained an end marker beginning with
# `\n}`, duplicating that close. Consume exactly that old function close while
# retaining everything after it (test/module annotations or the next helper).
scan_driver = Path("scripts/apply_session_scan_semantics_once.py")
scan_text = scan_driver.read_text(encoding="utf-8")
old_replace = "    write(path, text[:i] + new + text[j:])\n"
new_replace = '''    if end.startswith("\\n}") and new.rstrip().endswith("}"):
        j += 2
    write(path, text[:i] + new + text[j:])
'''
if scan_text.count(old_replace) != 1:
    raise SystemExit(f"session structural replace_region body count={scan_text.count(old_replace)}")
scan_driver.write_text(scan_text.replace(old_replace, new_replace, 1), encoding="utf-8")

# Session scanning is a separate domain from provider installation discovery.
runpy.run_path("scripts/apply_session_scan_semantics_once.py", run_name="__main__")
assert_traversal_boundaries("after structural migration")

# OpenClaw sessions are gateway-managed and deliberately have no CLI resume
# command. Also, parse_session is followed by prune_sessions_index(), not the
# test module. Correct the dirty-parser migration driver's exact anchors.
parse_driver = Path("scripts/apply_session_parse_semantics_once.py")
parse_text = parse_driver.read_text(encoding="utf-8")
old_openclaw_resume = 'resume_command: Some(format!("openclaw --session {session_id}")),'
new_openclaw_resume = 'resume_command: None, // OpenClaw sessions are gateway-managed, no CLI resume'
if parse_text.count(old_openclaw_resume) != 2:
    raise SystemExit(
        f"OpenClaw parse-driver resume anchor count={parse_text.count(old_openclaw_resume)}"
    )
parse_text = parse_text.replace(old_openclaw_resume, new_openclaw_resume)

old_anchor = (
    "'''        resume_command: None, // OpenClaw sessions are gateway-managed, no CLI resume\n"
    "    })\n}\n\n#[cfg(test)]''',"
)
new_anchor = (
    "'''        resume_command: None, // OpenClaw sessions are gateway-managed, no CLI resume\n"
    "    })\n}\n\nfn prune_sessions_index(''',"
)
if parse_text.count(old_anchor) != 1:
    raise SystemExit(f"OpenClaw parse-driver source anchor count={parse_text.count(old_anchor)}")
parse_text = parse_text.replace(old_anchor, new_anchor, 1)

old_replacement = (
    "'''        resume_command: None, // OpenClaw sessions are gateway-managed, no CLI resume\n"
    "    })\n}\n\n#[cfg(test)]\n"
    "fn parse_session(\n"
    "    path: &Path,\n"
    "    display_names: Option<&HashMap<String, String>>,\n"
    ") -> Option<SessionMeta> {\n"
    "    parse_session_checked(path, display_names).ok()\n"
    "}\n\n#[cfg(test)]''',"
)
new_replacement = (
    "'''        resume_command: None, // OpenClaw sessions are gateway-managed, no CLI resume\n"
    "    })\n}\n\n#[cfg(test)]\n"
    "fn parse_session(\n"
    "    path: &Path,\n"
    "    display_names: Option<&HashMap<String, String>>,\n"
    ") -> Option<SessionMeta> {\n"
    "    parse_session_checked(path, display_names).ok()\n"
    "}\n\nfn prune_sessions_index(''',"
)
if parse_text.count(old_replacement) != 1:
    raise SystemExit(
        f"OpenClaw parse-driver replacement anchor count={parse_text.count(old_replacement)}"
    )
parse_text = parse_text.replace(old_replacement, new_replacement, 1)
parse_driver.write_text(parse_text, encoding="utf-8")
runpy.run_path("scripts/apply_session_parse_semantics_once.py", run_name="__main__")
assert_traversal_boundaries("after dirty-history migration")

# Gemini and OpenCode no longer have any test consumers for the legacy Option
# parser shape. Remove those wrappers instead of suppressing dead-code warnings.
for path, wrapper, label in [
    (
        "src-tauri/src/session_manager/providers/gemini.rs",
        '''#[cfg(test)]
fn parse_session(path: &Path) -> Option<SessionMeta> {
    parse_session_checked(path).ok()
}

''',
        "remove obsolete Gemini parser compatibility wrapper",
    ),
    (
        "src-tauri/src/session_manager/providers/opencode.rs",
        '''#[cfg(test)]
fn parse_session(storage: &Path, path: &Path) -> Option<SessionMeta> {
    parse_session_checked(storage, path).ok()
}

''',
        "remove obsolete OpenCode parser compatibility wrapper",
    ),
]:
    text = read(path)
    text = replace_once(text, wrapper, "", label)
    write(path, text)

# These are one-shot migration mechanics. On a successful verified run they
# disappear from the resulting branch along with the existing drivers.
for temporary in [
    "scripts/apply_session_scan_semantics_once.py",
    "scripts/apply_session_parse_semantics_once.py",
    "scripts/apply_final_convergence_once.py",
]:
    Path(temporary).unlink()

print("Applied final root/session design convergence")
