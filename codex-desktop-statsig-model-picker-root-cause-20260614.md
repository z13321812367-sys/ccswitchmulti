# Codex Desktop Statsig model picker root cause

Date: 2026-06-14

## Runtime evidence

The MultiRouter write path is now complete:

- `%USERPROFILE%\.codex\config.toml` points to `model_provider = "codex_model_router_v2"`.
- Top-level `model_catalog_json = "cc-switch-model-catalog.json"` is present.
- `[model_providers.codex_model_router_v2].models` contains all 7 display models.
- `%USERPROFILE%\.codex\cc-switch-model-catalog.json` contains 7 models.
- `%USERPROFILE%\.codex\models_cache.json` is cc-switch owned and contains 7 models.
- `GET http://127.0.0.1:15721/v1/models` with a Codex user agent returns `models=7` and `data=7`.
- `%USERPROFILE%\.codex\auth.json` remains ChatGPT OAuth: `auth_mode = chatgpt`, no `OPENAI_API_KEY`, and OAuth tokens are still present.

The current failing runtime still has:

- Codex main process launched without `--remote-debugging-port`.
- Candidate CDP ports `9229`, `9222`, `9223`, `9230`, and `9231` closed.

Therefore the remaining "only 3 OpenAI models" symptom is not caused by `auth.json`, provider id naming, `/v1/models`, or an incomplete catalog. It is caused by Codex Desktop renderer filtering the already-loaded model list.

## Codex Desktop filtering chain

The installed Codex Desktop app bundle contains:

- `webview/assets/model-queries-*.js`
- `webview/assets/models-and-reasoning-efforts-*.js`

The renderer calls app-server `list-models-for-host` / `model/list` with `includeHidden: true`, then applies the Statsig dynamic config gate `107580212`:

- `available_models`
- `use_hidden_models`
- `default_model`

When `use_hidden_models` is true and `authMethod !== "amazonBedrock"`, the UI keeps only models whose slug is in `available_models`. The current remote whitelist contains the 3 official OpenAI slugs, so custom Qwen/DeepSeek/local slugs disappear even though the local catalog and `/v1/models` are correct.

## Codex++ comparison

Codex++ does not solve this by only writing `config.toml` or `auth.json`. Its durable path is:

- launch Codex Desktop with `--remote-debugging-port`;
- inject a renderer script through CDP;
- patch Statsig gate `107580212`;
- patch app-server `model/list` / `list-models-for-host` responses;
- patch `Response.prototype.json`;
- patch React state/object graphs after the UI has already memoized model state.

This matches the failure observed in CCSwitchMulti: the data layer has 7 models, but the renderer whitelist reduces the visible picker to 3.

## CCSwitchMulti fix

The CCSwitchMulti fix keeps routing and auth unchanged, and only repairs the Desktop renderer picker:

- `src-tauri/src/codex_desktop.rs`
  - bumps the renderer patch key to v2;
  - injects into every matching Codex CDP page target instead of only the first page;
  - enables `Runtime` and `Page` before installing the script;
  - patches model containers to set `use_hidden_models = false` and `useHiddenModels = false`;
  - still expands `available_models`, app-server model arrays, response JSON, and React state.
- `src-tauri/src/services/proxy.rs`
  - after Codex takeover, calls the full unlock path so Codex is launched with CDP when it is not already running;
  - if Codex is already running without CDP, it logs a precise warning instead of pretending the catalog is the blocker.
- `src-tauri/src/commands/proxy.rs`
  - diagnostics now expose whether Codex is running with remote debugging and explicitly call out the Statsig `107580212` renderer filter.

The fix intentionally does not patch `app.asar` on disk. On Windows MSIX installs this file is package-managed, update-prone, and commonly protected. Runtime CDP injection is the same class of solution used by Codex++ and keeps the change local to the active Desktop renderer.

## Operational implication

If Codex Desktop is already running normally, CCSwitchMulti cannot inject into that process. The user must fully quit Codex Desktop and then use CCSwitchMulti's "unlock model picker" entry, or enable MultiRouter while Codex is not running so CCSwitchMulti can start Codex with the CDP flag.

Manual "restart Codex" from the Windows Start menu is not enough, because that starts Codex without `--remote-debugging-port` and leaves the renderer whitelist unpatchable.
