import { useEffect, useState } from "react";
import type { Status, BacktestPoint, BacktestRun } from "../../../lib/parse";
import BacktestForm from "./BacktestForm";
import BacktestChart from "./BacktestChart";
import BacktestHistory from "./BacktestHistory";

const api = (window as unknown as {
  api: { getBacktestRun: (id: string) => Promise<BacktestPoint[]> };
}).api;

export default function BacktestPanel({ status, latest, history }: {
  status: Status | null; latest: BacktestPoint[]; history: BacktestRun[];
}): React.JSX.Element {
  const [sel, setSel] = useState<{ id: string; points: BacktestPoint[] } | null>(null);
  const [msg, setMsg] = useState("");

  // when a new run is appended, drop any manual selection and follow the latest result
  const newestTs = history.length ? history[history.length - 1].ts : "";
  useEffect(() => { setSel(null); setMsg(""); }, [newestTs]);

  const selectRun = async (r: BacktestRun): Promise<void> => {
    if (!r.id) { setSel(null); setMsg("This run predates saved curves — re-run it to view its chart."); return; }
    try {
      const points = await api.getBacktestRun(r.id);
      if (points.length) { setSel({ id: r.id, points }); setMsg(""); }
      else { setSel(null); setMsg("That run's saved curve is missing — re-run it to view."); }
    } catch {
      setSel(null); setMsg("Couldn't load that run's chart.");
    }
  };

  return (
    <>
      <BacktestForm status={status} />
      <BacktestChart points={sel ? sel.points : latest} />
      {msg && <div className="bt-result bt-error">{msg}</div>}
      <div className="bt-history-wrap">
        <h2>Past runs{sel ? " · viewing selected" : ""}</h2>
        <BacktestHistory runs={history} selectedId={sel?.id} onSelect={selectRun} />
      </div>
    </>
  );
}
