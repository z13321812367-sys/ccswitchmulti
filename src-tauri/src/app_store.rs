use serde_json::Value;
use std::path::PathBuf;
use std::sync::{OnceLock, RwLock};
use tauri_plugin_store::StoreExt;

use crate::error::AppError;

/// Store 中的键名
const STORE_KEY_APP_CONFIG_DIR: &str = "app_config_dir_override";
/// 旧 settings.json -> Store 迁移完成标记。
///
/// 该标记必须与 override 分离保存：用户迁移后如果主动清除覆盖目录，旧版
/// settings.json 中残留的字段不能在下一次启动时再次把覆盖目录“复活”。
const STORE_KEY_APP_CONFIG_DIR_LEGACY_MIGRATED: &str = "app_config_dir_legacy_migrated_v1";
const LEGACY_APP_CONFIG_DIR_KEYS: &[&str] =
    &["appConfigDir", "app_config_dir", "app_config_dir_override"];

/// Cached Store outcome. `Ok(None)` is genuine absence; `Err` means the last
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

fn open_paths_store(
    app: &tauri::AppHandle,
) -> Result<std::sync::Arc<tauri_plugin_store::Store<tauri::Wry>>, AppError> {
    app.store_builder("app_paths.json")
        .build()
        .map_err(|e| AppError::Message(format!("创建 Store 失败: {e}")))
}

fn read_override_from_store(app: &tauri::AppHandle) -> Result<Option<PathBuf>, AppError> {
    let store = open_paths_store(app)?;

    match store.get(STORE_KEY_APP_CONFIG_DIR) {
        Some(Value::String(path_str)) => {
            let path_str = path_str.trim();
            if path_str.is_empty() {
                return Ok(None);
            }

            let path = resolve_path(path_str)?;
            if !path.is_dir() {
                return Err(AppError::Config(format!(
                    "Store 中配置的 app_config_dir 不是现有目录: {}",
                    path.display()
                )));
            }

            log::info!("使用 Store 中的 app_config_dir: {path:?}");
            Ok(Some(path))
        }
        Some(_) => Err(AppError::Config(format!(
            "Store 中的 {STORE_KEY_APP_CONFIG_DIR} 类型不正确，应为字符串"
        ))),
        None => Ok(None),
    }
}

fn legacy_migration_completed(app: &tauri::AppHandle) -> Result<bool, AppError> {
    let store = open_paths_store(app)?;
    match store.get(STORE_KEY_APP_CONFIG_DIR_LEGACY_MIGRATED) {
        Some(Value::Bool(value)) => Ok(value),
        Some(_) => Err(AppError::Config(format!(
            "Store 中的 {STORE_KEY_APP_CONFIG_DIR_LEGACY_MIGRATED} 类型不正确，应为布尔值"
        ))),
        None => Ok(false),
    }
}

/// 从旧版 `~/.cc-switch/settings.json` 读取 app_config_dir。
///
/// 这里故意读取原始 JSON，而不是反序列化为当前 AppSettings：当前结构已经删除了
/// 这个字段，直接按新结构读取会静默丢失迁移信息。兼容 snake_case / camelCase 以及
/// 早期实验版的 override 键名。
fn read_legacy_override_from_settings() -> Result<Option<PathBuf>, AppError> {
    let settings_path = crate::config::try_get_home_dir_typed()
        .map_err(AppError::from)?
        .join(".cc-switch")
        .join("settings.json");
    let content = match std::fs::read_to_string(&settings_path) {
        Ok(content) => content,
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(err) => return Err(AppError::io(&settings_path, err)),
    };

    let root: Value =
        serde_json::from_str(&content).map_err(|err| AppError::json(&settings_path, err))?;

    for key in LEGACY_APP_CONFIG_DIR_KEYS {
        let Some(raw) = root.get(*key).and_then(Value::as_str) else {
            continue;
        };
        let trimmed = raw.trim();
        if trimmed.is_empty() {
            continue;
        }
        let resolved = resolve_path(trimmed)?;
        if !resolved.is_dir() {
            return Err(AppError::Config(format!(
                "旧 settings.json 的 {key} 不是现有目录: {}",
                resolved.display()
            )));
        }
        return Ok(Some(resolved));
    }

    Ok(None)
}

fn persist_override_and_migration_marker(
    app: &tauri::AppHandle,
    path: Option<&str>,
) -> Result<(), AppError> {
    let store = open_paths_store(app)?;

    match path {
        Some(value) => {
            store.set(
                STORE_KEY_APP_CONFIG_DIR,
                Value::String(value.trim().to_string()),
            );
        }
        None => {
            store.delete(STORE_KEY_APP_CONFIG_DIR);
        }
    }
    store.set(STORE_KEY_APP_CONFIG_DIR_LEGACY_MIGRATED, Value::Bool(true));
    store
        .save()
        .map_err(|e| AppError::Message(format!("保存 Store 失败: {e}")))
}

fn migrate_legacy_override_if_needed(app: &tauri::AppHandle) -> Result<Option<PathBuf>, AppError> {
    if legacy_migration_completed(app)? {
        return Ok(None);
    }

    if let Some(existing_path) = read_override_from_store(app)? {
        // 已经存在新格式配置，只补迁移标记，绝不能用尚未初始化的缓存反写 Store。
        let path_string = existing_path.to_string_lossy().to_string();
        persist_override_and_migration_marker(app, Some(&path_string))?;
        return Ok(Some(existing_path));
    }

    match read_legacy_override_from_settings()? {
        Some(legacy_path) => {
            let path_string = legacy_path.to_string_lossy().to_string();
            persist_override_and_migration_marker(app, Some(&path_string))?;
            log::info!(
                "已将旧 settings.json 的 app_config_dir 自动迁移到 Store: {}",
                legacy_path.display()
            );
            Ok(Some(legacy_path))
        }
        None => {
            // A successful scan with no legacy value is still a completed one-time migration.
            // Persist the marker so a stale legacy field cannot unexpectedly resurrect later.
            persist_override_and_migration_marker(app, None)?;
            Ok(None)
        }
    }
}

/// 从 Store 刷新 app_config_dir 覆盖值并更新缓存。
///
/// 启动阶段会顺带执行一次旧 settings.json 兼容迁移；迁移成功后 Store 成为唯一事实源。
pub fn refresh_app_config_dir_override(
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

/// 写入 app_config_dir 到 Tauri Store
pub fn set_app_config_dir_to_store(
    app: &tauri::AppHandle,
    path: Option<&str>,
) -> Result<(), AppError> {
    let resolved = match path.map(str::trim).filter(|value| !value.is_empty()) {
        Some(value) => {
            let path = resolve_path(value)?;
            if !path.is_dir() {
                return Err(AppError::InvalidInput(format!(
                    "app_config_dir 必须指向现有目录: {}",
                    path.display()
                )));
            }
            Some(path)
        }
        None => None,
    };
    let serialized = resolved
        .as_ref()
        .map(|path| path.to_string_lossy().to_string());
    persist_override_and_migration_marker(app, serialized.as_deref())?;
    update_cached_override(Ok(resolved.clone()));

    match resolved {
        Some(value) => log::info!("已将 app_config_dir 写入 Store: {}", value.display()),
        None => log::info!("已从 Store 中删除 app_config_dir 配置"),
    }
    Ok(())
}

/// 解析路径，支持 ~ 开头的相对路径
fn resolve_path(raw: &str) -> Result<PathBuf, AppError> {
    crate::config::resolve_persistence_path_typed(raw, "app_config_dir").map_err(AppError::from)
}

/// 从旧的 settings.json 迁移 app_config_dir 到 Store。
///
/// 保留该入口供旧调用方使用；实际迁移由 refresh 路径统一执行，保证启动时数据库初始化
/// 之前就能得到正确目录。
pub fn migrate_app_config_dir_from_settings(app: &tauri::AppHandle) -> Result<(), AppError> {
    let migrated = migrate_legacy_override_if_needed(app)?;
    let value = match migrated {
        Some(path) => Some(path),
        None => read_override_from_store(app)?,
    };
    update_cached_override(Ok(value));
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn resolve_path_preserves_normal_paths() {
        let input = if cfg!(windows) {
            r"C:\Users\test\.cc-switch"
        } else {
            "/tmp/.cc-switch"
        };
        assert_eq!(resolve_path(input).unwrap(), PathBuf::from(input));
    }

    #[test]
    fn resolve_path_rejects_process_relative_app_root() {
        assert!(resolve_path("relative/.cc-switch").is_err());
    }

    #[test]
    fn legacy_keys_cover_camel_and_snake_case() {
        assert!(LEGACY_APP_CONFIG_DIR_KEYS.contains(&"appConfigDir"));
        assert!(LEGACY_APP_CONFIG_DIR_KEYS.contains(&"app_config_dir"));
    }
}
