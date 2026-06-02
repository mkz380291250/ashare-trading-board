import { useState } from "react";
import { apiPost } from "../api/client";

export function TradeForm({ accountId, onDone }: { accountId: number; onDone: () => void }) {
  const [code, setCode] = useState("600519.SH");
  const [side, setSide] = useState("BUY");
  const [price, setPrice] = useState(1500);
  const [shares, setShares] = useState(100);
  const [msg, setMsg] = useState("");

  async function submit() {
    try {
      await apiPost("/api/trade", {
        account_id: accountId, code, side, price, shares,
        on: new Date().toISOString().slice(0, 10),
      });
      setMsg("成交"); onDone();
    } catch (e) { setMsg("失败: " + (e as Error).message); }
  }

  return (
    <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
      <input value={code} onChange={(e) => setCode(e.target.value)} />
      <select value={side} onChange={(e) => setSide(e.target.value)}>
        <option>BUY</option><option>SELL</option>
      </select>
      <input type="number" value={price} onChange={(e) => setPrice(+e.target.value)} />
      <input type="number" value={shares} onChange={(e) => setShares(+e.target.value)} />
      <button onClick={submit}>下单</button><span>{msg}</span>
    </div>
  );
}
