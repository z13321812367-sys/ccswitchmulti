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
