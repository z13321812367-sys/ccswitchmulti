import { useCallback, useEffect, useRef, useState } from "react";

export interface CodexLocalRoutingNoticeState {
  isOpen: boolean;
  dismiss: () => void;
}

// 监听 Codex 本地路由从关闭变为开启；只在状态边沿弹一次，避免代理状态轮询导致重复打扰。
export function useCodexLocalRoutingNotice(
  isLocalRoutingActive: boolean,
): CodexLocalRoutingNoticeState {
  const [isOpen, setIsOpen] = useState(false);
  const wasLocalRoutingActiveRef = useRef(false);

  useEffect(() => {
    const becameActive =
      isLocalRoutingActive && !wasLocalRoutingActiveRef.current;
    wasLocalRoutingActiveRef.current = isLocalRoutingActive;
    if (becameActive) {
      setIsOpen(true);
    }
  }, [isLocalRoutingActive]);

  // 用户确认后只关闭当前提示；下次本地路由重新从关闭变为开启时会再次提醒。
  const dismiss = useCallback(() => {
    setIsOpen(false);
  }, []);

  return { isOpen, dismiss };
}
