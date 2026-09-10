#!/usr/bin/env python3
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
RUST_ROOT = ROOT / "src-tauri" / "src"

# These are source-level regression guards for failure modes that previously existed in multiple
# entry points. They intentionally scan the full Rust tree where the same boundary can reappear.
GLOBAL_FORBIDDEN = [
    (re.compile(r'Deep link URL \(raw\)|"url"\s*:\s*url_str'), "raw deep-link data must not cross diagnostics/events"),
    (re.compile(r'Parsing deep link URL:\s*\{url\}'), "deep-link commands must log only redacted URLs"),
    (re.compile(r'请求 URL:\s*\{url\}'), "upstream URLs must be redacted before logging"),
    (re.compile(r'Trying endpoint:\s*\{url\}'), "model-discovery URLs must be redacted before logging"),
    (re.compile(r'上游响应体内容'), "raw upstream response bodies must not be persisted to logs"),
    (re.compile(r'body:\s*\{body_str\}'), "raw upstream response bodies must not be persisted to logs"),
]

FILE_CHECKS = [
    ("settings.rs", re.compile(r"let _ = set_current_provider\("), "current-provider persistence errors must propagate"),
    ("services/webdav_auto_sync.rs", re.compile(r"let _ = settings::update_webdav_sync_status\("), "WebDAV auto-sync status persistence errors must be observable"),
    ("services/s3_auto_sync.rs", re.compile(r"let _ = settings::update_s3_sync_status\("), "S3 auto-sync status persistence errors must be observable"),
    ("services/proxy.rs", re.compile(r"let _ = (?:self\.db\.|crate::settings::|self\.write_|self\.stop\(\)|self\.restore_live_|crate::config::delete_file)"), "proxy state/write/rollback failures must not be silently discarded"),
    ("codex_config.rs", re.compile(r"let _ = (?:atomic_write|delete_file)\("), "Codex config rollback failures must be observable"),
    ("config.rs", re.compile(r'PathBuf::from\("\."\)'), "home/config resolution must never silently fall back to the process CWD"),
    ("config.rs", re.compile(r"return Ok\(PathBuf::from\(home\)\);"), "explicit home overrides must be validated as absolute before use"),
    ("services/model_fetch.rs", re.compile(r'Err\(e\)\s*=>\s*\{\s*return Err\(format!\("Request failed:', re.S), "model discovery transport failures must advance to later compatibility candidates"),
    ("services/model_fetch.rs", re.compile(r'\.json\(\)\s*\.await\s*\.map_err\(\|e\| format!\("Failed to parse response:', re.S), "invalid successful model payloads must not abort compatibility candidate discovery"),
    ("services/model_fetch.rs", re.compile(r'HTTP \{status\}: \{body\}'), "model-discovery errors must not expose raw upstream response bodies"),
    ("app_store.rs", re.compile(r"fn read_override_from_store\([^)]*\) -> Option<PathBuf>"), "Store read failure must not collapse into an absent app_config_dir override"),
    ("app_store.rs", re.compile(r"fn resolve_path\(raw: &str\) -> PathBuf"), "app_config_dir parsing must be fallible and reject relative persistence roots"),
    ("settings.rs", re.compile(r"fn settings_path\(\) -> Option<PathBuf>"), "settings path resolution must expose HOME failures instead of a fake Option contract"),
    ("services/skill.rs", re.compile(r"\bget_app_config_dir\(\)|crate::config::get_home_dir\(\)"), "Skill Result APIs must propagate fallible persistence roots instead of panicking"),
    ("commands/misc.rs", re.compile(r"let home = crate::config::get_home_dir\(\);"), "CLI discovery must degrade without HOME instead of panicking"),
    ("session_manager/mod.rs", re.compile(r"join\(\)\.unwrap_or_default\(\)"), "session worker panics must be observable, not converted to empty results"),
    ("session_manager/providers/opencode.rs", re.compile(r"crate::config::get_home_dir\(\)"), "OpenCode session path resolution must be fallible"),
    ("hermes_config.rs", re.compile(r"return PathBuf::from\(trimmed\)"), "HERMES_HOME must not create a process-relative configuration root"),
    ("hermes_config.rs", re.compile(r"pub fn read_hermes_config\(\) -> Result<serde_yaml::Value, AppError> \{\s*let path = get_hermes_config_path\(\);"), "Hermes config reads must propagate root resolution errors"),
    ("hermes_config.rs", re.compile(r"fn write_yaml_section_to_config_locked\([\s\S]{0,220}\) -> Result<HermesWriteOutcome, AppError> \{\s*let config_path = get_hermes_config_path\(\);"), "Hermes config writes must propagate root resolution errors"),
    ("hermes_config.rs", re.compile(r"let backup_dir = get_app_config_dir\(\)"), "Hermes backup persistence must not hide app-root failures"),
    ("session_manager/providers/hermes.rs", re.compile(r"use crate::hermes_config::get_hermes_dir"), "Hermes session discovery must use the fallible root API"),
]

failures = []
for path in RUST_ROOT.rglob("*.rs"):
    text = path.read_text(encoding="utf-8")
    rel = path.relative_to(ROOT)
    for pattern, message in GLOBAL_FORBIDDEN:
        if pattern.search(text):
            failures.append(f"{rel}: {message}")

for rel_path, pattern, message in FILE_CHECKS:
    path = RUST_ROOT / rel_path
    if pattern.search(path.read_text(encoding="utf-8")):
        failures.append(f"{path.relative_to(ROOT)}: {message}")

# Persistence compatibility must not reintroduce CWD-relative roots inside config.rs itself.
config_text = (RUST_ROOT / "config.rs").read_text(encoding="utf-8")
if 'let legacy_dir = PathBuf::from(trimmed).join(".cc-switch")' in config_text:
    failures.append("src-tauri/src/config.rs: Windows legacy HOME must be validated before DB fallback")

# User-home resolution is a persistence boundary shared by DB/config/backup/CLI paths. A direct
# dirs::home_dir() call elsewhere can silently re-introduce CWD/relative fallback semantics or
# diverge from the validated CC_SWITCH_TEST_HOME behavior, so keep one common implementation.
for path in RUST_ROOT.rglob("*.rs"):
    if path.name == "config.rs":
        continue
    text = path.read_text(encoding="utf-8")
    if "dirs::home_dir(" in text:
        failures.append(
            f"{path.relative_to(ROOT)}: direct home resolution must use the config common boundary"
        )

# Hermes persistence/session roots are fallible production boundaries. The only infallible
# wrappers are #[cfg(test)] helpers owned by hermes_config.rs; no other module may call/import them.
for path in RUST_ROOT.rglob("*.rs"):
    if path.name == "hermes_config.rs":
        continue
    text = path.read_text(encoding="utf-8")
    if re.search(r"(?:crate::)?hermes_config::get_hermes_(?:dir|config_path)\b", text):
        failures.append(
            f"{path.relative_to(ROOT)}: Hermes roots must use fallible try_get_hermes_* APIs"
        )

# URL sanitization is a common diagnostics boundary. Specialized copies drift and caused raw
# deep-link/model-fetch paths to be missed; keep implementations centralized.
for path in RUST_ROOT.rglob("*.rs"):
    if path.name == "diagnostics.rs":
        continue
    text = path.read_text(encoding="utf-8")
    if re.search(r"\bfn\s+redact_url(?:_for_log|_without_query_for_log)?\s*\(", text):
        failures.append(
            f"{path.relative_to(ROOT)}: URL redaction helpers must live in diagnostics.rs"
        )

if failures:
    print("Rust failure-boundary policy violations:", file=sys.stderr)
    for failure in sorted(set(failures)):
        print(f"- {failure}", file=sys.stderr)
    raise SystemExit(1)

print("Rust failure-boundary policy checks passed")
