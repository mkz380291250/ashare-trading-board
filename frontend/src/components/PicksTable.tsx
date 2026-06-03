type Pick = {
  code: string; theme: string; first_selected_on: string; entry_close: number;
  ret_t1: number | null; ret_t3: number | null;
  ret_t5: number | null; ret_t10: number | null;
};

function pct(v: number | null) {
  return v == null ? "-" : (v * 100).toFixed(1) + "%";
}

export function PicksTable({ picks }: { picks: Pick[] }) {
  if (!picks.length) return <p>观察池为空</p>;
  return (
    <table>
      <thead><tr>
        <th>代码</th><th>题材</th><th>入选日</th><th>入选价</th>
        <th>T+1</th><th>T+3</th><th>T+5</th><th>T+10</th>
      </tr></thead>
      <tbody>
        {picks.map((p) => (
          <tr key={p.code + p.first_selected_on}>
            <td>{p.code}</td><td>{p.theme}</td><td>{p.first_selected_on}</td>
            <td>{p.entry_close.toFixed(2)}</td>
            <td>{pct(p.ret_t1)}</td><td>{pct(p.ret_t3)}</td>
            <td>{pct(p.ret_t5)}</td><td>{pct(p.ret_t10)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
