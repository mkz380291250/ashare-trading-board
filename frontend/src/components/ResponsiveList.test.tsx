import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { ResponsiveList } from "./ResponsiveList";

type Row = { code: string; name: string };
const DATA: Row[] = [{ code: "600519.SH", name: "贵州茅台" }];
const columns = [
  { title: "代码", dataIndex: "code", key: "code" },
  { title: "名称", dataIndex: "name", key: "name" },
];

describe("ResponsiveList", () => {
  it("desktop renders a table (column headers visible)", () => {
    render(<ResponsiveList forceMobile={false} dataSource={DATA} columns={columns}
      rowKey="code" renderCard={(r: Row) => <div>card-{r.code}</div>} />);
    expect(screen.getAllByText("代码").length).toBeGreaterThan(0);   // 表头(含 antd 测量行)
    expect(screen.getByText("贵州茅台")).toBeInTheDocument();
  });

  it("mobile renders cards via renderCard", () => {
    render(<ResponsiveList forceMobile={true} dataSource={DATA} columns={columns}
      rowKey="code" renderCard={(r: Row) => <div>card-{r.code}</div>} />);
    expect(screen.getByText("card-600519.SH")).toBeInTheDocument();
    expect(screen.queryByText("代码")).toBeNull();
  });

  it("shows empty node when no data", () => {
    render(<ResponsiveList forceMobile={true} dataSource={[]} columns={columns}
      rowKey="code" renderCard={() => null} empty={<div>空空如也</div>} />);
    expect(screen.getByText("空空如也")).toBeInTheDocument();
  });
});

describe("ResponsiveList mobile render cap", () => {
  const many: Row[] = Array.from({ length: 100 }, (_, i) => ({
    code: `C${i}.SZ`, name: `股票${i}` }));

  it("mobile caps initial cards at 30 with a load-more button", async () => {
    render(<ResponsiveList forceMobile={true} dataSource={many} columns={columns}
      rowKey="code" renderCard={(r: Row) => <div>card-{r.code}</div>} />);
    expect(screen.getByText("card-C0.SZ")).toBeInTheDocument();
    expect(screen.getByText("card-C29.SZ")).toBeInTheDocument();
    expect(screen.queryByText("card-C30.SZ")).toBeNull();          // 第31张不渲染
    expect(screen.getByText(/加载更多/)).toBeInTheDocument();
  });

  it("load-more reveals the next batch", () => {
    render(<ResponsiveList forceMobile={true} dataSource={many} columns={columns}
      rowKey="code" renderCard={(r: Row) => <div>card-{r.code}</div>} />);
    fireEvent.click(screen.getByText(/加载更多/));
    expect(screen.getByText("card-C30.SZ")).toBeInTheDocument();
    expect(screen.getByText("card-C59.SZ")).toBeInTheDocument();
  });

  it("desktop table is not capped", () => {
    render(<ResponsiveList forceMobile={false} dataSource={many} columns={columns}
      rowKey="code" renderCard={(r: Row) => <div>card-{r.code}</div>} />);
    expect(screen.getByText("股票99")).toBeInTheDocument();
  });
});
