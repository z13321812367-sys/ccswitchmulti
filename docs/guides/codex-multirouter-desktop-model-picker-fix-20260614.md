# CCSwitchMulti Codex MultiRouter 模型候选修复说明

日期：2026-06-14

适用版本：3.16.2-15

## 背景

启用 CCSwitchMulti 的 Codex MultiRouter 后，Codex Desktop 的模型菜单只显示 3 个 OpenAI 模型，例如 GPT-5.5、GPT-5.4、GPT-5.4 Mini。实际期望是 OpenAI、Qwen、DeepSeek 等所有 MultiRouter 候选模型都能进入 Codex 可见候选列表，同时不破坏路由、速度选项、历史 session 和统计。

排查过程中还发现一个相关症状：Codex Desktop 左下角的 OpenAI OAuth 登录账户、剩余额度等信息消失。这个问题看起来像 `auth.json` 被写坏，但实际不是 auth 文件损坏。

## 根因一：模型菜单被 Codex Desktop renderer 白名单过滤

运行态证据显示，CCSwitchMulti 已经把完整模型目录写进 Codex 可读取的数据层：

- `~/.codex/config.toml` 使用稳定的 MultiRouter provider：`codex_model_router_v2`。
- 顶层 `model_catalog_json = "cc-switch-model-catalog.json"` 存在。
- `[model_providers.codex_model_router_v2].models` 内联包含完整候选模型。
- `~/.codex/cc-switch-model-catalog.json` 包含完整候选模型。
- `~/.codex/models_cache.json` 被同步为 cc-switch 生成的候选列表。
- `GET http://127.0.0.1:15721/v1/models` 可以返回完整模型。

但 Codex Desktop renderer 内部还有 Statsig dynamic config gate `107580212`，它会根据远端 `available_models`、`use_hidden_models`、`default_model` 过滤模型菜单。当前远端白名单只放行少数 OpenAI slug，所以本地 catalog 和 `/v1/models` 即使完整，UI 仍只显示 3 个模型。

这不是 provider id 名字导致的，也不是 MultiRouter `/v1/models` 没返回模型。问题发生在 Codex Desktop renderer 已经拿到数据之后的白名单过滤层。

## 根因二：OAuth 信息消失是 provider schema 写错

`~/.codex/auth.json` 经验证仍然是健康的 ChatGPT OAuth 状态：

- `auth_mode = chatgpt`
- 没有 `OPENAI_API_KEY`
- OAuth token 字段存在
- 官方 ChatGPT quota endpoint 可用这些 token 返回额度信息

真正导致左下角账号和额度不显示的是 takeover provider 之前写了：

```toml
requires_openai_auth = false
```

Codex app-server 的 `get_auth_status` 会先看当前 active provider 的 `requires_openai_auth`。如果是 `false`，它直接返回 `auth_method = None` 和 `requires_openai_auth = false`，不会继续读取 `auth.json`。因此 UI 看起来像没有登录。

这个字段只描述 Codex Desktop 是否应该展示和维护 OpenAI OAuth 账号状态，不应该用来决定 MultiRouter 的真实请求路由。真实请求仍由 provider 的 `base_url` 和 `experimental_bearer_token` 控制。

## 为什么不直接改 app.asar

截图里提到的方案是直接修改 Codex Desktop 的 `app.asar`，在 `useHiddenModels + amazonBedrock` 附近改白名单逻辑。这个方向能解释问题，但不适合作为 CCSwitchMulti 的默认修复：

- Windows Codex Desktop 是 MSIX 包，`app.asar` 受包管理保护。
- Codex 更新后 `app.asar` 会被覆盖。
- 直接改安装目录容易触发权限、签名、更新和恢复问题。
- CCSwitchMulti 不应该静态篡改用户安装的 Codex Desktop 包。

因此当前实现采用 Codex++ 同类思路：运行时通过 CDP 注入 renderer patch。它达到同一目标，但不修改磁盘上的 `app.asar`。

## 修复方案

### 1. 保持 MultiRouter 自定义 provider，但恢复 OAuth 语义

文件：

- `src-tauri/src/services/proxy.rs`
- `src-tauri/src/services/provider/mod.rs`

现在 takeover 写出的 Codex provider 仍然是本地 Responses facade：

```toml
model_provider = "codex_model_router_v2"
model_catalog_json = "cc-switch-model-catalog.json"

[model_providers.codex_model_router_v2]
base_url = "http://127.0.0.1:<port>/v1"
wire_api = "responses"
requires_openai_auth = true
supports_websockets = false
experimental_bearer_token = "PROXY_MANAGED"
```

关键边界：

- 不回退到 built-in `openai` provider。
- `requires_openai_auth = true` 只用于让 Codex app-server 继续返回 ChatGPT OAuth 登录、账号和额度状态。
- `experimental_bearer_token = "PROXY_MANAGED"` 仍然保留，请求继续命中本地 MultiRouter。
- `base_url` 仍然指向 `127.0.0.1:<port>/v1`，上游 OpenAI/Qwen/DeepSeek 路由、转换层、统计和历史归属不变。

### 2. 用 CDP 注入修复 Codex Desktop 模型菜单

文件：

- `src-tauri/src/codex_desktop.rs`
- `src-tauri/src/commands/proxy.rs`
- `src-tauri/src/services/proxy.rs`

修复点：

- 启动或发现带 CDP 的 Codex Desktop renderer。
- 给所有匹配的 Codex page target 注入脚本，而不是只注入第一个 target。
- patch Statsig gate `107580212`，扩展 `available_models`，并强制 `use_hidden_models = false`。
- patch app-server `list-models-for-host` 结果。
- patch MCP `model/list` 请求和响应。
- patch `Response.prototype.json`。
- patch React state/object graph，处理 UI 已经 memoize 的旧模型状态。
- patch key 升级到 `__ccSwitchCodexModelPickerUnlockV3`，避免旧脚本缓存。

注意：如果 Codex Desktop 已经从开始菜单正常启动，通常没有 `--remote-debugging-port`，此时 CCSwitchMulti 无法注入 renderer。需要完全退出 Codex Desktop，再由 CCSwitchMulti 启动或执行 unlock model picker。

### 3. 加入 Codex++ 风格的 auth context 兜底

文件：

- `src-tauri/src/codex_desktop.rs`

新增 renderer 兜底：

```js
auth.setAuthMethod("chatgpt")
```

它只修复前端 React auth context 的旧缓存状态，不改变请求路由。主修复仍是 provider schema 写入 `requires_openai_auth = true`。

### 4. 保持模型 catalog 和 cache 的完整投影

已有修复继续保留：

- 切换 MultiRouter provider 时启用 Codex takeover。
- 保存或同步当前 provider 时，如果 Codex 处于 takeover 状态，会把 DB 中的 `modelCatalog` 重新投影到 live config。
- 写入 `~/.codex/cc-switch-model-catalog.json`。
- 同步 `~/.codex/models_cache.json`。
- provider 内联 `models` 保留完整候选，兼容 Desktop custom picker。

## 旧实现与当前实现的差异

旧版 2026-06-08 附近曾通过 built-in `openai` 加 `openai_base_url` 借 Codex 自身刷新模型，所以菜单能显示更多候选。但 built-in `openai` 会把 Codex 拉回官方 OpenAI provider 语义，容易影响本地路由、转换层、历史 bucket、WebSocket/attestation 行为和统计归属。

当前实现坚持稳定 custom/router provider，不靠 provider 名字取巧：

- 模型候选由 CCSwitchMulti 主动生成和同步。
- 请求流量由本地 MultiRouter 接管。
- Codex Desktop UI 白名单通过运行时 CDP patch 修复。
- OAuth UI 通过 `requires_openai_auth = true` 保持官方账号状态可见。

## 验证项

本轮修复已执行：

```powershell
cargo fmt --manifest-path src-tauri\Cargo.toml --check
cargo test --manifest-path src-tauri\Cargo.toml codex_desktop --lib
cargo test --manifest-path src-tauri\Cargo.toml codex_config --lib
cargo test --manifest-path src-tauri\Cargo.toml switching_codex_router_provider_auto_enables_dedicated_local_takeover --lib
cargo test --manifest-path src-tauri\Cargo.toml provider_switch_with_restored_codex_backup_refreshes_catalog_and_common_config --lib
cargo test --manifest-path src-tauri\Cargo.toml apply_codex_proxy_toml_config_uses_custom_local_proxy_provider --lib
cargo test --manifest-path src-tauri\Cargo.toml codex_oauth --lib
cargo check --manifest-path src-tauri\Cargo.toml
pnpm exec tsc --noEmit
pnpm build:renderer
pnpm test:unit
pnpm release:export
```

已知输出：

- Rust 和前端测试通过。
- `cargo check` 仍有既有 `misc.rs` dead_code 警告，与本修复无关。
- Vite build 仍有既有 chunk size / browserslist 警告，与本修复无关。

## 安装后的人工验收

1. 安装或运行 `CCSwitchMulti_3.16.2-15`。
2. 完全退出 Codex Desktop，不要从开始菜单直接重启。
3. 在 CCSwitchMulti 中启用 Codex MultiRouter，让 CCSwitchMulti 启动或解锁 Codex Desktop。
4. 检查 `~/.codex/config.toml`：

```toml
model_provider = "codex_model_router_v2"
model_catalog_json = "cc-switch-model-catalog.json"
requires_openai_auth = true
experimental_bearer_token = "PROXY_MANAGED"
```

5. 检查 Codex Desktop 模型菜单：OpenAI、Qwen、DeepSeek 等候选模型应完整出现。
6. 检查左下角 OpenAI OAuth 账号和额度：应恢复显示。
7. 分别发起 OpenAI、Qwen、DeepSeek 路由请求，确认：

- `~/.cc-switch/logs/codex-router.log` 有对应路由命中。
- CCSwitchMulti 流量统计记录对应 provider。
- 历史 session 仍归属稳定 MultiRouter bucket。

## 产物

Windows 本地导出目录：

```text
C:\Users\sunda\Documents\LLMservice\最新版ccswitchmulti\windows\installer
C:\Users\sunda\Documents\LLMservice\最新版ccswitchmulti\windows\portable
C:\Users\sunda\Documents\LLMservice\最新版ccswitchmulti\windows\raw-exe
```

本次 release 使用 `v3.16.2-15` tag。GitHub Actions release workflow 会按 tag 构建跨平台产物；Windows 本机也会导出本地测试产物。
