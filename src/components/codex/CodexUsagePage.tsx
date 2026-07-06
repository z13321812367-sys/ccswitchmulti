import React from "react";
import {
  AlertCircle,
  CheckCircle2,
  Clock,
  Gauge,
  RefreshCw,
  RotateCcw,
  TimerReset,
} from "lucide-react";
import { useSubscriptionQuota } from "@/lib/query/subscription";
import type {
  QuotaTier,
  ResetCreditInfo,
  SubscriptionQuota,
} from "@/types/subscription";

const TRACKED_TIERS = new Set(["five_hour", "seven_day"]);

const TIER_LABELS: Record<string, string> = {
  five_hour: "5 小时窗口",
  seven_day: "每周窗口",
  weekly_limit: "每周窗口",
};

interface UsageWindowCardProps {
  tier: QuotaTier;
}

interface ResetCreditRowProps {
  credit: ResetCreditInfo;
  index: number;
}

/** 将百分比限制在进度条可安全渲染的 0-100 区间。 */
function clampPercent(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.min(Math.max(value, 0), 100);
}

/** 根据已用百分比返回容量状态文案。 */
function describeCapacity(utilization: number): string {
  if (utilization >= 95) return "接近耗尽";
  if (utilization >= 75) return "偏紧";
  if (utilization >= 50) return "正常";
  return "充足";
}

/** 根据已用百分比返回页面上的语义颜色。 */
function capacityTone(utilization: number): string {
  if (utilization >= 95) return "text-red-600 dark:text-red-400";
  if (utilization >= 75) return "text-amber-600 dark:text-amber-400";
  if (utilization >= 50) return "text-blue-600 dark:text-blue-400";
  return "text-emerald-600 dark:text-emerald-400";
}

/** 根据已用百分比返回进度条颜色。 */
function capacityBarTone(utilization: number): string {
  if (utilization >= 95) return "bg-red-500";
  if (utilization >= 75) return "bg-amber-500";
  if (utilization >= 50) return "bg-blue-500";
  return "bg-emerald-500";
}

/** 把 ISO 时间格式化为本地可读时间；无效或缺失时返回兜底文案。 */
function formatDateTime(value: string | null | undefined): string {
  if (!value) return "未返回";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "无法解析";
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** 把毫秒时间戳格式化为最近刷新时间。 */
function formatCheckedAt(value: number | null | undefined): string {
  if (!value) return "尚未刷新";
  return new Date(value).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** 计算 reset credit 到期紧迫度，用于提示即将过期的额度。 */
function resetCreditUrgency(expiresAt: string | null | undefined): {
  label: string;
  className: string;
} {
  if (!expiresAt) {
    return {
      label: "无到期记录",
      className: "text-muted-foreground",
    };
  }
  const expiresAtMs = new Date(expiresAt).getTime();
  if (Number.isNaN(expiresAtMs)) {
    return {
      label: "到期时间异常",
      className: "text-amber-600 dark:text-amber-400",
    };
  }
  const hoursLeft = (expiresAtMs - Date.now()) / (1000 * 60 * 60);
  if (hoursLeft <= 0) {
    return {
      label: "已过期",
      className: "text-red-600 dark:text-red-400",
    };
  }
  if (hoursLeft <= 24) {
    return {
      label: "今天到期",
      className: "text-red-600 dark:text-red-400",
    };
  }
  if (hoursLeft <= 72) {
    return {
      label: "即将到期",
      className: "text-amber-600 dark:text-amber-400",
    };
  }
  if (hoursLeft <= 24 * 7) {
    return {
      label: "本周到期",
      className: "text-blue-600 dark:text-blue-400",
    };
  }
  return {
    label: "可用",
    className: "text-emerald-600 dark:text-emerald-400",
  };
}

/** 判断 reset credit 是否仍处于官方 available 状态。 */
function isAvailableCredit(credit: ResetCreditInfo): boolean {
  return credit.status?.toLowerCase() === "available";
}

/** 从额度响应中挑出主页面展示的 Codex 速率窗口。 */
function getVisibleTiers(quota: SubscriptionQuota | undefined): QuotaTier[] {
  return (quota?.tiers ?? []).filter(
    (tier) => TRACKED_TIERS.has(tier.name) || tier.name in TIER_LABELS,
  );
}

/** 渲染单个 5 小时/每周用量窗口。 */
const UsageWindowCard: React.FC<UsageWindowCardProps> = ({ tier }) => {
  const used = clampPercent(tier.utilization);
  const remaining = Math.max(0, 100 - used);
  const label = TIER_LABELS[tier.name] ?? tier.name;

  return (
    <section className="rounded-lg border border-border-default bg-card p-4 shadow-sm">
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <div className="text-sm font-semibold text-foreground">{label}</div>
          <div className="mt-1 text-xs text-muted-foreground">
            重置时间：{formatDateTime(tier.resetsAt)}
          </div>
        </div>
        <div className={`text-right ${capacityTone(used)}`}>
          <div className="text-2xl font-semibold tabular-nums">
            {Math.round(remaining)}%
          </div>
          <div className="text-xs font-medium">剩余</div>
        </div>
      </div>

      <div className="h-2 overflow-hidden rounded-full bg-muted">
        <div
          className={`h-full rounded-full transition-all ${capacityBarTone(used)}`}
          style={{ width: `${used}%` }}
        />
      </div>

      <div className="mt-3 flex items-center justify-between text-xs">
        <span className={capacityTone(used)}>{describeCapacity(used)}</span>
        <span className="text-muted-foreground tabular-nums">
          已用 {Math.round(used)}%
        </span>
      </div>
    </section>
  );
};

/** 渲染单条 banked reset credit 到期记录。 */
const ResetCreditRow: React.FC<ResetCreditRowProps> = ({ credit, index }) => {
  const urgency = resetCreditUrgency(credit.expiresAt);

  return (
    <div className="grid grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-3 rounded-lg border border-border-default bg-background px-3 py-2 text-sm">
      <div className="min-w-0">
        <div className="truncate font-medium text-foreground">
          {credit.title || `Reset ${index + 1}`}
        </div>
        <div className="text-xs text-muted-foreground">
          状态：{credit.status ?? "unknown"}
        </div>
      </div>
      <div className="text-xs text-muted-foreground tabular-nums">
        {formatDateTime(credit.expiresAt)}
      </div>
      <div className={`text-xs font-medium ${urgency.className}`}>
        {urgency.label}
      </div>
    </div>
  );
};

/** 渲染凭据缺失、过期或接口失败时的页面级状态。 */
function renderQuotaProblem(
  quota: SubscriptionQuota | undefined,
  loading: boolean,
  refetch: () => void,
): React.ReactNode {
  if (loading && !quota) {
    return (
      <div className="rounded-lg border border-border-default bg-card p-6 text-sm text-muted-foreground">
        正在读取本机 Codex 登录状态...
      </div>
    );
  }

  if (!quota) return null;

  const isCredentialProblem =
    quota.credentialStatus === "not_found" ||
    quota.credentialStatus === "expired" ||
    quota.credentialStatus === "parse_error";

  if (!isCredentialProblem && quota.success) return null;

  const title = isCredentialProblem ? "Codex 登录不可用" : "额度查询失败";
  const detail =
    quota.credentialMessage ||
    quota.error ||
    "请确认 Codex Desktop / CLI 已登录，然后刷新。";

  return (
    <section className="rounded-lg border border-amber-200 bg-amber-50 p-5 text-sm text-amber-900 shadow-sm dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-100">
      <div className="mb-3 flex items-center gap-2 font-semibold">
        <AlertCircle className="h-4 w-4" />
        {title}
      </div>
      <p className="mb-4 text-amber-800 dark:text-amber-200">{detail}</p>
      <button
        type="button"
        onClick={refetch}
        disabled={loading}
        className="inline-flex items-center gap-2 rounded-lg border border-amber-300 bg-background px-3 py-2 text-xs font-medium text-foreground transition-colors hover:bg-amber-100 disabled:opacity-50 dark:border-amber-700 dark:hover:bg-amber-900/40"
      >
        <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
        重新刷新
      </button>
    </section>
  );
}

/** Codex 用量与 banked reset credits 的独立工具页。 */
export const CodexUsagePage: React.FC = () => {
  const {
    data: quota,
    isFetching,
    refetch,
  } = useSubscriptionQuota("codex", true, true, 5);
  const visibleTiers = getVisibleTiers(quota);
  const availableCredits = (quota?.resetCredits?.credits ?? []).filter(
    isAvailableCredit,
  );
  const availableCount = Math.max(quota?.resetCredits?.availableCount ?? 0, 0);
  const missingExpiryCount = Math.max(
    availableCount - availableCredits.length,
    0,
  );
  const problem = renderQuotaProblem(quota, isFetching, () => void refetch());

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-5 px-6 py-6">
      <section className="rounded-lg border border-border-default bg-card p-5 shadow-sm">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex min-w-0 items-start gap-3">
            <div className="rounded-lg bg-emerald-500/10 p-2 text-emerald-600 dark:text-emerald-400">
              <Gauge className="h-5 w-5" />
            </div>
            <div className="min-w-0">
              <h2 className="text-lg font-semibold text-foreground">
                Codex 用量与重置额度
              </h2>
              <p className="mt-1 text-sm text-muted-foreground">
                当前页面读取本机 Codex 登录，只展示额度状态，不兑换
                reset、不修改账号。
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-3 text-sm">
            <div className="inline-flex items-center gap-2 rounded-lg border border-border-default bg-background px-3 py-2 text-muted-foreground">
              <Clock className="h-4 w-4" />
              {formatCheckedAt(quota?.queriedAt)}
            </div>
            <button
              type="button"
              onClick={() => void refetch()}
              disabled={isFetching}
              className="inline-flex items-center gap-2 rounded-lg bg-foreground px-3 py-2 text-sm font-medium text-background transition-colors hover:bg-foreground/90 disabled:opacity-50"
            >
              <RefreshCw
                className={`h-4 w-4 ${isFetching ? "animate-spin" : ""}`}
              />
              刷新
            </button>
          </div>
        </div>
      </section>

      {problem}

      {quota?.success && (
        <>
          <div className="grid gap-4 lg:grid-cols-2">
            {visibleTiers.map((tier) => (
              <UsageWindowCard key={tier.name} tier={tier} />
            ))}
            {visibleTiers.length === 0 && (
              <section className="rounded-lg border border-border-default bg-card p-5 text-sm text-muted-foreground shadow-sm lg:col-span-2">
                Codex 没有返回 5 小时或每周用量窗口。
              </section>
            )}
          </div>

          <section className="rounded-lg border border-border-default bg-card p-5 shadow-sm">
            <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-center gap-2">
                <RotateCcw className="h-4 w-4 text-sky-600 dark:text-sky-400" />
                <h3 className="text-base font-semibold text-foreground">
                  Banked reset credits
                </h3>
              </div>
              <div className="inline-flex items-center gap-2 rounded-lg bg-sky-500/10 px-3 py-2 text-sm font-semibold text-sky-700 dark:text-sky-300">
                <TimerReset className="h-4 w-4" />
                {availableCount} 个可用
              </div>
            </div>

            {availableCount > 0 ? (
              <div className="flex flex-col gap-2">
                {availableCredits.map((credit, index) => (
                  <ResetCreditRow
                    key={`${credit.expiresAt ?? "missing"}-${index}`}
                    credit={credit}
                    index={index}
                  />
                ))}
                {missingExpiryCount > 0 && (
                  <div className="rounded-lg border border-dashed border-border-default bg-background px-3 py-2 text-sm text-muted-foreground">
                    还有 {missingExpiryCount} 个可用 reset
                    没有返回可展示的到期明细。
                  </div>
                )}
              </div>
            ) : (
              <div className="flex items-center gap-2 rounded-lg border border-border-default bg-background px-3 py-3 text-sm text-muted-foreground">
                <CheckCircle2 className="h-4 w-4 text-emerald-600 dark:text-emerald-400" />
                当前没有 banked reset credits。
              </div>
            )}

            {quota.resetCreditsError && (
              <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-200">
                Reset credit 明细读取不完整：{quota.resetCreditsError}
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
};
