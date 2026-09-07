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
# Product-level failure semantics. Persistence-root resolution is strict;
# best-effort discovery is allowed to omit candidates but never invent roots.
# ---------------------------------------------------------------------------
semantics = Path("src-tauri/src/failure_semantics.rs")
if semantics.exists():
    raise SystemExit("failure_semantics.rs already exists; redesign driver is one-shot")
semantics.write_text(
    '''use std::path::PathBuf;
use thiserror::Error;

/// Failure to determine a persistent/configuration root.
///
/// `None` is reserved for genuine absence at the API that owns optionality.
/// Invalid explicit values are errors and must not silently select another root.
#[derive(Debug, Clone, PartialEq, Eq, Error)]
pub enum RootResolutionError {
    #[error("{source} is unavailable: {detail}")]
    Unavailable { source: String, detail: String },
    #[error("{source} must be an absolute path, got: {path}")]
    Relative { source: String, path: String },
}

pub fn require_absolute_root(
    path: PathBuf,
    source: impl Into<String>,
) -> Result<PathBuf, RootResolutionError> {
    if path.is_absolute() {
        Ok(path)
    } else {
        Err(RootResolutionError::Relative {
            source: source.into(),
            path: path.display().to_string(),
        })
    }
}

/// Read an environment variable that selects a persistent root.
/// Missing/blank means "not configured"; a non-empty relative value is invalid.
pub fn optional_absolute_env_root(
    name: &str,
) -> Result<Option<PathBuf>, RootResolutionError> {
    let Some(raw) = std::env::var_os(name) else {
        return Ok(None);
    };
    let value = raw.to_string_lossy();
    let trimmed = value.trim();
    if trimmed.is_empty() {
        return Ok(None);
    }
    require_absolute_root(PathBuf::from(trimmed), name).map(Some)
}
''',
    encoding="utf-8",
)

replace_exact(
    "src-tauri/src/lib.rs",
    "mod error;\n",
    "mod error;\nmod failure_semantics;\n",
    "register failure semantics module",
)
replace_exact(
    "src-tauri/src/error.rs",
    "use std::path::Path;\n",
    "use std::path::Path;\n\nuse crate::failure_semantics::RootResolutionError;\n",
    "error root import",
)
replace_exact(
    "src-tauri/src/error.rs",
    '''    #[error("配置错误: {0}")]
    Config(String),
''',
    '''    #[error("配置错误: {0}")]
    Config(String),
    #[error(transparent)]
    Root(#[from] RootResolutionError),
''',
    "typed root AppError",
)

# ---------------------------------------------------------------------------
# config.rs: add typed APIs while retaining compatibility wrappers for callers
# that have not yet migrated. New persistence code must use the typed boundary.
# ---------------------------------------------------------------------------
path = "src-tauri/src/config.rs"
replace_exact(
    path,
    "use crate::error::AppError;\n",
    "use crate::error::AppError;\nuse crate::failure_semantics::{require_absolute_root, RootResolutionError};\n",
    "config typed root import",
)
replace_region(
    path,
    "pub fn try_get_home_dir() -> Result<PathBuf, String> {",
    "\npub fn get_home_dir() -> PathBuf {",
    '''pub fn try_get_home_dir_typed() -> Result<PathBuf, RootResolutionError> {
    if let Ok(raw) = std::env::var("CC_SWITCH_TEST_HOME") {
        let trimmed = raw.trim();
        if !trimmed.is_empty() {
            return require_absolute_root(PathBuf::from(trimmed), "CC_SWITCH_TEST_HOME");
        }
    }

    let detected = dirs::home_dir().ok_or_else(|| RootResolutionError::Unavailable {
        source: "user home".to_string(),
        detail: "operating system did not provide a home directory; CWD fallback is forbidden"
            .to_string(),
    })?;
    require_absolute_root(detected, "operating-system user home")
}

/// Compatibility adapter. New persistence code should keep RootResolutionError typed.
pub fn try_get_home_dir() -> Result<PathBuf, String> {
    try_get_home_dir_typed().map_err(|err| err.to_string())
}
''',
    "typed home boundary",
)
replace_region(
    path,
    "pub fn resolve_persistence_path(raw: &str, label: &str) -> Result<PathBuf, String> {",
    "\n/// Last-resort crash/exit observability directory",
    '''pub fn resolve_persistence_path_typed(
    raw: &str,
    label: &str,
) -> Result<PathBuf, RootResolutionError> {
    let trimmed = raw.trim();
    if trimmed == "~" {
        return try_get_home_dir_typed();
    }
    if let Some(stripped) = trimmed.strip_prefix("~/") {
        return Ok(try_get_home_dir_typed()?.join(stripped));
    }
    if let Some(stripped) = trimmed.strip_prefix("~\\\\") {
        return Ok(try_get_home_dir_typed()?.join(stripped));
    }
    require_absolute_root(PathBuf::from(trimmed), label)
}

/// Compatibility adapter for legacy String-error APIs.
pub fn resolve_persistence_path(raw: &str, label: &str) -> Result<PathBuf, String> {
    resolve_persistence_path_typed(raw, label).map_err(|err| err.to_string())
}
''',
    "typed persistence boundary",
)
replace_region(
    path,
    "pub fn try_get_app_config_dir() -> Result<PathBuf, String> {",
    "\n/// Compatibility wrapper for legacy infallible path APIs.",
    '''pub fn try_get_app_config_dir_app() -> Result<PathBuf, AppError> {
    if let Some(custom) = crate::app_store::try_get_app_config_dir_override()? {
        return Ok(require_absolute_root(custom, "app_config_dir override")?);
    }

    let default_dir = try_get_home_dir_typed()?.join(".cc-switch");

    // v3.10.3 HOME is only a historical discovery candidate, not an active root selector.
    // Invalid legacy candidates are ignored; they must never override a valid OS home root.
    #[cfg(windows)]
    {
        let default_db = default_dir.join("cc-switch.db");
        if !default_db.exists() {
            if let Ok(home_env) = std::env::var("HOME") {
                let trimmed = home_env.trim();
                if !trimmed.is_empty() {
                    let legacy_home = PathBuf::from(trimmed);
                    if legacy_home.is_absolute() {
                        let legacy_dir = legacy_home.join(".cc-switch");
                        if legacy_dir.join("cc-switch.db").exists() {
                            log::info!(
                                "Detected v3.10.3 legacy database at {}, using it instead of {}",
                                legacy_dir.display(),
                                default_dir.display()
                            );
                            return Ok(legacy_dir);
                        }
                    } else {
                        log::warn!(
                            "Ignoring relative legacy HOME discovery candidate: {}",
                            legacy_home.display()
                        );
                    }
                }
            }
        }
    }

    Ok(default_dir)
}

pub fn try_get_app_config_dir() -> Result<PathBuf, String> {
    try_get_app_config_dir_app().map_err(|err| err.to_string())
}
''',
    "typed app root boundary",
)

# ---------------------------------------------------------------------------
# app_store.rs: cache failure separately from genuine absence. A failed Store
# refresh can no longer leave None behind and silently redirect persistence.
# ---------------------------------------------------------------------------
path = "src-tauri/src/app_store.rs"
replace_region(
    path,
    "/// 缓存当前的 app_config_dir 覆盖路径，避免存储 AppHandle\n",
    "\nfn open_paths_store(",
    '''/// Cached Store outcome. `Ok(None)` is genuine absence; `Err` means the last
/// refresh failed and must remain observable to persistence-root callers.
static APP_CONFIG_DIR_OVERRIDE: OnceLock<RwLock<Result<Option<PathBuf>, String>>> = OnceLock::new();

fn override_cache() -> &'static RwLock<Result<Option<PathBuf>, String>> {
    APP_CONFIG_DIR_OVERRIDE.get_or_init(|| RwLock::new(Ok(None)))
}

fn update_cached_override(value: Result<Option<PathBuf>, String>) {
    match override_cache().write() {
        Ok(mut guard) => *guard = value,
        Err(err) => log::error!("app_config_dir override cache poisoned: {err}"),
    }
}

pub fn try_get_app_config_dir_override() -> Result<Option<PathBuf>, AppError> {
    let guard = override_cache()
        .read()
        .map_err(|err| AppError::Lock(err.to_string()))?;
    guard
        .as_ref()
        .map(Clone::clone)
        .map_err(|err| AppError::Config(err.clone()))
}

/// Legacy infallible adapter. It fails closed instead of turning a cached Store
/// error into absence. New code must use `try_get_app_config_dir_override`.
pub fn get_app_config_dir_override() -> Option<PathBuf> {
    try_get_app_config_dir_override().unwrap_or_else(|err| {
        log::error!("{err}");
        panic!("{err}");
    })
}
''',
    "tri-state app root cache",
)
replace_exact(
    path,
    '''    let settings_path = crate::config::try_get_home_dir()
        .map_err(AppError::Config)?
''',
    '''    let settings_path = crate::config::try_get_home_dir_typed()
        .map_err(AppError::from)?
''',
    "legacy settings typed home",
)
replace_exact(
    path,
    '''fn resolve_path(raw: &str) -> Result<PathBuf, AppError> {
    crate::config::resolve_persistence_path(raw, "app_config_dir")
        .map_err(AppError::InvalidInput)
}
''',
    '''fn resolve_path(raw: &str) -> Result<PathBuf, AppError> {
    crate::config::resolve_persistence_path_typed(raw, "app_config_dir").map_err(AppError::from)
}
''',
    "typed app_store path",
)
replace_region(
    path,
    "pub fn refresh_app_config_dir_override(\n",
    "\n/// 写入 app_config_dir",
    '''pub fn refresh_app_config_dir_override(
    app: &tauri::AppHandle,
) -> Result<Option<PathBuf>, AppError> {
    let result = (|| {
        let migrated = migrate_legacy_override_if_needed(app)?;
        match migrated {
            Some(path) => Ok(Some(path)),
            None => read_override_from_store(app),
        }
    })();

    match result {
        Ok(value) => {
            update_cached_override(Ok(value.clone()));
            Ok(value)
        }
        Err(err) => {
            update_cached_override(Err(err.to_string()));
            Err(err)
        }
    }
}
''',
    "observable Store refresh failure",
)
replace_exact(
    path,
    "    update_cached_override(resolved.clone());\n",
    "    update_cached_override(Ok(resolved.clone()));\n",
    "cache successful Store write",
)
replace_exact(
    path,
    "    update_cached_override(value);\n",
    "    update_cached_override(Ok(value));\n",
    "cache successful migration",
)

# ---------------------------------------------------------------------------
# Hermes: current explicit persistent roots are strict. Missing/blank env means
# absent; relative HERMES_HOME/LOCALAPPDATA is a configuration error, not fallback.
# ---------------------------------------------------------------------------
path = "src-tauri/src/hermes_config.rs"
replace_exact(
    path,
    "use crate::error::AppError;\n",
    "use crate::error::AppError;\nuse crate::failure_semantics::{optional_absolute_env_root, require_absolute_root};\n",
    "Hermes root helpers import",
)
replace_region(
    path,
    "pub fn try_get_hermes_dir() -> Result<PathBuf, AppError> {",
    "\npub fn try_get_hermes_config_path() -> Result<PathBuf, AppError> {",
    '''pub fn try_get_hermes_dir() -> Result<PathBuf, AppError> {
    if let Some(override_dir) = get_hermes_override_dir() {
        return Ok(require_absolute_root(override_dir, "hermes_config_dir")?);
    }

    if let Some(path) = optional_absolute_env_root("HERMES_HOME")? {
        return Ok(path);
    }

    default_hermes_dir()
}

#[cfg(target_os = "windows")]
fn default_hermes_dir() -> Result<PathBuf, AppError> {
    if let Some(local_app_data) = optional_absolute_env_root("LOCALAPPDATA")? {
        return Ok(local_app_data.join("hermes"));
    }
    Ok(crate::config::try_get_home_dir_typed()?.join("AppData").join("Local").join("hermes"))
}

#[cfg(not(target_os = "windows"))]
fn default_hermes_dir() -> Result<PathBuf, AppError> {
    Ok(crate::config::try_get_home_dir_typed()?.join(".hermes"))
}

#[cfg(test)]
fn windows_local_hermes_dir(localappdata: Option<&std::ffi::OsStr>, home: &Path) -> PathBuf {
    localappdata
        .map(|value| value.to_string_lossy().trim().to_string())
        .filter(|value| !value.is_empty())
        .map(PathBuf::from)
        .unwrap_or_else(|| home.join("AppData").join("Local"))
        .join("hermes")
}

''',
    "strict Hermes persistent roots",
)

# ---------------------------------------------------------------------------
# OpenCode persistence root: XDG_DATA_HOME is an explicit persistent root.
# Relative values are errors. This is intentionally different from CLI discovery.
# ---------------------------------------------------------------------------
path = "src-tauri/src/session_manager/providers/opencode.rs"
replace_region(
    path,
    "fn try_get_opencode_base_dir() -> Result<PathBuf, String> {",
    "\npub(crate) fn get_opencode_data_dir() -> Result<PathBuf, String> {",
    '''fn try_get_opencode_base_dir() -> Result<PathBuf, String> {
    match crate::failure_semantics::optional_absolute_env_root("XDG_DATA_HOME") {
        Ok(Some(root)) => return Ok(root.join("opencode")),
        Ok(None) => {}
        Err(err) => return Err(err.to_string()),
    }
    Ok(crate::config::try_get_home_dir_typed()
        .map_err(|err| err.to_string())?
        .join(".local/share/opencode"))
}
''',
    "strict OpenCode persistence root",
)

# ---------------------------------------------------------------------------
# CLI discovery is intentionally best-effort. Make optional HOME explicit in
# the helper contract so callers cannot manufacture Path("") sentinels.
# ---------------------------------------------------------------------------
path = "src-tauri/src/commands/misc.rs"
replace_exact(
    path,
    "fn opencode_extra_search_paths(\n    home: &Path,\n",
    "fn opencode_extra_search_paths(\n    home: Option<&Path>,\n",
    "optional OpenCode discovery home",
)
replace_exact(
    path,
    '''    if !home.as_os_str().is_empty() {
        push_unique_path(&mut paths, home.join("bin"));
        push_unique_path(&mut paths, home.join(".opencode").join("bin"));
        push_unique_path(&mut paths, home.join(".bun").join("bin"));
        push_unique_path(&mut paths, home.join("go").join("bin"));
    }
''',
    '''    if let Some(home) = home {
        push_unique_path(&mut paths, home.join("bin"));
        push_unique_path(&mut paths, home.join(".opencode").join("bin"));
        push_unique_path(&mut paths, home.join(".bun").join("bin"));
        push_unique_path(&mut paths, home.join("go").join("bin"));
    }
''',
    "OpenCode discovery HOME body",
)
replace_exact(
    path,
    '''    if tool == "opencode" {
        let empty_home = Path::new("");
        for path in opencode_extra_search_paths(
            home.as_deref().unwrap_or(empty_home),
            std::env::var_os("OPENCODE_INSTALL_DIR"),
            std::env::var_os("XDG_BIN_DIR"),
            std::env::var_os("GOPATH"),
        ) {
''',
    '''    if tool == "opencode" {
        for path in opencode_extra_search_paths(
            home.as_deref(),
            std::env::var_os("OPENCODE_INSTALL_DIR"),
            std::env::var_os("XDG_BIN_DIR"),
            std::env::var_os("GOPATH"),
        ) {
''',
    "remove fake HOME discovery sentinel",
)
# Existing unit tests pass concrete Path references; preserve their intent explicitly.
replace_exact(
    path,
    "opencode_extra_search_paths(&home, None, None, None)",
    "opencode_extra_search_paths(Some(&home), None, None, None)",
    "OpenCode discovery test caller",
)

print("Applied failure-semantics redesign before test alignment")
