import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CodexUsagePage } from "./CodexUsagePage";
import { useSubscriptionQuota } from "@/lib/query/subscription";

vi.mock("@/lib/query/subscription", () => ({
  useSubscriptionQuota: vi.fn(),
}));

const mockedUseSubscriptionQuota = vi.mocked(useSubscriptionQuota);

/** 生成测试用的 quota query 返回值，避免每条用例重复声明 React Query 字段。 */
function mockQuotaResult(data: unknown, isFetching = false) {
  mockedUseSubscriptionQuota.mockReturnValue({
    data,
    isFetching,
    refetch: vi.fn(),
  } as any);
}

describe("CodexUsagePage", () => {
  beforeEach(() => {
    mockedUseSubscriptionQuota.mockReset();
  });

  it("renders Codex usage windows and banked reset credits", () => {
    mockQuotaResult({
      tool: "codex",
      credentialStatus: "valid",
      credentialMessage: null,
      success: true,
      tiers: [
        {
          name: "five_hour",
          utilization: 36,
          resetsAt: "2026-07-06T15:00:00.000Z",
        },
        {
          name: "seven_day",
          utilization: 68,
          resetsAt: "2026-07-12T15:00:00.000Z",
        },
      ],
      extraUsage: null,
      resetCredits: {
        availableCount: 2,
        credits: [
          {
            resetType: "rate_limit",
            status: "available",
            expiresAt: "2026-07-08T15:00:00.000Z",
            title: "Banked reset",
          },
        ],
      },
      resetCreditsError: "one credit missing expiry",
      error: null,
      queriedAt: 1783300000000,
    });

    render(<CodexUsagePage />);

    expect(screen.getByText("Codex 用量与重置额度")).toBeInTheDocument();
    expect(screen.getByText("使用引导")).toBeInTheDocument();
    expect(screen.getByText("从 Codex 工具栏进入")).toBeInTheDocument();
    expect(screen.getByText("按窗口和到期时间决策")).toBeInTheDocument();
    expect(screen.getByText("5 小时窗口")).toBeInTheDocument();
    expect(screen.getByText("每周窗口")).toBeInTheDocument();
    expect(screen.getByText("已存 reset 额度")).toBeInTheDocument();
    expect(screen.getByText("2 个可用")).toBeInTheDocument();
    expect(screen.getByText("Banked reset")).toBeInTheDocument();
    expect(screen.getByText(/Reset credit 明细读取不完整/)).toBeInTheDocument();
  });

  it("shows a visible problem state when Codex credentials are unavailable", () => {
    mockQuotaResult({
      tool: "codex",
      credentialStatus: "not_found",
      credentialMessage: "未找到 Codex 登录文件",
      success: false,
      tiers: [],
      extraUsage: null,
      resetCredits: null,
      resetCreditsError: null,
      error: null,
      queriedAt: null,
    });

    render(<CodexUsagePage />);

    expect(screen.getByText("Codex 登录不可用")).toBeInTheDocument();
    expect(screen.getByText("未找到 Codex 登录文件")).toBeInTheDocument();
  });
});
