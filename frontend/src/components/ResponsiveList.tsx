import { useState, type ReactNode } from "react";
import { Table, Grid, Space, Empty, Button } from "antd";
import type { ColumnsType } from "antd/es/table/interface";

const MOBILE_BATCH = 30; // 移动端每批渲染的卡片数(全量渲染千行曾卡死手机)

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
  const [mobileLimit, setMobileLimit] = useState(MOBILE_BATCH);
  const keyOf = (r: T, i: number) =>
    typeof p.rowKey === "function" ? p.rowKey(r) : String((r as Record<string, unknown>)[p.rowKey] ?? i);

  if (!p.dataSource.length) return <>{p.empty ?? <Empty description="暂无数据" />}</>;

  if (isMobile) {
    const visible = p.dataSource.slice(0, mobileLimit);
    return (
      <Space direction="vertical" size="small" style={{ width: "100%" }}>
        {visible.map((r, i) => (
          <div key={keyOf(r, i)} onClick={() => p.onRowClick?.(r)}
            style={p.onRowClick ? { cursor: "pointer" } : undefined}>
            {p.renderCard(r)}
          </div>
        ))}
        {p.dataSource.length > mobileLimit && (
          <Button block onClick={() => setMobileLimit(mobileLimit + MOBILE_BATCH)}>
            加载更多({mobileLimit}/{p.dataSource.length})
          </Button>
        )}
      </Space>
    );
  }
  return (
    <Table<T> rowKey={p.rowKey} size="small" pagination={false}
      dataSource={p.dataSource} columns={p.columns} scroll={{ x: "max-content" }}
      onRow={(r) => ({ onClick: () => p.onRowClick?.(r),
        style: p.onRowClick ? { cursor: "pointer" } : undefined })} />
  );
}
