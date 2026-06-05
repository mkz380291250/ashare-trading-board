import { useState } from "react";
import { Card, InputNumber, Button, Space, message } from "antd";
import { apiPost } from "../api/client";

export function ManualTrade({ code, onDone }: { code: string; onDone: () => void }) {
  const [price, setPrice] = useState(0);
  const [shares, setShares] = useState(100);
  const today = new Date().toISOString().slice(0, 10);
  async function trade(side: "BUY" | "SELL") {
    try {
      await apiPost("/api/trade", { account_id: 1, code, side, price, shares, on: today });
      message.success(`${side} ${code} 成功`);
      onDone();
    } catch { message.error("下单失败"); }
  }
  return (
    <Card size="small" title={`手动交易 ${code}`} style={{ marginTop: 16 }}>
      <Space wrap>
        <InputNumber addonBefore="价" value={price} onChange={(v) => setPrice(v ?? 0)} />
        <InputNumber addonBefore="股数" value={shares} onChange={(v) => setShares(v ?? 0)} />
        <Button danger autoInsertSpace={false} onClick={() => trade("BUY")}>买入</Button>
        <Button autoInsertSpace={false} onClick={() => trade("SELL")}>卖出</Button>
      </Space>
    </Card>
  );
}
