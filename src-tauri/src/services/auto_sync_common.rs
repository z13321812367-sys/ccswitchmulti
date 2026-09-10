use std::any::Any;
use std::time::{Duration, Instant};

use tokio::sync::mpsc::error::TrySendError;
use tokio::sync::mpsc::Sender;

pub(crate) const AUTO_SYNC_DEBOUNCE_MS: u64 = 1_000;
pub(crate) const MAX_AUTO_SYNC_WAIT_MS: u64 = 10_000;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum ChangeSignalOutcome {
    Enqueued,
    Coalesced,
    WorkerUnavailable,
}

pub(crate) fn enqueue_change_signal(tx: &Sender<String>, table: &str) -> ChangeSignalOutcome {
    match tx.try_send(table.to_string()) {
        Ok(()) => ChangeSignalOutcome::Enqueued,
        Err(TrySendError::Full(_)) => ChangeSignalOutcome::Coalesced,
        Err(TrySendError::Closed(_)) => ChangeSignalOutcome::WorkerUnavailable,
    }
}

pub(crate) fn should_trigger_for_table(table: &str) -> bool {
    let normalized = table.trim().to_ascii_lowercase();
    matches!(
        normalized.as_str(),
        "providers"
            | "provider_endpoints"
            | "mcp_servers"
            | "prompts"
            | "skills"
            | "skill_repos"
            | "settings"
            | "proxy_config"
    )
}

pub(crate) fn auto_sync_wait_duration(started_at: Instant, now: Instant) -> Option<Duration> {
    let max_wait = Duration::from_millis(MAX_AUTO_SYNC_WAIT_MS);
    let debounce = Duration::from_millis(AUTO_SYNC_DEBOUNCE_MS);
    let elapsed = now.saturating_duration_since(started_at);
    if elapsed >= max_wait {
        return None;
    }
    Some(debounce.min(max_wait - elapsed))
}

pub(crate) fn panic_message(payload: &(dyn Any + Send)) -> &str {
    if let Some(message) = payload.downcast_ref::<&'static str>() {
        message
    } else if let Some(message) = payload.downcast_ref::<String>() {
        message.as_str()
    } else {
        "non-string panic payload"
    }
}

#[cfg(test)]
mod tests {
    use super::{
        auto_sync_wait_duration, enqueue_change_signal, should_trigger_for_table,
        ChangeSignalOutcome, MAX_AUTO_SYNC_WAIT_MS,
    };
    use std::time::{Duration, Instant};
    use tokio::sync::mpsc::channel;

    #[test]
    fn config_tables_share_one_trigger_policy() {
        assert!(should_trigger_for_table("providers"));
        assert!(should_trigger_for_table("settings"));
        assert!(!should_trigger_for_table("proxy_request_logs"));
        assert!(!should_trigger_for_table("provider_health"));
    }

    #[test]
    fn max_wait_caps_flush_latency_for_continuous_events() {
        let started = Instant::now();
        let later = started + Duration::from_millis(MAX_AUTO_SYNC_WAIT_MS + 1);
        assert!(auto_sync_wait_duration(started, later).is_none());
    }

    #[tokio::test]
    async fn full_queue_is_coalescing_but_closed_queue_is_worker_failure() {
        let (tx, rx) = channel::<String>(1);
        assert_eq!(
            enqueue_change_signal(&tx, "providers"),
            ChangeSignalOutcome::Enqueued
        );
        assert_eq!(
            enqueue_change_signal(&tx, "settings"),
            ChangeSignalOutcome::Coalesced
        );

        drop(rx);
        assert_eq!(
            enqueue_change_signal(&tx, "providers"),
            ChangeSignalOutcome::WorkerUnavailable
        );
    }
}
