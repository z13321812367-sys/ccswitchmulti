#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "src-tauri/src/proxy/forwarder.rs"

old = """            codex_responses_lite_fallbacks: Arc::new(RwLock::new(HashMap::new())),\n            non_streaming_timeout,\n            streaming_first_byte_timeout,\n            max_attempts: 1,\n"""
new = """            codex_responses_lite_fallbacks: Arc::new(RwLock::new(HashMap::new())),\n            timeout_policy: ForwarderTimeoutPolicy::from_seconds(\n                non_streaming_timeout.as_secs(),\n                streaming_first_byte_timeout.as_secs(),\n            ),\n            max_attempts: 1,\n"""

text = PATH.read_text(encoding="utf-8")
count = text.count(old)
if count != 1:
    raise SystemExit(f"expected exactly one stale test RequestForwarder timeout initializer, found {count}")

text = text.replace(old, new, 1)

# The old fields were removed from RequestForwarder. A direct test initializer must not resurrect
# them; cargo test is the compile-time regression barrier, while this assertion keeps this one-shot
# migration exact and auditable.
if "            non_streaming_timeout,\n            streaming_first_byte_timeout,\n" in text:
    raise SystemExit("stale RequestForwarder timeout fields remain after replacement")

PATH.write_text(text, encoding="utf-8")
print("updated forwarder test helper to use ForwarderTimeoutPolicy")
