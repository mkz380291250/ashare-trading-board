import { useEffect, useState } from "react";
import { apiGet } from "../api/client";

type Pick = { as_of: string; code: string; rank: number; score: number;
  factors: Record<string, number> };

export function DiscoveryPanel() {
  const [picks, setPicks] = useState<Pick[]>([]);
  useEffect(() => {
    apiGet<Pick[]>("/api/discovery").then(setPicks).catch(() => {});
  }, []);
  if (!picks.length) return <p>机会榜暂无数据</p>;
  return (
    <table>
      <thead><tr><th>#</th><th>代码</th><th>评分</th><th>因子</th></tr></thead>
      <tbody>
        {picks.map((p) => (
          <tr key={p.code}>
            <td>{p.rank}</td><td>{p.code}</td><td>{p.score.toFixed(3)}</td>
            <td>{Object.entries(p.factors).map(([k, v]) => `${k}:${v.toFixed(2)}`).join("  ")}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
