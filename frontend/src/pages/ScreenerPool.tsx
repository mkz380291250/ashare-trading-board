import { useEffect, useState } from "react";
import { Card } from "antd";
import { apiGet } from "../api/client";
import { PicksTable } from "../components/PicksTable";

type Pick = {
  code: string; theme: string; first_selected_on: string; entry_close: number;
  ret_t1: number | null; ret_t3: number | null;
  ret_t5: number | null; ret_t10: number | null;
};

export function ScreenerPool() {
  const [picks, setPicks] = useState<Pick[]>([]);
  useEffect(() => {
    apiGet<Pick[]>("/api/screener/picks").then(setPicks).catch(() => {});
  }, []);
  return <Card title="题材选股池(T+1/3/5/10 追踪)"><PicksTable picks={picks} /></Card>;
}
