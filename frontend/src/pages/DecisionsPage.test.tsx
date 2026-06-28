import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { DecisionsPage } from "./DecisionsPage";

const LIST = [{ id: 1, code: "600519.SH", action: "HOLD", status: "PENDING" }];
const DETAIL = {
  id: 1, code: "600519.SH", name: null, action: "HOLD", confidence: 0.62,
  shares: 0, status: "PENDING", summary: "空仓观望",
  roles: [{ role: "量价分析师", stage: "analyst", stance: "bull",
    action: null, confidence: 0.7, text: "放量突破" }],
};

describe("DecisionsPage", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn((url: string) => {
      if (/\/decisions\/jobs/.test(url)) return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      if (/\/decisions\/run/.test(url)) return Promise.resolve({ ok: true, json: () => Promise.resolve({ id: 2, code: "000001.SZ", status: "PENDING" }) });
      if (/\/decisions\/1$/.test(url)) return Promise.resolve({ ok: true, json: () => Promise.resolve(DETAIL) });
      return Promise.resolve({ ok: true, json: () => Promise.resolve(LIST) });
    }) as any);
  });

  it("loads list then detail with role viewpoints", async () => {
    render(<DecisionsPage />);
    await waitFor(() => expect(screen.getByText("空仓观望")).toBeInTheDocument());
    expect(screen.getByText("分析师团")).toBeInTheDocument();
    expect(screen.getByText("放量突破")).toBeInTheDocument();
  });

  it('shows composite score and LOW_CONF status', async () => {
    vi.stubGlobal('fetch', vi.fn((url: string) => {
      let body: unknown;
      if (/\/decisions\/jobs/.test(url)) {
        body = [];
      } else if (/\/decisions\/\d/.test(url)) {
        body = { id: 1, code: '600519.SH', name: '', action: 'BUY', confidence: 0.5, shares: 0, status: 'LOW_CONF', summary: '', roles: [] };
      } else {
        body = [{ id: 1, code: '600519.SH', name: '贵州茅台', action: 'BUY',
                  confidence: 0.5, status: 'LOW_CONF', score: 0.95, reasoning: '' }];
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve(body) }) as any;
    }))
    render(<DecisionsPage />)
    expect(await screen.findByText('LOW_CONF')).toBeTruthy()
    expect(await screen.findByText('0.95')).toBeTruthy()
  })

  it("submitting a code calls /api/decisions/run", async () => {
    const calls: string[] = [];
    vi.stubGlobal("fetch", vi.fn((url: string, init?: any) => {
      calls.push(url + (init?.method ? `:${init.method}` : ""));
      if (/\/decisions\/jobs/.test(url)) return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      if (/\/decisions\/run/.test(url)) return Promise.resolve({ ok: true, json: () => Promise.resolve({ id: 1, code: "600519.SH", status: "PENDING" }) });
      if (/\/decisions\/1$/.test(url)) return Promise.resolve({ ok: true, json: () => Promise.resolve({ id:1, code:"x", name:"", action:"HOLD", confidence:0, shares:0, status:"APPROVED", summary:"", roles:[] }) });
      return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
    }) as any);
    render(<DecisionsPage />);
    fireEvent.change(screen.getByPlaceholderText("输入股票代号"), { target: { value: "600519" } });
    fireEvent.click(screen.getByText("开始辩论"));
    await waitFor(() => expect(calls.some((c) => /\/decisions\/run:POST/.test(c))).toBe(true));
  });
});
