import { useState } from "react";
import { Dashboard } from "./pages/Dashboard";
import { ScreenerPool } from "./pages/ScreenerPool";

export default function App() {
  const [view, setView] = useState<"board" | "screener">("board");
  return (
    <div>
      <nav style={{ display: "flex", gap: 12, padding: 12 }}>
        <button onClick={() => setView("board")}>交易看板</button>
        <button onClick={() => setView("screener")}>选股池</button>
      </nav>
      {view === "board" ? <Dashboard /> : <ScreenerPool />}
    </div>
  );
}
