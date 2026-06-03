import { useEffect, useState } from "react";
import { Row, Col, Card, Statistic, Descriptions, Empty } from "antd";
import { apiGet } from "../api/client";
import { LayerBars } from "../components/LayerBars";

type Run = {
  id: number; created_at: string; signal: string; start: string; end: string;
  params: Record<string, unknown>;
  strategy_metrics: { annualized_return?: number; information_ratio?: number;
    max_drawdown?: number; cum_return?: number };
  factor_report: { ic_mean?: number; rank_ic_mean?: number; layer_returns?: number[] };
};

export function BacktestPage() {
  const [run, setRun] = useState<Run | null>(null);
  const [missing, setMissing] = useState(false);
  useEffect(() => {
    apiGet<Run>("/api/backtest").then(setRun).catch(() => setMissing(true));
  }, []);
  if (missing) return <Empty description="暂无回测结果,先跑 scripts/run_backtest.py" />;
  if (!run) return null;
  const m = run.strategy_metrics, f = run.factor_report;
  const pct = (v?: number) => v == null ? "-" : `${(v * 100).toFixed(2)}%`;
  return (
    <div style={{ display: "grid", gap: 16 }}>
      <Row gutter={16}>
        <Col span={6}><Card><Statistic title="年化收益" value={pct(m.annualized_return)} /></Card></Col>
        <Col span={6}><Card><Statistic title="信息比率(vs沪深300)" value={m.information_ratio ?? "-"}
          precision={2} /></Card></Col>
        <Col span={6}><Card><Statistic title="最大回撤" value={pct(m.max_drawdown)} /></Card></Col>
        <Col span={6}><Card><Statistic title="累计收益" value={pct(m.cum_return)} /></Card></Col>
      </Row>
      <Card title="因子 IC">
        <Row gutter={16}>
          <Col span={8}><Statistic title="IC 均值" value={f.ic_mean ?? "-"} precision={4} /></Col>
          <Col span={8}><Statistic title="RankIC 均值" value={f.rank_ic_mean ?? "-"} precision={4} /></Col>
        </Row>
        <div style={{ marginTop: 16 }}>
          {f.layer_returns?.length
            ? <LayerBars layers={f.layer_returns} />
            : <Empty description="无分层数据" />}
        </div>
      </Card>
      <Descriptions title="回测元信息" bordered size="small" column={2}>
        <Descriptions.Item label="信号">{run.signal}</Descriptions.Item>
        <Descriptions.Item label="区间">{run.start} ~ {run.end}</Descriptions.Item>
        <Descriptions.Item label="参数">{JSON.stringify(run.params)}</Descriptions.Item>
        <Descriptions.Item label="生成于">{run.created_at}</Descriptions.Item>
      </Descriptions>
    </div>
  );
}
