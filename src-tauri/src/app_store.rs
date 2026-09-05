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

/// 缓存当前的 app_config_dir 覆盖路径，避免存储 AppHandle
static APP_CONFIG_DIR_OVERRIDE: OnceLock<RwLock<Option<PathBuf>>> = OnceLock::new();

fn override_cache() -> &'static RwLock<Option<PathBuf>> {
    APP_CONFIG_DIR_OVERRIDE.get_or_init(|| RwLock::new(None))
}

fn update_cached_override(value: Option<PathBuf>) {
    if let Ok(mut guard) = override_cache().write() {
        *guard = value;
    }
}

/// 获取缓存中的 app_config_dir 覆盖路径
pub fn get_app_config_dir_override() -> Option<PathBuf> {
    override_cache().read().ok()?.clone()
}

fn open_paths_store(
    app: &tauri::AppHandle,
) -> Result<std::sync::Arc<tauri_plugin_store::Store<tauri::Wry>>, AppError> {
    app.store_builder("app_paths.json")
        .build()
        .map_err(|e| AppError::Message(format!("创建 Store 失败: {e}")))
}

fn read_override_from_store(app: &tauri::AppHandle) -> Option<PathBuf> {
    let store = match open_paths_store(app) {
        Ok(store) => store,
        Err(e) => {
            log::warn!("无法创建 Store: {e}");
            return None;
        }
    };

    match store.get(STORE_KEY_APP_CONFIG_DIR) {
        Some(Value::String(path_str)) => {
            let path_str = path_str.trim();
            if path_str.is_empty() {
                return None;
            }

            let path = resolve_path(path_str);

            if !path.exists() {
                log::warn!(
                    "Store 中配置的 app_config_dir 不存在: {path:?}\n\
                     将使用默认路径。"
                );
                return None;
            }

            log::info!("使用 Store 中的 app_config_dir: {path:?}");
            Some(path)
        }
        Some(_) => {
            log::warn!("Store 中的 {STORE_KEY_APP_CONFIG_DIR} 类型不正确，应为字符串");
            None
        }
        None => None,
    }
}

fn legacy_migration_completed(app: &tauri::AppHandle) -> bool {
    open_paths_store(app)
        .ok()
        .and_then(|store| store.get(STORE_KEY_APP_CONFIG_DIR_LEGACY_MIGRATED))
        .and_then(|value| value.as_bool())
        .unwrap_or(false)
}

/// 从旧版 `~/.cc-switch/settings.json` 读取 app_config_dir。
///
/// 这里故意读取原始 JSON，而不是反序列化为当前 AppSettings：当前结构已经删除了
/// 这个字段，直接按新结构读取会静默丢失迁移信息。兼容 snake_case / camelCase 以及
/// 早期实验版的 override 键名。
fn read_legacy_override_from_settings() -> Option<PathBuf> {
    let settings_path = crate::config::get_home_dir()
        .join(".cc-switch")
        .join("settings.json");
    let content = match std::fs::read_to_string(&settings_path) {
        Ok(content) => content,
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => return None,
        Err(err) => {
            log::warn!(
                "读取旧 settings.json 以迁移 app_config_dir 失败: path={}, error={err}",
                settings_path.display()
            );
            return None;
        }
    };

    let root: Value = match serde_json::from_str(&content) {
        Ok(value) => value,
        Err(err) => {
            log::warn!(
                "旧 settings.json 无法解析，跳过 app_config_dir 自动迁移: path={}, error={err}",
                settings_path.display()
            );
            return None;
        }
    };

    for key in LEGACY_APP_CONFIG_DIR_KEYS {
        let Some(raw) = root.get(*key).and_then(Value::as_str) else {
            continue;
        };
        let trimmed = raw.trim();
        if trimmed.is_empty() {
            continue;
        }
        let resolved = resolve_path(trimmed);
        if !resolved.exists() {
            log::warn!(
                "旧 settings.json 的 {key} 指向不存在的目录，跳过自动迁移: {}",
                resolved.display()
            );
            return None;
        }
        return Some(resolved);
    }

    None
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
    if legacy_migration_completed(app) {
        return Ok(None);
    }

    if let Some(existing_path) = read_override_from_store(app) {
        // 已经存在新格式配置，只补迁移标记，绝不能用尚未初始化的缓存反写 Store。
        let path_string = existing_path.to_string_lossy().to_string();
        persist_override_and_migration_marker(app, Some(&path_string))?;
        return Ok(Some(existing_path));
    }

    let Some(legacy_path) = read_legacy_override_from_settings() else {
        return Ok(None);
    };
    let path_string = legacy_path.to_string_lossy().to_string();
    persist_override_and_migration_marker(app, Some(&path_string))?;
    log::info!(
        "已将旧 settings.json 的 app_config_dir 自动迁移到 Store: {}",
        legacy_path.display()
    );
    Ok(Some(legacy_path))
}

/// 从 Store 刷新 app_config_dir 覆盖值并更新缓存。
///
/// 启动阶段会顺带执行一次旧 settings.json 兼容迁移；迁移成功后 Store 成为唯一事实源。
pub fn refresh_app_config_dir_override(app: &tauri::AppHandle) -> Option<PathBuf> {
    let migrated = match migrate_legacy_override_if_needed(app) {
        Ok(value) => value,
        Err(err) => {
            log::warn!("app_config_dir 旧配置迁移失败，将继续读取 Store: {err}");
            None
        }
    };
    let value = migrated.or_else(|| read_override_from_store(app));
    update_cached_override(value.clone());
    value
}

/// 写入 app_config_dir 到 Tauri Store
pub fn set_app_config_dir_to_store(
    app: &tauri::AppHandle,
    path: Option<&str>,
) -> Result<(), AppError> {
    let normalized = path.map(str::trim).filter(|value| !value.is_empty());
    persist_override_and_migration_marker(app, normalized)?;

    match normalized {
        Some(value) => log::info!("已将 app_config_dir 写入 Store: {value}"),
        None => log::info!("已从 Store 中删除 app_config_dir 配置"),
    }

    refresh_app_config_dir_override(app);
    Ok(())
}

/// 解析路径，支持 ~ 开头的相对路径
fn resolve_path(raw: &str) -> PathBuf {
    crate::config::expand_home_path(raw).unwrap_or_else(|err| {
        log::error!("{err}");
        panic!("{err}");
    })
}

/// 从旧的 settings.json 迁移 app_config_dir 到 Store。
///
/// 保留该入口供旧调用方使用；实际迁移由 refresh 路径统一执行，保证启动时数据库初始化
/// 之前就能得到正确目录。
pub fn migrate_app_config_dir_from_settings(app: &tauri::AppHandle) -> Result<(), AppError> {
    let migrated = migrate_legacy_override_if_needed(app)?;
    let value = migrated.or_else(|| read_override_from_store(app));
    update_cached_override(value);
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
        assert_eq!(resolve_path(input), PathBuf::from(input));
    }

    #[test]
    fn legacy_keys_cover_camel_and_snake_case() {
        assert!(LEGACY_APP_CONFIG_DIR_KEYS.contains(&"appConfigDir"));
        assert!(LEGACY_APP_CONFIG_DIR_KEYS.contains(&"app_config_dir"));
    }
}
