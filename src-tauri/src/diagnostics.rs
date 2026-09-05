//! Safe diagnostics helpers for data that may contain credentials or user content.
//!
//! Diagnostics must be useful without persisting raw secrets, prompts, model output, cookies,
//! signed URLs, or deep-link configuration payloads.

use http::HeaderMap;
use sha2::{Digest, Sha256};

const FINGERPRINT_HEX_LEN: usize = 16;

/// Redact credentials and query values while retaining endpoint shape and query key names.
pub(crate) fn redact_url_for_log(raw: &str) -> String {
    match url::Url::parse(raw) {
        Ok(parsed) => {
            let mut output = format!("{}://", parsed.scheme());
            if let Some(host) = parsed.host_str() {
                output.push_str(host);
            }
            if let Some(port) = parsed.port() {
                output.push(':');
                output.push_str(&port.to_string());
            }
            output.push_str(parsed.path());

            let mut keys: Vec<String> = parsed
                .query_pairs()
                .map(|(key, _)| key.into_owned())
                .collect();
            keys.sort();
            keys.dedup();
            if !keys.is_empty() {
                output.push_str("?[keys:");
                output.push_str(&keys.join(","));
                output.push(']');
            }
            output
        }
        Err(_) => {
            let without_fragment = raw.split('#').next().unwrap_or(raw);
            match without_fragment.split_once('?') {
                Some((prefix, _)) => format!("{prefix}?[redacted]"),
                None => without_fragment.to_string(),
            }
        }
    }
}

/// Redact credentials and all query material. Suitable for signed URLs where even key names are
/// implementation details that do not improve diagnostics.
pub(crate) fn redact_url_without_query_for_log(raw: &str) -> String {
    match url::Url::parse(raw) {
        Ok(parsed) => {
            let mut output = format!("{}://", parsed.scheme());
            if let Some(host) = parsed.host_str() {
                output.push_str(host);
            }
            if let Some(port) = parsed.port() {
                output.push(':');
                output.push_str(&port.to_string());
            }
            output.push_str(parsed.path());
            output
        }
        Err(_) => raw
            .split('#')
            .next()
            .unwrap_or(raw)
            .split('?')
            .next()
            .unwrap_or(raw)
            .to_string(),
    }
}

/// Return stable payload metadata without retaining the payload itself.
pub(crate) fn payload_fingerprint(bytes: &[u8]) -> String {
    let digest = Sha256::digest(bytes);
    let hex = format!("{digest:x}");
    format!(
        "bytes={}, sha256={}",
        bytes.len(),
        &hex[..FINGERPRINT_HEX_LEN]
    )
}

pub(crate) fn text_fingerprint(text: &str) -> String {
    payload_fingerprint(text.as_bytes())
}

/// Coarse response-body shape used for transport/protocol diagnosis without content disclosure.
pub(crate) fn text_shape_hint(text: &str) -> &'static str {
    let trimmed = text.trim_start_matches('\u{feff}').trim_start();
    if trimmed.is_empty() {
        "empty"
    } else if ["data:", "event:", "id:", "retry:", ":"]
        .iter()
        .any(|prefix| trimmed.starts_with(prefix))
    {
        "sse"
    } else if trimmed.starts_with('<') {
        "markup"
    } else if trimmed.starts_with('{') || trimmed.starts_with('[') {
        "json-like"
    } else {
        "text-or-binary"
    }
}

fn is_sensitive_header(name: &http::HeaderName) -> bool {
    matches!(
        name.as_str(),
        "authorization"
            | "proxy-authorization"
            | "cookie"
            | "set-cookie"
            | "x-api-key"
            | "x-goog-api-key"
            | "x-auth-token"
            | "x-access-token"
            | "www-authenticate"
            | "proxy-authenticate"
    ) || name.as_str().contains("token")
        || name.as_str().contains("secret")
        || name.as_str().contains("credential")
}

/// Format headers for diagnostics while replacing credential-bearing values.
pub(crate) fn format_headers_for_log(headers: &HeaderMap) -> String {
    headers
        .iter()
        .map(|(name, value)| {
            if is_sensitive_header(name) {
                format!("{name}=<redacted>")
            } else {
                let value = value.to_str().unwrap_or("<non-utf8>");
                // Header values can still be arbitrarily large; cap non-sensitive diagnostics.
                let rendered: String = value.chars().take(160).collect();
                if rendered.len() < value.len() {
                    format!("{name}={rendered}…")
                } else {
                    format!("{name}={rendered}")
                }
            }
        })
        .collect::<Vec<_>>()
        .join(", ")
}

#[cfg(test)]
mod tests {
    use super::*;
    use http::{HeaderMap, HeaderValue};

    #[test]
    fn url_redaction_hides_credentials_query_values_and_fragment() {
        let raw = "https://alice:secret@example.com:8443/dav?token=abc&foo=1#private";
        let redacted = redact_url_for_log(raw);
        assert_eq!(redacted, "https://example.com:8443/dav?[keys:foo,token]");
        assert!(!redacted.contains("alice"));
        assert!(!redacted.contains("secret"));
        assert!(!redacted.contains("abc"));
        assert!(!redacted.contains("private"));
    }

    #[test]
    fn signed_url_redaction_drops_query_entirely() {
        let raw = "https://bucket.example/file?X-Amz-Credential=AKID&X-Amz-Signature=secret";
        assert_eq!(
            redact_url_without_query_for_log(raw),
            "https://bucket.example/file"
        );
    }

    #[test]
    fn payload_fingerprint_is_deterministic_and_contains_no_payload() {
        let secret = b"sk-secret-prompt-content";
        let first = payload_fingerprint(secret);
        assert_eq!(first, payload_fingerprint(secret));
        assert!(first.starts_with("bytes=24, sha256="));
        assert!(!first.contains("secret"));
        assert!(!first.contains("prompt"));
    }

    #[test]
    fn header_format_redacts_sensitive_values() {
        let mut headers = HeaderMap::new();
        headers.insert(
            "set-cookie",
            HeaderValue::from_static("session=super-secret"),
        );
        headers.insert("content-type", HeaderValue::from_static("application/json"));
        let rendered = format_headers_for_log(&headers);
        assert!(rendered.contains("set-cookie=<redacted>"));
        assert!(rendered.contains("content-type=application/json"));
        assert!(!rendered.contains("super-secret"));
    }

    #[test]
    fn shape_hint_distinguishes_protocol_shapes_without_content() {
        assert_eq!(text_shape_hint("data: {}\n\n"), "sse");
        assert_eq!(text_shape_hint("<html>blocked</html>"), "markup");
        assert_eq!(text_shape_hint("{\"ok\":true}"), "json-like");
    }
}
