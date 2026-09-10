use std::path::PathBuf;
use thiserror::Error;

/// Failure to determine a persistent/configuration root.
///
/// `None` is reserved for genuine absence at the API that owns optionality.
/// Invalid explicit values are errors and must not silently select another root.
#[derive(Debug, Clone, PartialEq, Eq, Error)]
pub enum RootResolutionError {
    #[error("{origin} is unavailable: {detail}")]
    Unavailable { origin: String, detail: String },
    #[error("{origin} must be an absolute path, got: {path}")]
    Relative { origin: String, path: String },
}

pub fn require_absolute_root(
    path: PathBuf,
    origin: impl Into<String>,
) -> Result<PathBuf, RootResolutionError> {
    if path.is_absolute() {
        Ok(path)
    } else {
        Err(RootResolutionError::Relative {
            origin: origin.into(),
            path: path.display().to_string(),
        })
    }
}

/// Read an environment variable that selects a persistent root.
/// Missing/blank means "not configured"; a non-empty relative value is invalid.
pub fn optional_absolute_env_root(name: &str) -> Result<Option<PathBuf>, RootResolutionError> {
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
