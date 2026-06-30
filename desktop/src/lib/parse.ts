export type EquityPoint = { ts: string; equity: number };
export type Position = { symbol?: string; qty: number; avg_price: number; stop_price: number;
                         leverage?: number; liq_price?: number };
export type State = { cash: number; positions: Record<string, Position>; equity_history: EquityPoint[] };
export type Trade = { ts: string; symbol: string; side: string; qty: number; price: number; fee: number };
export type Decision = { ts: string; symbol: string; action: string; reason: string; price: number; executed: boolean };
export type Pending = Record<string, { ts: string; action: string; size: number; reason: string; price: number }>;
export type SourceScores = { fear_greed: number | null; cryptopanic: number | null;
                             reddit: number | null; x_twitter: number | null };
export type SymbolSentiment = { blended: number; sources: SourceScores };
export type SentimentSnapshot = { ts: string; strategy: string;
                                  symbols: Record<string, SymbolSentiment> };
export type RiskStatus = { allow_short: boolean; leverage: number; maintenance_margin_pct: number;
                           funding_rate: number; funding_interval_hours: number;
                           max_position_pct: number; stop_loss_pct: number };
export type FundingStatus = { accrued: number; last_funding_ts: string | null };
export type Status = { ts: string; strategy: string; exchange: string; mode?: string; halted?: boolean; armed?: boolean;
                       auto_execute?: boolean;
                       interval_seconds?: number; symbols?: string[]; risk: RiskStatus; funding: FundingStatus };
export type BacktestPoint = { ts: string; equity: number; buyHold: number };
export type Snapshot = { state: State | null; trades: Trade[]; decisions: Decision[];
                         sentiment: SentimentSnapshot | null;
                         status: Status | null; backtest: BacktestPoint[]; pending: Pending };

export function parseTradesCsv(text: string): Trade[] {
  const lines = text.trim().split("\n").filter((l) => l.trim() !== "");
  if (lines.length <= 1) return []; // empty or header-only
  return lines.slice(1).map((line) => {
    const [ts, symbol, side, qty, price, fee] = line.split(",");
    return { ts, symbol, side, qty: Number(qty), price: Number(price), fee: Number(fee) };
  });
}

export function parseDecisions(text: string): Decision[] {
  const out: Decision[] = [];
  for (const line of text.split("\n")) {
    const t = line.trim();
    if (t === "") continue;
    try {
      out.push(JSON.parse(t) as Decision);
    } catch {
      // skip a torn/partial line (e.g. process killed mid-append) — keep the rest
    }
  }
  return out;
}

export function parseSentiment(text: string): SentimentSnapshot {
  return JSON.parse(text) as SentimentSnapshot;
}

export function parsePending(raw: unknown): Pending {
  const out: Pending = {};
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return out;
  for (const [sym, v] of Object.entries(raw as Record<string, unknown>)) {
    if (!v || typeof v !== "object") continue;
    const e = v as Record<string, unknown>;
    if (typeof e.action !== "string") continue;
    out[sym] = {
      ts: typeof e.ts === "string" ? e.ts : "",
      action: e.action,
      size: Number(e.size) || 0,
      reason: typeof e.reason === "string" ? e.reason : "",
      price: Number(e.price) || 0,
    };
  }
  return out;
}

export function parseBacktestCsv(text: string): BacktestPoint[] {
  const lines = text.trim().split("\n").filter((l) => l.trim() !== "");
  if (lines.length <= 1) return []; // empty or header-only
  return lines.slice(1).map((line) => {
    const [ts, equity, buyHold] = line.split(",");
    return { ts, equity: Number(equity), buyHold: Number(buyHold) };
  });
}
