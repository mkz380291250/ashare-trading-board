type Position = { code: string; shares: number; cost: number };

export function PositionsTable({ positions }: { positions: Position[] }) {
  if (!positions.length) return <p>无持仓</p>;
  return (
    <table>
      <thead><tr><th>代码</th><th>股数</th><th>成本</th></tr></thead>
      <tbody>
        {positions.map((p) => (
          <tr key={p.code}><td>{p.code}</td><td>{p.shares}</td><td>{p.cost.toFixed(2)}</td></tr>
        ))}
      </tbody>
    </table>
  );
}
