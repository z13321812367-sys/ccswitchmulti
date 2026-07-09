import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useCodexLocalRoutingNotice } from "@/hooks/useCodexLocalRoutingNotice";

describe("useCodexLocalRoutingNotice", () => {
  it("opens once when Codex local routing becomes active", async () => {
    const { result, rerender } = renderHook(
      ({ active }) => useCodexLocalRoutingNotice(active),
      { initialProps: { active: false } },
    );

    expect(result.current.isOpen).toBe(false);

    rerender({ active: true });
    await waitFor(() => expect(result.current.isOpen).toBe(true));

    act(() => result.current.dismiss());
    expect(result.current.isOpen).toBe(false);

    rerender({ active: true });
    expect(result.current.isOpen).toBe(false);
  });

  it("opens again after local routing is disabled and re-enabled", async () => {
    const { result, rerender } = renderHook(
      ({ active }) => useCodexLocalRoutingNotice(active),
      { initialProps: { active: true } },
    );

    await waitFor(() => expect(result.current.isOpen).toBe(true));
    act(() => result.current.dismiss());
    expect(result.current.isOpen).toBe(false);

    rerender({ active: false });
    expect(result.current.isOpen).toBe(false);

    rerender({ active: true });
    await waitFor(() => expect(result.current.isOpen).toBe(true));
  });
});
