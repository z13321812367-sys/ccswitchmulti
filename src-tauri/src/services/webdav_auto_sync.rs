use std::panic::AssertUnwindSafe;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::Arc;
use std::sync::OnceLock;
use std::time::Instant;

use futures::FutureExt;
use serde_json::json;
use tauri::{AppHandle, Emitter};
use tokio::sync::mpsc::{channel, Receiver, Sender};

use crate::error::AppError;
use crate::services::auto_sync_common::{
    auto_sync_wait_duration, enqueue_change_signal, panic_message, should_trigger_for_table,
    ChangeSignalOutcome,
};
use crate::services::webdav_sync as webdav_sync_service;
use crate::settings::{self, WebDavSyncSettings};

static DB_CHANGE_TX: OnceLock<Sender<String>> = OnceLock::new();
static AUTO_SYNC_SUPPRESS_DEPTH: AtomicUsize = AtomicUsize::new(0);
static WORKER_CHANNEL_CLOSED_REPORTED: AtomicBool = AtomicBool::new(false);

pub(crate) struct AutoSyncSuppressionGuard;

impl AutoSyncSuppressionGuard {
    pub fn new() -> Self {
        AUTO_SYNC_SUPPRESS_DEPTH.fetch_add(1, Ordering::SeqCst);
        Self
    }
}

impl Drop for AutoSyncSuppressionGuard {
    fn drop(&mut self) {
        let _ =
            AUTO_SYNC_SUPPRESS_DEPTH.fetch_update(Ordering::SeqCst, Ordering::SeqCst, |value| {
                Some(value.saturating_sub(1))
            });
    }
}

pub(crate) fn is_auto_sync_suppressed() -> bool {
    AUTO_SYNC_SUPPRESS_DEPTH.load(Ordering::SeqCst) > 0
}

fn should_run_auto_sync(settings: Option<&WebDavSyncSettings>) -> bool {
    let Some(sync) = settings else {
        return false;
    };
    sync.enabled && sync.auto_sync
}

fn persist_auto_sync_error(
    settings: &mut WebDavSyncSettings,
    error: &AppError,
) -> Result<(), AppError> {
    settings.status.last_error = Some(error.to_string());
    settings.status.last_error_source = Some("auto".to_string());
    settings::update_webdav_sync_status(settings.status.clone())
}

fn emit_auto_sync_status_updated(app: &AppHandle, status: &str, error: Option<&str>) {
    let payload = match error {
        Some(message) => json!({
            "source": "auto",
            "status": status,
            "error": message,
        }),
        None => json!({
            "source": "auto",
            "status": status,
        }),
    };

    if let Err(err) = app.emit("webdav-sync-status-updated", payload) {
        log::debug!("[WebDAV] failed to emit sync status update event: {err}");
    }
}

async fn run_auto_sync_upload(
    db: &crate::database::Database,
    app: &AppHandle,
) -> Result<(), AppError> {
    let mut settings = settings::get_webdav_sync_settings();
    if !should_run_auto_sync(settings.as_ref()) {
        return Ok(());
    }

    let mut sync_settings = match settings.take() {
        Some(value) => value,
        None => return Ok(()),
    };

    let result = webdav_sync_service::run_with_sync_lock(webdav_sync_service::upload(
        db,
        &mut sync_settings,
    ))
    .await;
    match result {
        Ok(_) => {
            emit_auto_sync_status_updated(app, "success", None);
            Ok(())
        }
        Err(err) => {
            if let Err(persist_err) = persist_auto_sync_error(&mut sync_settings, &err) {
                log::error!(
                    "[WebDAV][AutoSync] Upload failed and persisting the error status also failed: upload_error={err}; persistence_error={persist_err}"
                );
            }
            emit_auto_sync_status_updated(app, "error", Some(&err.to_string()));
            Err(err)
        }
    }
}

pub fn notify_db_changed(table: &str) {
    if is_auto_sync_suppressed() {
        return;
    }
    if !should_trigger_for_table(table) {
        return;
    }
    let Some(tx) = DB_CHANGE_TX.get() else {
        return;
    };
    match enqueue_change_signal(tx, table) {
        ChangeSignalOutcome::Enqueued | ChangeSignalOutcome::Coalesced => {}
        ChangeSignalOutcome::WorkerUnavailable => {
            if !WORKER_CHANNEL_CLOSED_REPORTED.swap(true, Ordering::SeqCst) {
                log::error!(
                    "[WebDAV][AutoSync] Change-signal channel is closed; the auto-sync worker is unavailable. Further database changes cannot be auto-synced until the worker is reinitialized."
                );
            }
        }
    }
}

pub fn start_worker(db: Arc<crate::database::Database>, app: tauri::AppHandle) {
    if DB_CHANGE_TX.get().is_some() {
        return;
    }

    // Buffer size 1 is enough: we only need "dirty" signals, not every event.
    let (tx, rx) = channel::<String>(1);
    if DB_CHANGE_TX.set(tx).is_err() {
        return;
    }
    WORKER_CHANNEL_CLOSED_REPORTED.store(false, Ordering::SeqCst);

    tauri::async_runtime::spawn(async move {
        run_worker_loop(db, rx, app).await;
    });
}

async fn run_worker_loop(
    db: Arc<crate::database::Database>,
    mut rx: Receiver<String>,
    app: tauri::AppHandle,
) {
    while let Some(first_table) = rx.recv().await {
        let started_at = Instant::now();
        let mut merged_count = 1usize;

        while let Some(wait_for) = auto_sync_wait_duration(started_at, Instant::now()) {
            let timeout = tokio::time::timeout(wait_for, rx.recv()).await;

            match timeout {
                Ok(Some(_)) => merged_count += 1,
                Ok(None) => return,
                Err(_) => break,
            }
        }

        log::debug!(
            "[WebDAV][AutoSync] Triggered by table={first_table}, merged_changes={merged_count}"
        );

        match AssertUnwindSafe(run_auto_sync_upload(&db, &app))
            .catch_unwind()
            .await
        {
            Ok(Ok(())) => {}
            Ok(Err(err)) => log::warn!("[WebDAV][AutoSync] Upload failed: {err}"),
            Err(payload) => log::error!(
                "[WebDAV][AutoSync] Upload panicked; worker will continue processing later changes: {}",
                panic_message(payload.as_ref())
            ),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::{is_auto_sync_suppressed, should_run_auto_sync, AutoSyncSuppressionGuard};
    use crate::settings::WebDavSyncSettings;
    #[test]
    fn suppression_guard_enables_and_restores_state() {
        assert!(!is_auto_sync_suppressed());
        {
            let _guard = AutoSyncSuppressionGuard::new();
            assert!(is_auto_sync_suppressed());
        }
        assert!(!is_auto_sync_suppressed());
    }

    #[test]
    fn should_run_auto_sync_requires_enabled_and_auto_sync_flag() {
        assert!(!should_run_auto_sync(None));

        let disabled = WebDavSyncSettings {
            enabled: false,
            auto_sync: true,
            ..WebDavSyncSettings::default()
        };
        assert!(!should_run_auto_sync(Some(&disabled)));

        let auto_sync_off = WebDavSyncSettings {
            enabled: true,
            auto_sync: false,
            ..WebDavSyncSettings::default()
        };
        assert!(!should_run_auto_sync(Some(&auto_sync_off)));

        let enabled = WebDavSyncSettings {
            enabled: true,
            auto_sync: true,
            ..WebDavSyncSettings::default()
        };
        assert!(should_run_auto_sync(Some(&enabled)));
    }

    #[test]
    fn service_layer_does_not_depend_on_commands_layer() {
        let source = include_str!("webdav_auto_sync.rs");
        let needle = ["crate", "commands", ""].join("::");
        assert!(
            !source.contains(&needle),
            "services layer should not depend on commands layer"
        );
    }
}
