export type EquityPoint = { ts: string; equity: number };
export type Position = { symbol?: string; qty: number; avg_price: number; stop_price: number };
export type State = { cash: number; positions: Record<string, Position>; equity_history: EquityPoint[] };
export type Trade = { ts: string; symbol: string; side: string; qty: number; price: number; fee: number };
export type Decision = { ts: string; symbol: string; action: string; reason: string; price: number; executed: boolean };
export type Snapshot = { state: State | null; trades: Trade[]; decisions: Decision[] };

export function parseTradesCsv(text: string): Trade[] {
  const lines = text.trim().split("\n").filter((l) => l.trim() !== "");
  if (lines.length <= 1) return []; // empty or header-only
  return lines.slice(1).map((line) => {
    const [ts, symbol, side, qty, price, fee] = line.split(",");
    return { ts, symbol, side, qty: Number(qty), price: Number(price), fee: Number(fee) };
  });
}

export function parseDecisions(text: string): Decision[] {
  return text
    .split("\n")
    .map((l) => l.trim())
    .filter((l) => l !== "")
    .map((l) => JSON.parse(l) as Decision);
}
