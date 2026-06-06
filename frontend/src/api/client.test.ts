import { describe, it, expect, vi, beforeEach } from "vitest";
import { apiGet } from "./client";

// 默认(未设 VITE_API_BASE)应走同源相对路径 —— 不带 host:port 前缀。
// 这条用例锁死「同源默认」,防止再退回到打不通的绝对 :8000。
describe("api client BASE", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("默认同源:fetch 收到的是相对路径,不含 http(s):// 或 :8000", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ok: 1 }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await apiGet("/api/health");

    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toBe("/api/health");
    expect(url).not.toMatch(/^https?:\/\//);
    expect(url).not.toContain(":8000");
  });
});
