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


replace_once(
    "src-tauri/src/proxy/forwarder.rs",
    '''    thinking_rectifier::{\n        normalize_thinking_type, rectify_anthropic_request, should_rectify_thinking_signature,\n    },\n    types::{CopilotOptimizerConfig, OptimizerConfig, ProxyStatus, RectifierConfig},\n''',
    '''    thinking_rectifier::{\n        normalize_thinking_type, rectify_anthropic_request, should_rectify_thinking_signature,\n    },\n    timeout_policy::{ForwarderTimeoutPolicy, STREAMING_REQUEST_SAFETY_TIMEOUT},\n    types::{CopilotOptimizerConfig, OptimizerConfig, ProxyStatus, RectifierConfig},\n''',
)

replace_once(
    "src-tauri/src/proxy/forwarder.rs",
    '''    /// 非流式请求超时（秒）\n    non_streaming_timeout: std::time::Duration,\n    /// 流式请求响应头等待超时（秒）\n    streaming_first_byte_timeout: std::time::Duration,\n''',
    '''    /// 显式区分用户/故障转移 timeout 与传输层安全上限，禁止再用 Duration::ZERO\n    /// 同时表达“禁用用户 timeout”和“使用 600s transport fallback”两种不同语义。\n    timeout_policy: ForwarderTimeoutPolicy,\n''',
)

replace_once(
    "src-tauri/src/proxy/forwarder.rs",
    '''            codex_responses_lite_fallbacks: Arc::new(RwLock::new(HashMap::new())),\n            non_streaming_timeout: std::time::Duration::from_secs(non_streaming_timeout),\n            streaming_first_byte_timeout: std::time::Duration::from_secs(\n                streaming_first_byte_timeout,\n            ),\n            max_attempts,\n''',
    '''            codex_responses_lite_fallbacks: Arc::new(RwLock::new(HashMap::new())),\n            timeout_policy: ForwarderTimeoutPolicy::from_seconds(\n                non_streaming_timeout,\n                streaming_first_byte_timeout,\n            ),\n            max_attempts,\n''',
)

replace_once(
    "src-tauri/src/proxy/forwarder.rs",
    '''        // 确定超时\n        let timeout = if self.non_streaming_timeout.is_zero() {\n            std::time::Duration::from_secs(600) // 默认 600 秒\n        } else {\n            self.non_streaming_timeout\n        };\n''',
    '''        // 传输层安全上限与用户/故障转移 timeout 是两种独立语义。\n        // 即使用户配置 0（禁用故障转移 timeout），等待上游响应头也不能无限挂起。\n        let transport_header_timeout = if request_is_streaming {\n            self.timeout_policy.streaming_header_transport_timeout()\n        } else {\n            self.timeout_policy.non_streaming_transport_timeout()\n        };\n''',
)

replace_once(
    "src-tauri/src/proxy/forwarder.rs",
    '''                    ("timeout_ms", timeout.as_millis().to_string()),\n''',
    '''                    (\n                        "transport_header_timeout_ms",\n                        transport_header_timeout.as_millis().to_string(),\n                    ),\n                    (\n                        "failover_timeout_enabled",\n                        (if request_is_streaming {\n                            self.timeout_policy\n                                .streaming_first_byte_failover_timeout()\n                                .is_some()\n                        } else {\n                            self.timeout_policy.non_streaming_failover_timeout().is_some()\n                        })\n                        .to_string(),\n                    ),\n''',
)

replace_once(
    "src-tauri/src/proxy/forwarder.rs",
    '''                    timeout,\n                    request_is_streaming,\n                    self.non_streaming_timeout,\n                    self.streaming_first_byte_timeout,\n                    is_socks_proxy,\n''',
    '''                    transport_header_timeout,\n                    request_is_streaming,\n                    self.timeout_policy,\n                    is_socks_proxy,\n''',
)

replace_once(
    "src-tauri/src/proxy/forwarder.rs",
    '''        if self.non_streaming_timeout.is_zero() {\n            return Ok(response);\n        }\n\n        let status = response.status();\n        let headers = response.headers().clone();\n        let body_timeout = self.non_streaming_timeout;\n''',
    '''        let Some(body_timeout) = self.timeout_policy.non_streaming_failover_timeout() else {\n            return Ok(response);\n        };\n\n        let status = response.status();\n        let headers = response.headers().clone();\n''',
)

replace_once(
    "src-tauri/src/proxy/forwarder.rs",
    '''        if self.streaming_first_byte_timeout.is_zero() {\n            return Ok(response);\n        }\n\n        let status = response.status();\n        let headers = response.headers().clone();\n        let timeout = self.streaming_first_byte_timeout;\n''',
    '''        let Some(timeout) = self\n            .timeout_policy\n            .streaming_first_byte_failover_timeout()\n        else {\n            return Ok(response);\n        };\n\n        let status = response.status();\n        let headers = response.headers().clone();\n''',
)

replace_once(
    "src-tauri/src/proxy/forwarder.rs",
    '''    timeout: std::time::Duration,\n    request_is_streaming: bool,\n    non_streaming_timeout: std::time::Duration,\n    streaming_first_byte_timeout: std::time::Duration,\n    is_socks_proxy: bool,\n''',
    '''    transport_header_timeout: std::time::Duration,\n    request_is_streaming: bool,\n    timeout_policy: ForwarderTimeoutPolicy,\n    is_socks_proxy: bool,\n''',
)

replace_once(
    "src-tauri/src/proxy/forwarder.rs",
    '''        let client = super::http_client::get();\n        let mut request = client.request(method.clone(), &url);\n        if request_is_streaming {\n            request = request.timeout(std::time::Duration::from_secs(24 * 60 * 60));\n        } else if !non_streaming_timeout.is_zero() {\n            request = request.timeout(non_streaming_timeout);\n        }\n''',
    '''        let client = super::http_client::get();\n        let mut request = client.request(method.clone(), &url);\n        if request_is_streaming {\n            request = request.timeout(STREAMING_REQUEST_SAFETY_TIMEOUT);\n        } else {\n            // Explicit per-request value keeps Reqwest aligned with the Hyper path even when\n            // the user disables failover timeouts. Do not depend on the shared client's default.\n            request = request.timeout(timeout_policy.non_streaming_transport_timeout());\n        }\n''',
)

replace_once(
    "src-tauri/src/proxy/forwarder.rs",
    '''        let send_result = if request_is_streaming {\n            let header_timeout = if streaming_first_byte_timeout.is_zero() {\n                timeout\n            } else {\n                streaming_first_byte_timeout\n            };\n            match tokio::time::timeout(header_timeout, send).await {\n''',
    '''        let send_result = if request_is_streaming {\n            match tokio::time::timeout(transport_header_timeout, send).await {\n''',
)

replace_once(
    "src-tauri/src/proxy/forwarder.rs",
    '''                        "流式响应首包超时: {}s（上游未返回响应头）",\n                        header_timeout.as_secs()\n''',
    '''                        "流式响应头等待超时: {}s（上游未返回响应头）",\n                        transport_header_timeout.as_secs()\n''',
)

replace_once(
    "src-tauri/src/proxy/forwarder.rs",
    '''        timeout,\n        upstream_proxy_url,\n''',
    '''        transport_header_timeout,\n        upstream_proxy_url,\n''',
)

# Make the public-facing contract accurate: 0 disables failover/body timers, not the independent
# transport header safety cap used by both Reqwest and Hyper.
replace_once(
    "src-tauri/src/proxy/handler_context.rs",
    '''    /// 配置生效规则：\n    /// - 故障转移开启：超时配置正常生效（0 表示禁用超时）\n    /// - 故障转移关闭：超时配置不生效（全部传入 0）\n''',
    '''    /// 配置生效规则：\n    /// - 故障转移开启：用户超时配置正常生效（0 表示禁用故障转移/body timeout）；\n    /// - 故障转移关闭：用户超时配置不生效（全部传入 0）；\n    /// - 两种模式都保留独立的 transport response-header safety cap，避免连接永久挂起。\n''',
)
replace_once(
    "src-tauri/src/proxy/handler_context.rs",
    '''        // 故障转移关闭时强制 max_retries=0（仅尝试 1 个 provider），与「不超时 + 不切换」语义一致。\n''',
    '''        // 故障转移关闭时强制 max_retries=0（仅尝试 1 个 provider）。\n        // 用户级 failover/body timeout 被禁用，但 transport safety cap 仍保留。\n''',
)

forwarder = (ROOT / "src-tauri/src/proxy/forwarder.rs").read_text(encoding="utf-8")
for forbidden in (
    "self.non_streaming_timeout",
    "self.streaming_first_byte_timeout",
    "let header_timeout = if streaming_first_byte_timeout.is_zero()",
    "Duration::from_secs(600) // 默认 600 秒",
):
    if forbidden in forwarder:
        raise SystemExit(f"forwarder still contains legacy timeout semantic: {forbidden}")

print("Applied explicit proxy timeout policy integration")
