import { useEffect, useState } from "react";
import type { Status, State } from "../../../lib/parse";
import { validSymbol } from "../../../lib/symbols";
import { pairLinks } from "../../../lib/links";

const api = (window as unknown as {
  api: {
    setSymbols: (list: string[]) => Promise<string[]>;
    openExternal: (url: string) => Promise<void>;
  };
}).api;

const LinkIcon = (): React.JSX.Element => (
  <svg className="link-ic" viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor"
       strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M14 5h5v5" /><path d="M19 5l-8 8" />
    <path d="M18 13v5a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h5" />
  </svg>
);

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

  // add/remove persist immediately (no separate Save button); applies next cycle
  const persist = async (next: string[]): Promise<void> => {
    setSymbols(next);                                     // optimistic
    try { setSymbols(await api.setSymbols(next)); setSymMsg(""); }
    catch (err) { setSymMsg(`Could not save symbols: ${String(err)}`); }
  };

  const addSymbol = (): void => {
    const s = symInput.trim().toUpperCase();
    setSymMsg("");   // clear any stale message (incl. on a no-op duplicate add)
    if (validSymbol(s) && !symbols.includes(s)) { setSymInput(""); void persist([...symbols, s]); }
    else if (!validSymbol(s)) setSymMsg(`Not a valid pair: "${symInput}" (use BASE/QUOTE, e.g. SOL/USDT)`);
  };

  const removeSymbol = (s: string): void => {
    if (hasPosition(s)) return;
    if (!window.confirm(`Remove ${s} from tracked pairs? Applies next cycle.`)) return;
    void persist(symbols.filter((x) => x !== s));
  };

  return (
    <div className="pairs-panel">
      <div className="pairs-header">
        <h2>Trading pairs</h2>
        <div className="pairs-add">
          <input className="symbol-input" placeholder="e.g. SOL/USDT" value={symInput}
                 onChange={(e) => setSymInput(e.target.value)}
                 onKeyDown={(e) => { if (e.key === "Enter") addSymbol(); }} />
          <button className="bt-run" onClick={addSymbol}>Add</button>
        </div>
      </div>
      <div className="pair-rows">
        {symbols.map((s) => (
          <div className="pair-row" key={s}>
            <span className="pair-sym">{s}</span>
            <div className="pair-links">
              {pairLinks(s).map((l) => (
                <button className="pair-link" key={l.label}
                        onClick={() => api.openExternal(l.url)}><LinkIcon />{l.label}</button>
              ))}
              <button className="symbol-x" disabled={hasPosition(s)}
                      title={hasPosition(s) ? "close the position first" : "remove"}
                      onClick={() => removeSymbol(s)}>×</button>
            </div>
          </div>
        ))}
      </div>
      <div className="settings-summary">Each pair = one more LLM call per cycle; applies next cycle.</div>
      {symMsg && <div className="bt-result bt-error">{symMsg}</div>}
    </div>
  );
}
