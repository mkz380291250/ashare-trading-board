import { useEffect, useState } from "react";
import { apiGet } from "./api/client";

export default function App() {
  const [status, setStatus] = useState("checking...");
  useEffect(() => {
    apiGet<{ status: string }>("/api/health")
      .then((d) => setStatus(d.status))
      .catch((e) => setStatus("error: " + e.message));
  }, []);
  return <div style={{ padding: 24 }}><h1>A-Share Board</h1><p>backend: {status}</p></div>;
}
