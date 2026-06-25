import { describe, expect, it } from "vitest";
import { normalizeCodexCatalogModelsForSave } from "@/components/providers/forms/ProviderForm";

describe("ProviderForm Codex catalog helpers", () => {
  it("normalizes catalog rows and removes empty or duplicate models", () => {
    expect(
      normalizeCodexCatalogModelsForSave([
        {
          model: " deepseek-v4-flash ",
          upstreamModel: " deepseek-chat ",
          displayName: " DeepSeek ",
        },
        { model: "deepseek-v4-flash", displayName: "Duplicate" },
        { model: "", displayName: "Empty" },
        {
          model: "kimi-k2",
          upstreamModel: "kimi-k2",
          contextWindow: "128000 tokens",
        },
      ]),
    ).toEqual([
      {
        model: "deepseek-v4-flash",
        upstreamModel: "deepseek-chat",
        displayName: "DeepSeek",
      },
      { model: "kimi-k2", contextWindow: 128000 },
    ]);
  });

  it("keeps duplicate upstream models when visible model aliases differ", () => {
    expect(
      normalizeCodexCatalogModelsForSave([
        { model: "gpt-5.5-thirdparty", upstreamModel: "gpt-5.5" },
        { model: "gpt-5.5-backup", upstream_model: "gpt-5.5" },
      ]),
    ).toEqual([
      { model: "gpt-5.5-thirdparty", upstreamModel: "gpt-5.5" },
      { model: "gpt-5.5-backup", upstreamModel: "gpt-5.5" },
    ]);
  });
});
