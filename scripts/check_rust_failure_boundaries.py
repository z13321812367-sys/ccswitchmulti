#!/usr/bin/env python3
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
CHECKS = [
    (ROOT / "src-tauri/src/lib.rs", re.compile(r'Deep link URL \(raw\)|"url"\s*:\s*url_str'), "raw deep-link data must not cross the diagnostics/event boundary"),
    (ROOT / "src-tauri/src/settings.rs", re.compile(r"let _ = set_current_provider\("), "current-provider persistence errors must propagate"),
    (ROOT / "src-tauri/src/services/webdav_auto_sync.rs", re.compile(r"let _ = settings::update_webdav_sync_status\("), "WebDAV auto-sync status persistence errors must be observable"),
    (ROOT / "src-tauri/src/services/s3_auto_sync.rs", re.compile(r"let _ = settings::update_s3_sync_status\("), "S3 auto-sync status persistence errors must be observable"),
]

failures = []
for path, pattern, message in CHECKS:
    if pattern.search(path.read_text(encoding="utf-8")):
        failures.append(f"{path.relative_to(ROOT)}: {message}")

if failures:
    print("Rust failure-boundary policy violations:", file=sys.stderr)
    for failure in failures:
        print(f"- {failure}", file=sys.stderr)
    raise SystemExit(1)

print("Rust failure-boundary policy checks passed")
