#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected exactly one match, found {count}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


# Deep links: collapse the macOS RunEvent::Opened duplicate parser/event path into
# the same redacted boundary used by single-instance and plugin callbacks.
replace_once(
    "src-tauri/src/lib.rs",
    '''                // 处理通过自定义 URL 协议触发的打开事件（例如 ccswitch://...）\n                RunEvent::Opened { urls } => {\n                    if let Some(url) = urls.first() {\n                        let url_str = url.to_string();\n                        log::info!("RunEvent::Opened with URL: {url_str}");\n\n                        if url_str.starts_with("ccswitch://") {\n                            if crate::lightweight::is_lightweight_mode() {\n                                if let Err(e) = crate::lightweight::exit_lightweight_mode(app_handle)\n                                {\n                                    log::error!("退出轻量模式重建窗口失败: {e}");\n                                }\n                            }\n\n                            // 解析并广播深链接事件，复用与 single_instance 相同的逻辑\n                            match crate::deeplink::parse_deeplink_url(&url_str) {\n                                Ok(request) => {\n                                    log::info!(\n                                        "Successfully parsed deep link from RunEvent::Opened: resource={}, app={:?}",\n                                        request.resource,\n                                        request.app\n                                    );\n\n                                    if let Err(e) =\n                                        app_handle.emit("deeplink-import", &request)\n                                    {\n                                        log::error!(\n                                            "Failed to emit deep link event from RunEvent::Opened: {e}"\n                                        );\n                                    }\n                                }\n                                Err(e) => {\n                                    log::error!(\n                                        "Failed to parse deep link URL from RunEvent::Opened: {e}"\n                                    );\n\n                                    if let Err(emit_err) = app_handle.emit(\n                                        "deeplink-error",\n                                        serde_json::json!({\n                                            "url": url_str,\n                                            "error": e.to_string()\n                                        }),\n                                    ) {\n                                        log::error!(\n                                            "Failed to emit deep link error event from RunEvent::Opened: {emit_err}"\n                                        );\n                                    }\n                                }\n                            }\n\n                            // 确保主窗口可见\n                            if let Some(window) = app_handle.get_webview_window("main") {\n                                let _ = window.unminimize();\n                                let _ = window.show();\n                                let _ = window.set_focus();\n                            }\n                        }\n                    }\n                }\n''',
    '''                // 处理通过自定义 URL 协议触发的打开事件（例如 ccswitch://...）。\n                // 原始 URL 只能进入统一处理器；日志与错误事件都在该边界内脱敏。\n                RunEvent::Opened { urls } => {\n                    if let Some(url) = urls.first() {\n                        let url_str = url.as_str();\n                        log::debug!(\n                            "RunEvent::Opened URL: {}",\n                            redact_url_for_log(url_str)\n                        );\n\n                        if url_str.starts_with("ccswitch://")\n                            && crate::lightweight::is_lightweight_mode()\n                        {\n                            if let Err(e) = crate::lightweight::exit_lightweight_mode(app_handle) {\n                                log::error!("退出轻量模式重建窗口失败: {e}");\n                            }\n                        }\n\n                        handle_deeplink_url(app_handle, url_str, true, "RunEvent::Opened");\n                    }\n                }\n''',
)

for path, label, settings_type in [
    ("src-tauri/src/services/webdav_auto_sync.rs", "WebDAV", "WebDavSyncSettings"),
    ("src-tauri/src/services/s3_auto_sync.rs", "S3", "S3SyncSettings"),
]:
    # Imports and duplicate queue/timing policy move into auto_sync_common.
    replace_once(
        path,
        '''use std::sync::atomic::{AtomicUsize, Ordering};\nuse std::sync::Arc;\nuse std::sync::OnceLock;\nuse std::time::{Duration, Instant};\n\nuse serde_json::json;\nuse tauri::{AppHandle, Emitter};\nuse tokio::sync::mpsc::error::TrySendError;\nuse tokio::sync::mpsc::{channel, Receiver, Sender};\n\nuse crate::error::AppError;\n''',
        '''use std::panic::AssertUnwindSafe;\nuse std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};\nuse std::sync::Arc;\nuse std::sync::OnceLock;\nuse std::time::Instant;\n\nuse futures::FutureExt;\nuse serde_json::json;\nuse tauri::{AppHandle, Emitter};\nuse tokio::sync::mpsc::{channel, Receiver, Sender};\n\nuse crate::error::AppError;\nuse crate::services::auto_sync_common::{\n    auto_sync_wait_duration, enqueue_change_signal, panic_message, should_trigger_for_table,\n    ChangeSignalOutcome,\n};\n''',
    )

    replace_once(
        path,
        '''\nconst AUTO_SYNC_DEBOUNCE_MS: u64 = 1000;\npub(crate) const MAX_AUTO_SYNC_WAIT_MS: u64 = 10_000;\n\nstatic DB_CHANGE_TX: OnceLock<Sender<String>> = OnceLock::new();\nstatic AUTO_SYNC_SUPPRESS_DEPTH: AtomicUsize = AtomicUsize::new(0);\n''',
        '''\nstatic DB_CHANGE_TX: OnceLock<Sender<String>> = OnceLock::new();\nstatic AUTO_SYNC_SUPPRESS_DEPTH: AtomicUsize = AtomicUsize::new(0);\nstatic WORKER_CHANNEL_CLOSED_REPORTED: AtomicBool = AtomicBool::new(false);\n''',
    )

    replace_once(
        path,
        '''pub fn should_trigger_for_table(table: &str) -> bool {\n    let normalized = table.trim().to_ascii_lowercase();\n    matches!(\n        normalized.as_str(),\n        "providers"\n            | "provider_endpoints"\n            | "mcp_servers"\n            | "prompts"\n            | "skills"\n            | "skill_repos"\n            | "settings"\n            | "proxy_config"\n    )\n}\n\npub(crate) fn enqueue_change_signal(tx: &Sender<String>, table: &str) -> bool {\n    match tx.try_send(table.to_string()) {\n        Ok(()) => true,\n        Err(TrySendError::Full(_)) | Err(TrySendError::Closed(_)) => false,\n    }\n}\n\npub(crate) fn auto_sync_wait_duration(started_at: Instant, now: Instant) -> Option<Duration> {\n    let max_wait = Duration::from_millis(MAX_AUTO_SYNC_WAIT_MS);\n    let debounce = Duration::from_millis(AUTO_SYNC_DEBOUNCE_MS);\n    let elapsed = now.saturating_duration_since(started_at);\n    if elapsed >= max_wait {\n        return None;\n    }\n    Some(debounce.min(max_wait - elapsed))\n}\n\n''',
        "",
    )

    replace_once(
        path,
        '''    let Some(tx) = DB_CHANGE_TX.get() else {\n        return;\n    };\n    let _ = enqueue_change_signal(tx, table);\n}\n''',
        f'''    let Some(tx) = DB_CHANGE_TX.get() else {{\n        return;\n    }};\n    match enqueue_change_signal(tx, table) {{\n        ChangeSignalOutcome::Enqueued | ChangeSignalOutcome::Coalesced => {{}}\n        ChangeSignalOutcome::WorkerUnavailable => {{\n            if !WORKER_CHANNEL_CLOSED_REPORTED.swap(true, Ordering::SeqCst) {{\n                log::error!(\n                    "[{label}][AutoSync] Change-signal channel is closed; the auto-sync worker is unavailable. Further database changes cannot be auto-synced until the worker is reinitialized."\n                );\n            }}\n        }}\n    }}\n}}\n''',
    )

    replace_once(
        path,
        '''    if DB_CHANGE_TX.set(tx).is_err() {\n        return;\n    }\n\n    tauri::async_runtime::spawn(async move {\n''',
        '''    if DB_CHANGE_TX.set(tx).is_err() {\n        return;\n    }\n    WORKER_CHANNEL_CLOSED_REPORTED.store(false, Ordering::SeqCst);\n\n    tauri::async_runtime::spawn(async move {\n''',
    )

    replace_once(
        path,
        f'''        if let Err(err) = run_auto_sync_upload(&db, &app).await {{\n            log::warn!("[{label}][AutoSync] Upload failed: {{err}}");\n        }}\n''',
        f'''        match AssertUnwindSafe(run_auto_sync_upload(&db, &app))\n            .catch_unwind()\n            .await\n        {{\n            Ok(Ok(())) => {{}}\n            Ok(Err(err)) => log::warn!("[{label}][AutoSync] Upload failed: {{err}}"),\n            Err(payload) => log::error!(\n                "[{label}][AutoSync] Upload panicked; worker will continue processing later changes: {{}}",\n                panic_message(payload.as_ref())\n            ),\n        }}\n''',
    )

    # Remove duplicate tests now owned by auto_sync_common and simplify imports.
    replace_once(
        path,
        '''    use super::{\n        auto_sync_wait_duration, enqueue_change_signal, is_auto_sync_suppressed,\n        should_run_auto_sync, should_trigger_for_table, AutoSyncSuppressionGuard,\n        MAX_AUTO_SYNC_WAIT_MS,\n    };\n''',
        '''    use super::{is_auto_sync_suppressed, should_run_auto_sync, AutoSyncSuppressionGuard};\n''',
    )
    replace_once(path, '''    use std::time::{Duration, Instant};\n    use tokio::sync::mpsc::channel;\n\n''', "")
    replace_once(
        path,
        '''    #[test]\n    fn should_trigger_sync_for_config_tables_only() {\n        assert!(should_trigger_for_table("providers"));\n        assert!(should_trigger_for_table("settings"));\n        assert!(!should_trigger_for_table("proxy_request_logs"));\n        assert!(!should_trigger_for_table("provider_health"));\n    }\n\n''',
        "",
    )
    replace_once(
        path,
        '''    #[test]\n    fn max_wait_caps_flush_latency_for_continuous_events() {\n        let started = Instant::now();\n        let later = started + Duration::from_millis(MAX_AUTO_SYNC_WAIT_MS + 1);\n        assert!(auto_sync_wait_duration(started, later).is_none());\n    }\n\n    #[tokio::test]\n    async fn enqueue_change_signal_drops_when_channel_is_full() {\n        let (tx, _rx) = channel::<String>(1);\n        assert!(enqueue_change_signal(&tx, "providers"));\n        assert!(!enqueue_change_signal(&tx, "providers"));\n    }\n\n''',
        "",
    )

print("Applied deep-link and auto-sync unification patches")
