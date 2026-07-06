import React from "react";
import {
  AlertCircle,
  ArrowRight,
  CheckCircle2,
  Clock,
  Gauge,
  Info,
  RefreshCw,
  RotateCcw,
  TimerReset,
} from "lucide-react";
import { Button } from "@/components/ui/button";
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

interface GuideStepProps {
  index: number;
  title: string;
  detail: string;
}

interface UsageReadingHintProps {
  title: string;
  detail: string;
  tone: "ok" | "warn" | "info";
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

/** 引导步骤条目：说明从哪里进入页面以及读数顺序。 */
const GuideStep: React.FC<GuideStepProps> = ({ index, title, detail }) => (
  <div className="flex gap-3 rounded-lg border border-blue-200 bg-card p-3 text-sm dark:border-blue-700/40 dark:bg-slate-950/40">
    <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-blue-600 text-xs font-semibold text-white">
      {index}
    </div>
    <div className="min-w-0">
      <div className="font-medium text-foreground">{title}</div>
      <div className="mt-1 text-xs leading-5 text-muted-foreground">
        {detail}
      </div>
    </div>
  </div>
);

/** 读数提示条目：把颜色和阈值解释成可执行判断。 */
const UsageReadingHint: React.FC<UsageReadingHintProps> = ({
  title,
  detail,
  tone,
}) => {
  const toneClass =
    tone === "ok"
      ? "border-emerald-200 bg-emerald-50/70 text-emerald-900 dark:border-emerald-700/40 dark:bg-emerald-950/20 dark:text-emerald-100"
      : tone === "warn"
        ? "border-amber-200 bg-amber-50/70 text-amber-900 dark:border-amber-700/40 dark:bg-amber-950/20 dark:text-amber-100"
        : "border-blue-200 bg-blue-50/70 text-blue-900 dark:border-blue-700/40 dark:bg-blue-950/20 dark:text-blue-100";

  return (
    <div className={`rounded-lg border px-3 py-2 ${toneClass}`}>
      <div className="text-xs font-semibold">{title}</div>
      <div className="mt-1 text-xs leading-5 opacity-80">{detail}</div>
    </div>
  );
};

/** 页面引导区：补齐入口、刷新和读数判断，避免用户只看到一组静态数字。 */
const UsageGuidePanel: React.FC = () => (
  <section className="rounded-lg border border-blue-200 bg-blue-50/70 p-4 dark:border-blue-700/40 dark:bg-blue-950/15">
    <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-blue-900 dark:text-blue-100">
      <Info className="h-4 w-4" />
      使用引导
    </div>
    <div className="grid gap-3 lg:grid-cols-3">
      <GuideStep
        index={1}
        title="从 Codex 工具栏进入"
        detail="主界面先切到 Codex，再点多模型路由旁边的柱状图按钮。"
      />
      <GuideStep
        index={2}
        title="先刷新当前登录"
        detail="页面读取本机 Codex Desktop / CLI 登录；刷新只重新查询，不兑换 reset。"
      />
      <GuideStep
        index={3}
        title="按窗口和到期时间决策"
        detail="先看 5 小时与每周剩余额度，再看 reset 是否临近到期。"
      />
    </div>
    <div className="mt-3 grid gap-2 lg:grid-cols-3">
      <UsageReadingHint
        tone="ok"
        title="绿色 / 蓝色"
        detail="容量还可用，适合继续工作或保留 reset。"
      />
      <UsageReadingHint
        tone="warn"
        title="黄色 / 红色"
        detail="窗口偏紧；如果刷新还远，优先规划 reset 或等待。"
      />
      <UsageReadingHint
        tone="info"
        title="到期提示"
        detail="今天到期、即将到期、本周到期会单独标出，避免 reset 白白过期。"
      />
    </div>
  </section>
);

/** 渲染单个 5 小时/每周用量窗口。 */
const UsageWindowCard: React.FC<UsageWindowCardProps> = ({ tier }) => {
  const used = clampPercent(tier.utilization);
  const remaining = Math.max(0, 100 - used);
  const label = TIER_LABELS[tier.name] ?? tier.name;

  return (
    <section className="rounded-lg border border-border bg-card p-4 dark:border-slate-700/80 dark:bg-slate-950/30">
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

      <div className="h-2 overflow-hidden rounded-full bg-muted dark:bg-slate-800">
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
    <div className="grid grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-3 rounded-lg border border-border bg-background px-3 py-2 text-sm dark:border-slate-700/70 dark:bg-slate-950/40">
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
      <div className="rounded-lg border border-border bg-card p-6 text-sm text-muted-foreground dark:border-slate-700/80 dark:bg-slate-950/30">
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
      <Button
        type="button"
        onClick={refetch}
        disabled={loading}
        size="sm"
        variant="outline"
        className="gap-2 border-amber-300 hover:bg-amber-100 dark:border-amber-700 dark:hover:bg-amber-900/40"
      >
        <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
        重新刷新
      </Button>
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
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 px-6 py-6">
      <section className="overflow-hidden rounded-lg border border-border bg-card dark:border-slate-700/80 dark:bg-slate-950/30">
        <div className="flex flex-col gap-4 bg-gradient-to-r from-blue-50 via-background to-emerald-50 px-4 py-3 dark:from-blue-950/45 dark:via-slate-900 dark:to-emerald-950/30 lg:flex-row lg:items-center lg:justify-between">
          <div className="min-w-0 space-y-2">
            <div className="flex items-center gap-2 text-base font-semibold">
              <Gauge className="h-4 w-4 text-blue-600 dark:text-blue-300" />
              Codex 用量与重置额度
            </div>
            <p className="max-w-4xl text-xs leading-5 text-muted-foreground dark:text-slate-400">
              这里查看的是当前 Codex 登录账号的速率窗口和已存 reset
              额度。页面只读：不会兑换 reset、不会修改账号，也不会写入 Codex
              配置。
            </p>
            <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <span className="inline-flex items-center gap-1 rounded-md border border-border bg-background px-2 py-1 dark:border-slate-700/80 dark:bg-slate-950/40">
                Codex 工具栏
                <ArrowRight className="h-3 w-3" />
                柱状图按钮
              </span>
              <span className="inline-flex items-center gap-1 rounded-md border border-border bg-background px-2 py-1 dark:border-slate-700/80 dark:bg-slate-950/40">
                只读查询
              </span>
              <span className="inline-flex items-center gap-1 rounded-md border border-border bg-background px-2 py-1 dark:border-slate-700/80 dark:bg-slate-950/40">
                自动 5 分钟刷新
              </span>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-3 text-sm">
            <div className="inline-flex items-center gap-2 rounded-lg border border-border bg-background px-3 py-2 text-muted-foreground dark:border-slate-700/80 dark:bg-slate-950/40">
              <Clock className="h-4 w-4" />
              {formatCheckedAt(quota?.queriedAt)}
            </div>
            <Button
              type="button"
              onClick={() => void refetch()}
              disabled={isFetching}
              size="sm"
              className="gap-2 bg-blue-600 hover:bg-blue-500"
            >
              <RefreshCw
                className={`h-4 w-4 ${isFetching ? "animate-spin" : ""}`}
              />
              刷新
            </Button>
          </div>
        </div>
      </section>

      <UsageGuidePanel />

      {problem}

      {quota?.success && (
        <>
          <div className="grid gap-4 lg:grid-cols-2">
            {visibleTiers.map((tier) => (
              <UsageWindowCard key={tier.name} tier={tier} />
            ))}
            {visibleTiers.length === 0 && (
              <section className="rounded-lg border border-border bg-card p-5 text-sm text-muted-foreground dark:border-slate-700/80 dark:bg-slate-950/30 lg:col-span-2">
                Codex 没有返回 5 小时或每周用量窗口。
              </section>
            )}
          </div>

          <section className="rounded-lg border border-border bg-card p-5 dark:border-slate-700/80 dark:bg-slate-950/30">
            <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-center gap-2">
                <RotateCcw className="h-4 w-4 text-sky-600 dark:text-sky-400" />
                <h3 className="text-base font-semibold text-foreground">
                  已存 reset 额度
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
                  <div className="rounded-lg border border-dashed border-border bg-background px-3 py-2 text-sm text-muted-foreground dark:border-slate-700/70 dark:bg-slate-950/40">
                    还有 {missingExpiryCount} 个可用 reset
                    没有返回可展示的到期明细。
                  </div>
                )}
              </div>
            ) : (
              <div className="flex items-center gap-2 rounded-lg border border-border bg-background px-3 py-3 text-sm text-muted-foreground dark:border-slate-700/70 dark:bg-slate-950/40">
                <CheckCircle2 className="h-4 w-4 text-emerald-600 dark:text-emerald-400" />
                当前没有已存 reset 额度。
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
