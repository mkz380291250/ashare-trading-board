import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPost } from "../api/client";

type Decision = { id: number; code: string; action: string; confidence: number;
  shares: number; status: string; reasoning: string };

export function DecisionsPanel() {
  const [rows, setRows] = useState<Decision[]>([]);
  const load = useCallback(() => {
    apiGet<Decision[]>("/api/decisions").then(setRows).catch(() => {});
  }, []);
  useEffect(load, [load]);

  async function act(id: number, what: "approve" | "reject") {
    const body = what === "approve" ? { price: 0 } : {};
    await apiPost(`/api/decisions/${id}/${what}`, body);
    load();
  }

  if (!rows.length) return <p>暂无决策</p>;
  return (
    <div style={{ display: "grid", gap: 12 }}>
      {rows.map((d) => (
        <div key={d.id} style={{ border: "1px solid #ccc", padding: 8 }}>
          <b>{d.code}</b> — {d.action} (信心 {d.confidence.toFixed(2)}, {d.shares}股)
          {" "}[{d.status}]
          {d.status === "PENDING" && (
            <span style={{ marginLeft: 8 }}>
              <button onClick={() => act(d.id, "approve")}>批准</button>
              <button onClick={() => act(d.id, "reject")}>驳回</button>
            </span>
          )}
          <details><summary>理由</summary>
            <pre style={{ whiteSpace: "pre-wrap" }}>{d.reasoning}</pre>
          </details>
        </div>
      ))}
    </div>
  );
}
