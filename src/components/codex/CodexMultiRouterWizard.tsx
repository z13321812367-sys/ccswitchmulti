import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  Database,
  GitBranch,
  KeyRound,
  RefreshCw,
  Route,
  Server,
  ShieldAlert,
  Wand2,
  X,
} from "lucide-react";
import { toast } from "sonner";
import type { Provider } from "@/types";
import type { CodexCatalogModel, CodexRoutingRoute } from "@/types";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { providersApi } from "@/lib/api/providers";
import { fetchModelsForConfig } from "@/lib/api/model-fetch";
import {
  CODEX_MULTI_ROUTER_WIZARD_DISMISSED_KEY,
  buildCodexMultiRouterWizardPlan,
  defaultWizardModelSources,
  getWizardModelFetchConfig,
  isCodexMultiRouterPlan,
  readWizardModelCatalog,
  resolveWizardModelNameCollisions,
  type WizardModelFetchConfig,
} from "@/lib/codexMultiRouterWizard";
import type { WorkspaceTab } from "@/components/codex/CodexRouterWorkspacePage";

interface CodexMultiRouterWizardProps {
  open: boolean;
  providers: Provider[];
  onOpenChange: (open: boolean) => void;
  onCreateProvider: () => void;
  onOpenWorkspace: (provider: Provider, tab: WorkspaceTab) => void;
  onEnablePlan: (provider: Provider) => void | Promise<void>;
}

type WizardStepKey =
  | "intro"
  | "sources"
  | "providerConfig"
  | "fetchModels"
  | "collisions"
  | "routes"
  | "publish"
  | "finish";

interface WizardStep {
  key: WizardStepKey;
  title: string;
  description: string;
  icon: typeof Wand2;
}

const STEPS: WizardStep[] = [
  {
    key: "intro",
    title: "理解 MultiRouter",
    description:
      "Codex 仍连接本地 15721，CCSwitchMulti 按 model 分发到不同上游。",
    icon: Wand2,
  },
  {
    key: "sources",
    title: "创建模型源",
    description:
      "逐个添加 OpenAI/中转站、DeepSeek、Qwen、本地 vLLM/Ollama 等 Codex provider。",
    icon: Server,
  },
  {
    key: "providerConfig",
    title: "配置核心参数",
    description:
      "检查 API Key、Base URL、Responses / Chat Completions 以及是否需要本地路由映射。",
    icon: KeyRound,
  },
  {
    key: "fetchModels",
    title: "获取模型列表",
    description: "自动调用 /models，把模型写入每个 provider 的 modelCatalog。",
    icon: RefreshCw,
  },
  {
    key: "collisions",
    title: "处理重名模型",
    description:
      "官方模型保留原名，中转站或第三方同名模型生成可见别名并保留 upstreamModel。",
    icon: ShieldAlert,
  },
  {
    key: "routes",
    title: "生成路由规则",
    description:
      "按 provider 分组生成规则，gpt/o、deepseek、qwen 等前缀自动命中对应上游。",
    icon: GitBranch,
  },
  {
    key: "publish",
    title: "保存并发布",
    description:
      "创建或更新带 codexRouting 和 modelCatalog 的 MultiRouter provider。",
    icon: Database,
  },
  {
    key: "finish",
    title: "启用并测试",
    description: "显式启用这个多路路由，然后打开工作台测试发布页验证命中。",
    icon: CheckCircle2,
  },
];

// 将模型源的模型目录数量转成人可扫读的摘要，避免向导卡片暴露底层 JSON。
function modelSourceSummary(provider: Provider): string {
  const models = readWizardModelCatalog(provider);
  if (models.length === 0) return "尚未获取模型";
  return `${models.length} 个模型`;
}

// 把 /models 抓取参数格式化成安全摘要，不展示真实 API Key。
function fetchConfigSummary(config: WizardModelFetchConfig | null): string {
  if (!config) return "缺少 Base URL 或 API Key";
  return `${config.baseUrl}${config.isFullUrl ? " (完整 URL)" : ""}`;
}

export function CodexMultiRouterWizard({
  open,
  providers,
  onOpenChange,
  onCreateProvider,
  onOpenWorkspace,
  onEnablePlan,
}: CodexMultiRouterWizardProps) {
  const queryClient = useQueryClient();
  const [stepIndex, setStepIndex] = useState(0);
  const [draftSources, setDraftSources] = useState<Provider[]>([]);
  const [savedPlan, setSavedPlan] = useState<Provider | null>(null);
  const [isRefreshingModels, setIsRefreshingModels] = useState(false);
  const [isSavingPlan, setIsSavingPlan] = useState(false);
  const [isEnablingPlan, setIsEnablingPlan] = useState(false);

  const existingPlan = useMemo(
    () => providers.find((provider) => isCodexMultiRouterPlan(provider)),
    [providers],
  );
  const currentStep = STEPS[stepIndex];
  const CurrentStepIcon = currentStep.icon;

  // 每次打开向导都用当前 provider 列表重建草稿，保证用户刚添加的模型源能立即出现。
  useEffect(() => {
    if (!open) return;
    setStepIndex(0);
    setSavedPlan(existingPlan ?? null);
    setDraftSources(defaultWizardModelSources(providers));
  }, [existingPlan, open, providers]);

  // 关闭/跳过时记录 dismissed；首页按钮仍可再次显式打开。
  const closeWizard = (dismissed = true) => {
    if (dismissed) {
      localStorage.setItem(CODEX_MULTI_ROUTER_WIZARD_DISMISSED_KEY, "true");
    }
    onOpenChange(false);
  };

  // 顺序抓取所有可抓模型源；失败不阻塞其它 provider，最终由保存页继续使用已成功目录。
  const refreshModelSources = async () => {
    setIsRefreshingModels(true);
    try {
      const nextSources: Provider[] = [];
      let successCount = 0;
      let skippedCount = 0;
      for (const provider of draftSources) {
        const config = getWizardModelFetchConfig(provider);
        if (!config) {
          skippedCount += 1;
          nextSources.push(provider);
          continue;
        }
        try {
          const fetchedModels = await fetchModelsForConfig(
            config.baseUrl,
            config.apiKey,
            config.isFullUrl,
            config.modelsUrl,
            config.customUserAgent,
          );
          const nextProvider = {
            ...provider,
            settingsConfig: {
              ...provider.settingsConfig,
              modelCatalog: {
                ...(provider.settingsConfig?.modelCatalog ?? {}),
                models: fetchedModels.map((model) => ({
                  model: model.id,
                  upstreamModel: model.id,
                  displayName: model.id,
                  ...(model.contextWindow
                    ? { contextWindow: model.contextWindow }
                    : {}),
                })),
              },
            },
          };
          await providersApi.update(nextProvider, "codex");
          nextSources.push(nextProvider);
          successCount += 1;
        } catch (error) {
          console.error("[CodexMultiRouterWizard] fetch models failed", error);
          nextSources.push(provider);
        }
      }
      setDraftSources(resolveWizardModelNameCollisions(nextSources));
      await queryClient.invalidateQueries({ queryKey: ["providers", "codex"] });
      toast.success(
        `模型列表刷新完成：${successCount} 个成功，${skippedCount} 个跳过。`,
        { closeButton: true },
      );
    } finally {
      setIsRefreshingModels(false);
    }
  };

  // 保存 MultiRouter provider；这里才真正写入 DB，不会静默切换当前 Codex provider。
  const saveMultiRouterPlan = async () => {
    setIsSavingPlan(true);
    try {
      const result = buildCodexMultiRouterWizardPlan(
        providers,
        draftSources,
        existingPlan,
      );
      if (existingPlan) {
        await providersApi.update(result.plan, "codex");
      } else {
        await providersApi.add(result.plan, "codex", false);
      }
      setSavedPlan(result.plan);
      setDraftSources(result.sourceProviders);
      await queryClient.invalidateQueries({ queryKey: ["providers", "codex"] });
      toast.success("MultiRouter 方案已保存。", { closeButton: true });
      setStepIndex(STEPS.length - 1);
    } finally {
      setIsSavingPlan(false);
    }
  };

  // 启用动作复用 App 里的 switchProvider 路径，保证 Codex 接管和 OAuth 保留逻辑保持一致。
  const enableSavedPlan = async () => {
    if (!savedPlan) return;
    setIsEnablingPlan(true);
    try {
      await onEnablePlan(savedPlan);
      toast.success(
        "已启用多路模型。请完整重启或新开 Codex 会话验证模型选择器。",
        {
          closeButton: true,
          duration: 8000,
        },
      );
    } finally {
      setIsEnablingPlan(false);
    }
  };

  if (!open) return null;

  const planPreview = buildCodexMultiRouterWizardPlan(
    providers,
    draftSources,
    existingPlan,
  ).plan;
  const previewRoutes = (planPreview.settingsConfig.codexRouting?.routes ??
    []) as CodexRoutingRoute[];
  const previewModels = (planPreview.settingsConfig.modelCatalog?.models ??
    []) as CodexCatalogModel[];

  return createPortal(
    <div className="fixed inset-0 z-[120] bg-black/70 text-foreground backdrop-blur-sm">
      <div className="absolute inset-x-4 top-6 mx-auto max-w-5xl rounded-lg border border-white/15 bg-background shadow-2xl">
        <div className="flex items-start justify-between border-b px-5 py-4">
          <div className="flex items-start gap-3">
            <div className="rounded-md bg-primary/10 p-2 text-primary">
              <CurrentStepIcon className="h-5 w-5" />
            </div>
            <div>
              <div className="text-sm text-muted-foreground">
                第 {stepIndex + 1} / {STEPS.length} 步
              </div>
              <h2 className="text-xl font-semibold">{currentStep.title}</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                {currentStep.description}
              </p>
            </div>
          </div>
          <Button
            variant="ghost"
            size="icon"
            onClick={() => closeWizard(true)}
            aria-label="关闭多路模型配置向导"
          >
            <X className="h-4 w-4" />
          </Button>
        </div>

        <div className="grid max-h-[72vh] grid-cols-[14rem_1fr] overflow-hidden">
          <div className="space-y-1 border-r bg-muted/30 p-3">
            {STEPS.map((step, index) => {
              const StepIcon = step.icon;
              return (
                <button
                  key={step.key}
                  type="button"
                  className={`flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm ${
                    index === stepIndex
                      ? "bg-primary text-primary-foreground"
                      : "text-muted-foreground hover:bg-muted"
                  }`}
                  onClick={() => setStepIndex(index)}
                >
                  <StepIcon className="h-4 w-4 shrink-0" />
                  <span className="truncate">{step.title}</span>
                </button>
              );
            })}
          </div>

          <div className="overflow-y-auto p-5">
            {currentStep.key === "intro" && (
              <div className="space-y-4">
                <div className="rounded-lg border p-4">
                  <div className="flex items-center gap-2 font-medium">
                    <Route className="h-4 w-4" />
                    本地 15721 继续作为 Codex 唯一入口
                  </div>
                  <p className="mt-2 text-sm leading-6 text-muted-foreground">
                    向导会生成一个本地 MultiRouter provider。Codex 请求仍发到
                    127.0.0.1:15721，CCSwitchMulti 根据请求体里的 model
                    匹配路由，再把请求交给 OpenAI/中转站、DeepSeek、Qwen
                    或本地模型。
                  </p>
                </div>
                <div className="rounded-lg border p-4 text-sm text-muted-foreground">
                  自动化只会在你点击“保存并发布”后写入 providers
                  数据库；启用当前 Codex provider 需要最后一步显式点击。
                </div>
              </div>
            )}

            {currentStep.key === "sources" && (
              <div className="space-y-4">
                <div className="flex items-center justify-between gap-3">
                  <p className="text-sm text-muted-foreground">
                    当前识别到 {draftSources.length} 个普通 Codex provider
                    可作为模型源。
                  </p>
                  <Button onClick={onCreateProvider}>
                    <Server className="mr-2 h-4 w-4" />
                    添加 Provider
                  </Button>
                </div>
                <div className="grid gap-3 md:grid-cols-2">
                  {draftSources.map((provider) => (
                    <div key={provider.id} className="rounded-lg border p-3">
                      <div className="font-medium">{provider.name}</div>
                      <div className="mt-1 text-xs text-muted-foreground">
                        {provider.id}
                      </div>
                      <Badge variant="outline" className="mt-3">
                        {modelSourceSummary(provider)}
                      </Badge>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {currentStep.key === "providerConfig" && (
              <div className="space-y-3">
                {draftSources.map((provider) => {
                  const config = getWizardModelFetchConfig(provider);
                  return (
                    <div
                      key={provider.id}
                      className="rounded-lg border p-4 text-sm"
                    >
                      <div className="flex items-center justify-between gap-3">
                        <div className="font-medium">{provider.name}</div>
                        <Badge variant={config ? "outline" : "destructive"}>
                          {config ? "可自动获取模型" : "需补全配置"}
                        </Badge>
                      </div>
                      <div className="mt-2 text-muted-foreground">
                        {fetchConfigSummary(config)}
                      </div>
                      <div className="mt-2 text-xs text-muted-foreground">
                        API 格式：
                        {provider.meta?.apiFormat ??
                          provider.settingsConfig?.apiFormat ??
                          provider.settingsConfig?.api_format ??
                          "未显式设置，向导保存路由时默认 Chat Completions"}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}

            {currentStep.key === "fetchModels" && (
              <div className="space-y-4">
                <Button
                  onClick={refreshModelSources}
                  disabled={isRefreshingModels || draftSources.length === 0}
                >
                  <RefreshCw
                    className={`mr-2 h-4 w-4 ${
                      isRefreshingModels ? "animate-spin" : ""
                    }`}
                  />
                  自动获取并写入模型列表
                </Button>
                <div className="grid gap-3 md:grid-cols-2">
                  {draftSources.map((provider) => (
                    <div key={provider.id} className="rounded-lg border p-3">
                      <div className="font-medium">{provider.name}</div>
                      <div className="mt-2 text-sm text-muted-foreground">
                        {modelSourceSummary(provider)}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {currentStep.key === "collisions" && (
              <div className="space-y-4">
                <Button
                  variant="outline"
                  onClick={() =>
                    setDraftSources(
                      resolveWizardModelNameCollisions(draftSources),
                    )
                  }
                >
                  <ShieldAlert className="mr-2 h-4 w-4" />
                  重新计算重名别名
                </Button>
                <div className="rounded-lg border p-4 text-sm text-muted-foreground">
                  同名策略：官方/订阅模型保留原名；中转站或第三方模型显示成
                  relay-gpt-5.4-mini 这类别名，upstreamModel
                  仍指向真实上游模型名。
                </div>
                <div className="max-h-72 overflow-auto rounded-lg border">
                  {previewModels.slice(0, 80).map((model) => (
                    <div
                      key={`${model.model}:${model.upstreamModel ?? ""}`}
                      className="flex items-center justify-between border-b px-3 py-2 text-sm last:border-b-0"
                    >
                      <span>{model.model}</span>
                      <span className="text-muted-foreground">
                        {model.upstreamModel &&
                        model.upstreamModel !== model.model
                          ? `上游 ${model.upstreamModel}`
                          : "原名"}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {currentStep.key === "routes" && (
              <div className="space-y-3">
                {previewRoutes.map((route) => (
                  <div key={route.id} className="rounded-lg border p-4">
                    <div className="flex items-center justify-between gap-3">
                      <div className="font-medium">{route.label}</div>
                      <Badge variant="outline">
                        {route.upstream.apiFormat}
                      </Badge>
                    </div>
                    <div className="mt-2 text-sm text-muted-foreground">
                      模型 {route.match.models?.length ?? 0} 个；前缀{" "}
                      {(route.match.prefixes ?? []).join(", ") || "无"}
                    </div>
                  </div>
                ))}
              </div>
            )}

            {currentStep.key === "publish" && (
              <div className="space-y-4">
                <div className="rounded-lg border p-4 text-sm text-muted-foreground">
                  将保存 {previewRoutes.length} 条路由和 {previewModels.length}{" "}
                  个可见模型到{" "}
                  {existingPlan ? existingPlan.name : "新的 MultiRouter"}。
                </div>
                <Button
                  onClick={saveMultiRouterPlan}
                  disabled={isSavingPlan || draftSources.length === 0}
                >
                  <Database className="mr-2 h-4 w-4" />
                  {isSavingPlan ? "正在保存..." : "保存并发布"}
                </Button>
              </div>
            )}

            {currentStep.key === "finish" && (
              <div className="space-y-4">
                <div className="rounded-lg border p-4 text-sm leading-6 text-muted-foreground">
                  保存完成后，请显式启用这个多路路由。启用后保持 CCSwitchMulti
                  运行，并完整重启或新开 Codex 会话，让模型选择器读取新的
                  modelCatalog。
                </div>
                <div className="flex flex-wrap gap-3">
                  <Button
                    onClick={enableSavedPlan}
                    disabled={!savedPlan || isEnablingPlan}
                  >
                    <CheckCircle2 className="mr-2 h-4 w-4" />
                    启用这个多路路由
                  </Button>
                  <Button
                    variant="outline"
                    disabled={!savedPlan}
                    onClick={() => {
                      if (!savedPlan) return;
                      closeWizard(false);
                      onOpenWorkspace(savedPlan, "test");
                    }}
                  >
                    <Route className="mr-2 h-4 w-4" />
                    完成后打开工作台
                  </Button>
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="flex items-center justify-between border-t px-5 py-4">
          <Button variant="ghost" onClick={() => closeWizard(true)}>
            跳过
          </Button>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              onClick={() => setStepIndex((index) => Math.max(0, index - 1))}
              disabled={stepIndex === 0}
            >
              <ArrowLeft className="mr-2 h-4 w-4" />
              上一步
            </Button>
            <Button
              onClick={() =>
                stepIndex === STEPS.length - 1
                  ? closeWizard(false)
                  : setStepIndex((index) =>
                      Math.min(STEPS.length - 1, index + 1),
                    )
              }
            >
              {stepIndex === STEPS.length - 1 ? "关闭" : "下一步"}
              {stepIndex !== STEPS.length - 1 && (
                <ArrowRight className="ml-2 h-4 w-4" />
              )}
            </Button>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}
