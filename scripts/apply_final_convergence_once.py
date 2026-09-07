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

# Session scanning is a separate domain from provider installation discovery.
# First make structural failures observable; then distinguish dirty individual
# history files from intentional filters without letting one dirty file take
# down the whole provider.
runpy.run_path("scripts/apply_session_scan_semantics_once.py", run_name="__main__")
runpy.run_path("scripts/apply_session_parse_semantics_once.py", run_name="__main__")

# These are one-shot migration mechanics. On a successful verified run they
# should disappear from the resulting branch along with the existing drivers.
for temporary in [
    "scripts/apply_session_scan_semantics_once.py",
    "scripts/apply_session_parse_semantics_once.py",
    "scripts/apply_final_convergence_once.py",
]:
    Path(temporary).unlink()

print("Applied final root/session design convergence")
