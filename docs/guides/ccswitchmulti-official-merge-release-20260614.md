# CCSwitchMulti 3.16.2-17 官方合并发布说明

日期：2026-06-14

版本：3.16.2-17

上游基线：`farion1231/cc-switch` `main`，提交 `0c46efe1`

官方 release 基线：`farion1231/cc-switch` 最新公开 release 仍为 `v3.16.2`。因此 CCSwitchMulti 继续使用 `3.16.2-*` 发布线，本次版本为 `3.16.2-17`。

本次目标是在 CCSwitchMulti 的 `feat/codex-local-model-routing` 分支上合并最新官方 cc-switch，同时保留 Codex MultiRouter 的模型候选、路由、OAuth、历史 session 和统计归因行为。

## 合并原则

1. 不把 Codex MultiRouter 退回 built-in `openai` provider。
2. 保留稳定的 MultiRouter provider bucket 和历史 session 迁移逻辑。
3. 保留 Codex Desktop 模型候选解锁、完整 catalog 注入、速度选项和本地 route 配置。
4. 接收官方新增能力，包括自定义 User-Agent、官方统一 session bucket、usage dashboard/统计更新、供应商预设和文档更新。
5. 不覆盖用户本地未提交改动；本次合并期间未暂存 `src-tauri/src/services/skill.rs`、`src-tauri/tests/skill_sync.rs` 和 `scripts/logs/`。

## 关键冲突处理

### Codex 历史迁移

文件：`src-tauri/src/codex_history_migration.rs`

- 保留官方 `maybe_migrate_codex_official_history_to_unified_bucket`。
- 保留 CCSwitchMulti 的 `maybe_migrate_codex_openai_history_provider_bucket`。
- 保留 `sync_codex_history_provider_bucket_to_multirouter`，用于把 Codex 历史 bucket 同步到 MultiRouter provider。
- 将 JSONL 和 state DB provider bucket 迁移 helper 泛化为带 `target_provider_id` 参数的实现，避免官方 `custom` bucket 和 MultiRouter bucket 互相覆盖。
- 删除测试也不再使用的旧 wrapper，避免 dead-code warning。

### Codex 配置和启动迁移

文件：`src-tauri/src/lib.rs`

- 启动阶段同时运行 CCSwitchMulti 的 OpenAI/history bucket 兼容迁移和官方 unified history 迁移。
- 这样既保留旧版 MultiRouter 历史可见性，又接入官方最新的统一 session 修复。

### settings 保存合并

文件：`src-tauri/src/commands/settings.rs`

- 采用官方策略：保存 settings 时以后端现有 `local_migrations` 为准。
- 防止前端旧缓存把已经清理或已经完成的本地迁移 marker 重新写回。
- 测试中补齐 `codex_openai_history_provider_bucket_v2`，确保 CCSwitchMulti 自有迁移 marker 也被保留。

### 请求转发和统计归因

文件：

- `src-tauri/src/proxy/forwarder.rs`
- `src-tauri/src/proxy/handler_context.rs`
- `src-tauri/src/proxy/handlers.rs`

处理方式：

- `forward` 成功结果同时返回实际 effective provider 和 `outbound_model`。
- `RequestContext` 增加 `outbound_model`，成功转发后回填。
- usage 记录使用三层兜底：上游响应模型、`outbound_model`、客户端请求模型。
- MultiRouter 场景下统计锚定真实上游模型，不再只按 Codex 请求别名归因。

### Codex 表单

文件：`src/components/providers/forms/CodexFormFields.tsx`

- 保留 CCSwitchMulti 的本地模型路由编辑器。
- 接入官方新增的高级设置折叠区域和自定义 User-Agent 字段。
- 测试 harness 补齐 `customUserAgent` 和 `onCustomUserAgentChange` props。

### 流式 usage 和媒体清洗

文件：

- `src-tauri/src/proxy/providers/streaming.rs`
- `src-tauri/src/proxy/media_sanitizer.rs`

处理方式：

- 接收官方 Anthropic cache accounting 修复：input tokens 同时扣减 cache read 和 cache creation。
- 保留 CCSwitchMulti DeepSeek V4 alias 图片替换测试。
- 保留官方 `image_url` 和 Codex `input_image` 清洗覆盖。

## 验证记录

已通过：

```powershell
cargo fmt --manifest-path src-tauri\Cargo.toml --check
cargo check --manifest-path src-tauri\Cargo.toml
cargo test --manifest-path src-tauri\Cargo.toml codex_history_migration --lib
cargo test --manifest-path src-tauri\Cargo.toml media_sanitizer --lib
cargo test --manifest-path src-tauri\Cargo.toml streaming --lib
cargo test --manifest-path src-tauri\Cargo.toml save_settings_should --lib
cargo test --manifest-path src-tauri\Cargo.toml proxy::handlers --lib
pnpm typecheck
pnpm build:renderer
pnpm exec vitest run tests/components/CodexFormFields.test.tsx tests/components/ClaudeFormFields.test.tsx tests/lib/userAgent.test.ts
```

`cargo check` 仍有官方 `src-tauri/src/commands/misc.rs` 中两个未使用函数 warning；本次没有改动该无关逻辑。

## 发布步骤

版本号已更新：

- `package.json`
- `src-tauri/tauri.conf.json`
- `src-tauri/Cargo.toml`
- `src-tauri/Cargo.lock`

本地导出命令：

```powershell
pnpm release:export
```

预期导出目录：

```text
C:\Users\sunda\Documents\LLMservice\最新版ccswitchmulti\windows\installer
C:\Users\sunda\Documents\LLMservice\最新版ccswitchmulti\windows\portable
C:\Users\sunda\Documents\LLMservice\最新版ccswitchmulti\windows\raw-exe
```

Git tag：

```text
v3.16.2-17
```
