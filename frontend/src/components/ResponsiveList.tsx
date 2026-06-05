import { type ReactNode } from "react";
import { Table, Grid, Space, Empty } from "antd";
import type { ColumnsType } from "antd/es/table/interface";

type Props<T> = {
  dataSource: T[];
  columns: ColumnsType<T>;
  rowKey: string | ((r: T) => string);
  renderCard: (record: T) => ReactNode;
  onRowClick?: (record: T) => void;
  empty?: ReactNode;
  forceMobile?: boolean;
};

export function ResponsiveList<T extends object>(p: Props<T>) {
  const screens = Grid.useBreakpoint();
  const isMobile = p.forceMobile ?? !screens.md;
  const keyOf = (r: T, i: number) =>
    typeof p.rowKey === "function" ? p.rowKey(r) : String((r as Record<string, unknown>)[p.rowKey] ?? i);

  if (!p.dataSource.length) return <>{p.empty ?? <Empty description="暂无数据" />}</>;

  if (isMobile) {
    return (
      <Space direction="vertical" size="small" style={{ width: "100%" }}>
        {p.dataSource.map((r, i) => (
          <div key={keyOf(r, i)} onClick={() => p.onRowClick?.(r)}
            style={p.onRowClick ? { cursor: "pointer" } : undefined}>
            {p.renderCard(r)}
          </div>
        ))}
      </Space>
    );
  }
  return (
    <Table<T> rowKey={p.rowKey} size="small" pagination={false}
      dataSource={p.dataSource} columns={p.columns}
      onRow={(r) => ({ onClick: () => p.onRowClick?.(r),
        style: p.onRowClick ? { cursor: "pointer" } : undefined })} />
  );
}
