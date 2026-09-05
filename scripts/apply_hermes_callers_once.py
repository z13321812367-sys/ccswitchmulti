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
    write(path, text.replace(old, new))


# ---------------------------------------------------------------------------
# Tauri config commands already return Result<String/...>; Hermes root failures
# must be visible to the caller rather than recovered through a panic wrapper.
# ---------------------------------------------------------------------------
path = "src-tauri/src/commands/config.rs"
replace_exact(
    path,
    '''        AppType::Hermes => {
            let config_path = crate::hermes_config::get_hermes_config_path();
            let exists = config_path.exists();
            let path = crate::hermes_config::get_hermes_dir()
                .to_string_lossy()
                .to_string();

            Ok(ConfigStatus { exists, path })
        }
''',
    '''        AppType::Hermes => {
            let dir = crate::hermes_config::try_get_hermes_dir().map_err(|e| e.to_string())?;
            let exists = dir.join("config.yaml").exists();
            let path = dir.to_string_lossy().to_string();

            Ok(ConfigStatus { exists, path })
        }
''',
    "Hermes config status root propagation",
)
replace_exact(
    path,
    "        AppType::Hermes => crate::hermes_config::get_hermes_dir(),\n",
    '''        AppType::Hermes => {
            crate::hermes_config::try_get_hermes_dir().map_err(|e| e.to_string())?
        }
''',
    "Hermes config command root propagation",
    expected=2,
)

# ---------------------------------------------------------------------------
# Prompt-file path derivation is already fallible, so propagate the Hermes root.
# ---------------------------------------------------------------------------
replace_exact(
    "src-tauri/src/prompt_files.rs",
    "        AppType::Hermes => crate::hermes_config::get_hermes_dir(),\n",
    "        AppType::Hermes => crate::hermes_config::try_get_hermes_dir()?,\n",
    "Hermes prompt-file root propagation",
)

# ---------------------------------------------------------------------------
# MCP synchronization writes user configuration. A missing/invalid root is a
# sync failure, not an 'Hermes is absent' signal, so preserve the Result boundary.
# ---------------------------------------------------------------------------
path = "src-tauri/src/mcp/hermes.rs"
replace_exact(
    path,
    '''fn should_sync_hermes_mcp() -> bool {
    hermes_config::get_hermes_dir().exists()
}
''',
    '''fn should_sync_hermes_mcp() -> Result<bool, AppError> {
    Ok(hermes_config::try_get_hermes_dir()?.exists())
}
''',
    "Hermes MCP root propagation",
)
replace_exact(
    path,
    "    if !should_sync_hermes_mcp() {\n",
    "    if !should_sync_hermes_mcp()? {\n",
    "Hermes MCP sync caller propagation",
    expected=2,
)

# ---------------------------------------------------------------------------
# Live provider read/remove APIs already return AppError. Keep root-resolution
# errors observable rather than converting them into missing-config behavior.
# ---------------------------------------------------------------------------
path = "src-tauri/src/services/provider/live.rs"
replace_exact(
    path,
    "            let config_path = crate::hermes_config::get_hermes_config_path();\n",
    "            let config_path = crate::hermes_config::try_get_hermes_config_path()?;\n",
    "Hermes live-read config path propagation",
)
replace_exact(
    path,
    "    if !hermes_config::get_hermes_dir().exists() {\n",
    "    if !hermes_config::try_get_hermes_dir()?.exists() {\n",
    "Hermes live-remove root propagation",
)

# ---------------------------------------------------------------------------
# Test contract: the platform-default helper is now fallible by design.
# ---------------------------------------------------------------------------
replace_exact(
    "src-tauri/src/hermes_config.rs",
    "            assert_eq!(dir, default_hermes_dir());\n",
    "            assert_eq!(dir, default_hermes_dir().expect(\"default Hermes dir\"));\n",
    "Hermes default-dir test fallible contract",
)

# ---------------------------------------------------------------------------
# Permanent global guard: production modules must never reintroduce the test-only
# Hermes panic wrappers. hermes_config.rs itself is excluded because it owns the
# #[cfg(test)] compatibility helpers.
# ---------------------------------------------------------------------------
guard = "scripts/check_rust_failure_boundaries.py"
text = read(guard)
marker = '''# URL sanitization is a common diagnostics boundary. Specialized copies drift and caused raw
# deep-link/model-fetch paths to be missed; keep implementations centralized.
'''
if text.count(marker) != 1:
    raise SystemExit(f"Hermes global guard anchor count={text.count(marker)}")
hermes_guard = '''# Hermes persistence/session roots are fallible production boundaries. The only infallible
# wrappers are #[cfg(test)] helpers owned by hermes_config.rs; no other module may call/import them.
for path in RUST_ROOT.rglob("*.rs"):
    if path.name == "hermes_config.rs":
        continue
    text = path.read_text(encoding="utf-8")
    if re.search(r"(?:crate::)?hermes_config::get_hermes_(?:dir|config_path)\\b", text):
        failures.append(
            f"{path.relative_to(ROOT)}: Hermes roots must use fallible try_get_hermes_* APIs"
        )

'''
write(guard, text.replace(marker, hermes_guard + marker, 1))

print("Applied Hermes production caller migration")
