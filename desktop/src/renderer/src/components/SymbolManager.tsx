import { useEffect, useState } from "react";
import type { Status, State } from "../../../lib/parse";
import { validSymbol } from "../../../lib/symbols";

const api = (window as unknown as {
  api: { setSymbols: (list: string[]) => Promise<string[]> };
}).api;

export default function SymbolManager({ status, state }: { status: Status | null; state: State | null }): React.JSX.Element {
  const [symbols, setSymbols] = useState<string[]>([]);
  const [symInput, setSymInput] = useState("");
  const [seeded, setSeeded] = useState(false);
  const [symMsg, setSymMsg] = useState("");

  useEffect(() => {
    if (!seeded && status?.symbols) { setSymbols(status.symbols); setSeeded(true); }
  }, [status, seeded]);

  // unknown state (null) -> treat as "may hold a position" so the orphan guard never fails open
  const hasPosition = (sym: string): boolean => state == null || (state.positions?.[sym]?.qty ?? 0) !== 0;

  const addSymbol = (): void => {
    const s = symInput.trim().toUpperCase();
    setSymMsg("");   // clear any stale message (incl. on a no-op duplicate add)
    if (validSymbol(s) && !symbols.includes(s)) { setSymbols([...symbols, s]); setSymInput(""); }
    else if (!validSymbol(s)) setSymMsg(`Not a valid pair: "${symInput}" (use BASE/QUOTE, e.g. SOL/USDT)`);
  };

  const removeSymbol = (s: string): void => {
    if (!hasPosition(s)) setSymbols(symbols.filter((x) => x !== s));
  };

  const saveSymbols = async (): Promise<void> => {
    try {
      setSymbols(await api.setSymbols(symbols));
      setSymMsg("");
    } catch (err) {
      setSymMsg(`Could not save symbols: ${String(err)}`);
    }
  };

  return (
    <div className="settings-form">
      <div className="symbol-chips">
        {symbols.map((s) => (
          <span className="symbol-chip" key={s}>
            {s}
            <button className="symbol-x" disabled={hasPosition(s)}
                    title={hasPosition(s) ? "close the position first" : "remove"}
                    onClick={() => removeSymbol(s)}>×</button>
          </span>
        ))}
      </div>
      <div className="settings-actions">
        <input className="symbol-input" placeholder="e.g. SOL/USDT" value={symInput}
               onChange={(e) => setSymInput(e.target.value)}
               onKeyDown={(e) => { if (e.key === "Enter") addSymbol(); }} />
        <button className="bt-run" onClick={addSymbol}>Add</button>
        <button className="bt-run" disabled={!symbols.length} onClick={saveSymbols}>Save symbols</button>
      </div>
      <div className="settings-summary">Each pair = one more LLM call per cycle; applies next cycle.</div>
      {symMsg && <div className="bt-result bt-error">{symMsg}</div>}
    </div>
  );
}
