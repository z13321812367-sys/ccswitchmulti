use std::time::Duration;

/// Even when user/failover timeouts are disabled, transport setup and response headers must not
/// be allowed to wait forever. This is a transport safety boundary, not a failover policy value.
pub(crate) const TRANSPORT_RESPONSE_HEADER_SAFETY_TIMEOUT: Duration = Duration::from_secs(600);

/// Streaming bodies are governed by first-byte/idle logic after headers. Reqwest still needs a
/// finite request-level guard so a broken body cannot hold internal resources forever.
pub(crate) const STREAMING_REQUEST_SAFETY_TIMEOUT: Duration = Duration::from_secs(24 * 60 * 60);

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct ForwarderTimeoutPolicy {
    /// User-configured non-streaming timeout. `None` means the failover timeout is disabled.
    non_streaming: Option<Duration>,
    /// User-configured streaming response-header / first-byte timeout. `None` disables the
    /// failover timer; the transport safety boundary still applies while waiting for headers.
    streaming_first_byte: Option<Duration>,
}

impl ForwarderTimeoutPolicy {
    pub(crate) fn from_seconds(non_streaming: u64, streaming_first_byte: u64) -> Self {
        Self {
            non_streaming: non_zero_seconds(non_streaming),
            streaming_first_byte: non_zero_seconds(streaming_first_byte),
        }
    }

    pub(crate) fn non_streaming_failover_timeout(self) -> Option<Duration> {
        self.non_streaming
    }

    pub(crate) fn streaming_first_byte_failover_timeout(self) -> Option<Duration> {
        self.streaming_first_byte
    }

    /// Timeout used until upstream response headers arrive for non-streaming requests.
    /// Configured failover timeout wins; otherwise the transport safety cap applies.
    pub(crate) fn non_streaming_transport_timeout(self) -> Duration {
        self.non_streaming
            .unwrap_or(TRANSPORT_RESPONSE_HEADER_SAFETY_TIMEOUT)
    }

    /// Timeout used until upstream response headers arrive for streaming requests.
    /// Configured first-byte timeout wins; otherwise the transport safety cap applies.
    pub(crate) fn streaming_header_transport_timeout(self) -> Duration {
        self.streaming_first_byte
            .unwrap_or(TRANSPORT_RESPONSE_HEADER_SAFETY_TIMEOUT)
    }
}

fn non_zero_seconds(seconds: u64) -> Option<Duration> {
    (seconds > 0).then(|| Duration::from_secs(seconds))
}

#[cfg(test)]
mod tests {
    use super::{ForwarderTimeoutPolicy, TRANSPORT_RESPONSE_HEADER_SAFETY_TIMEOUT};
    use std::time::Duration;

    #[test]
    fn zero_disables_failover_timeout_but_not_transport_safety() {
        let policy = ForwarderTimeoutPolicy::from_seconds(0, 0);

        assert_eq!(policy.non_streaming_failover_timeout(), None);
        assert_eq!(policy.streaming_first_byte_failover_timeout(), None);
        assert_eq!(
            policy.non_streaming_transport_timeout(),
            TRANSPORT_RESPONSE_HEADER_SAFETY_TIMEOUT
        );
        assert_eq!(
            policy.streaming_header_transport_timeout(),
            TRANSPORT_RESPONSE_HEADER_SAFETY_TIMEOUT
        );
    }

    #[test]
    fn configured_timeouts_override_transport_header_safety_cap() {
        let policy = ForwarderTimeoutPolicy::from_seconds(45, 12);

        assert_eq!(
            policy.non_streaming_failover_timeout(),
            Some(Duration::from_secs(45))
        );
        assert_eq!(
            policy.streaming_first_byte_failover_timeout(),
            Some(Duration::from_secs(12))
        );
        assert_eq!(
            policy.non_streaming_transport_timeout(),
            Duration::from_secs(45)
        );
        assert_eq!(
            policy.streaming_header_transport_timeout(),
            Duration::from_secs(12)
        );
    }
}
