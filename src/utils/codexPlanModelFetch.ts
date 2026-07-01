export interface CodexPlanModelFetchSource {
  baseUrl?: string | null;
  partnerPromotionKey?: string | null;
  providerName?: string | null;
}

const CATALOG_ONLY_PLAN_PROMOTION_KEYS = new Set([
  "volcengine_agentplan",
  "byteplus",
]);

const CATALOG_ONLY_PLAN_BASE_URL_MARKERS = [
  "ark.cn-beijing.volces.com/api/coding/v3",
  "ark.ap-southeast.bytepluses.com/api/coding/v3",
];

// 归一化用于 Plan provider 判定的文本，避免大小写、尾斜杠和空格导致漏判。
function normalizePlanFetchText(value?: string | null): string {
  return String(value ?? "")
    .trim()
    .replace(/\/+$/, "")
    .toLowerCase();
}

// 判断当前 Codex provider 是否只能使用内置 modelCatalog，而不能走 OpenAI `/models` 自动枚举。
export function isCodexCatalogOnlyPlanModelFetch(
  source: CodexPlanModelFetchSource,
): boolean {
  const promotionKey = normalizePlanFetchText(source.partnerPromotionKey);
  if (promotionKey && CATALOG_ONLY_PLAN_PROMOTION_KEYS.has(promotionKey)) {
    return true;
  }

  const baseUrl = normalizePlanFetchText(source.baseUrl);
  if (
    baseUrl &&
    CATALOG_ONLY_PLAN_BASE_URL_MARKERS.some((marker) =>
      baseUrl.includes(marker),
    )
  ) {
    return true;
  }

  const providerName = normalizePlanFetchText(source.providerName);
  return (
    providerName.includes("agentplan") &&
    (providerName.includes("火山") || providerName.includes("volc"))
  );
}

// 生成 catalog-only Plan 的用户提示；有目录时是正常跳过，没有目录时提示需要手动恢复。
export function codexCatalogOnlyPlanModelFetchMessage(
  hasModelCatalog: boolean,
): string {
  return hasModelCatalog
    ? "当前 Plan 的模型枚举不开放 OpenAI /models，已保留内置 modelCatalog。"
    : "当前 Plan 的模型枚举不开放 OpenAI /models，请手动添加模型或重新选择预设恢复 modelCatalog。";
}
