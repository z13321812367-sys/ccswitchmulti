# Codex MultiRouter Debug Notes

## 2026-06-12

MultiRouter 页面的一键 Debug 检查用于判断请求是否真正进入本地 Codex router。它只读本机现场，不会向真实上游发送模型请求。

检查范围：

- 本地代理进程状态和 TCP 端口可达性。
- `~/.codex/config.toml` 当前 `model_provider`、active `base_url`、`wire_api`、`supports_websockets`。
- Responses WebSocket 回退探针：`GET /v1/responses` 带 Upgrade 头，预期本地代理返回 HTTP 426。
- 当前 MultiRouter provider 的 `codexRouting`、启用规则数、目标 provider 是否存在、route 的模型匹配摘要。
- `~/.cc-switch/logs/codex-router.log` 最近事件。

结果解释：

- `route_resolved`、`request_prepared`、`upstream_send`、`upstream_status` 表示请求已经进入 MultiRouter。
- 没有近期 router 事件时，如果用户刚在 Codex 发过请求，优先看 live config 是否被接管到本地 custom provider，而不是继续判断端口是否监听。
- `upstream_send_error`、`upstream_error` 表示请求已进入 MultiRouter，后续应排查目标 provider、转换层或上游返回。
- MultiRouter 正常接管 Codex 时应写入 custom model provider，并设置 `supports_websockets=false`。内置 `openai` provider 指向本地 base URL 会触发 Codex 官方 WebSocket/OpenAI 语义，不适合作为 MultiRouter 接管方式。

