import { readFile, rm } from "fs/promises";
import { join, resolve } from "path";
import { parseTradesCsv, parseDecisions, parseSentiment, parseBacktestCsv, parseBacktestHistory, parsePending, Snapshot, State, SentimentSnapshot, Status, BacktestPoint, BacktestRun, Pending } from "./parse";

export function dataDir(): string {
  return process.env.DATA_DIR || resolve(process.cwd(), "..", "data");
}

async function readOr<T>(path: string, fallback: T, transform: (s: string) => T): Promise<T> {
  try {
    return transform(await readFile(path, "utf8"));
  } catch {
    return fallback; // missing/unreadable file -> empty value, never throw
  }
}

export async function readSnapshot(dir: string): Promise<Snapshot> {
  const state = await readOr<State | null>(join(dir, "state.json"), null, (s) => JSON.parse(s) as State);
  const trades = await readOr(join(dir, "trades.csv"), [], parseTradesCsv);
  const decisions = await readOr(join(dir, "decisions.jsonl"), [], parseDecisions);
  const sentiment = await readOr<SentimentSnapshot | null>(join(dir, "sentiment.json"), null, parseSentiment);
  const status = await readOr<Status | null>(join(dir, "status.json"), null, (s) => JSON.parse(s) as Status);
  const backtest = await readOr<BacktestPoint[]>(join(dir, "backtest_equity.csv"), [], parseBacktestCsv);
  const pending = await readOr<Pending>(join(dir, "pending.json"), {}, (s) => parsePending(JSON.parse(s)));
  const backtestHistory = await readOr<BacktestRun[]>(join(dir, "backtest_history.jsonl"), [], parseBacktestHistory);
  return { state, trades, decisions, sentiment, status, backtest, pending, backtestHistory };
}

// Load one past run's equity curve on demand (clicking a row in the history table).
export async function readBacktestRun(dir: string, id: string): Promise<BacktestPoint[]> {
  if (!/^[0-9T]+$/.test(id)) return [];   // guard: id is engine-generated; reject anything path-like
  return readOr<BacktestPoint[]>(join(dir, "backtest_runs", `${id}.csv`), [], parseBacktestCsv);
}

// Wipe the run log and all saved curves (the "Clear history" button).
export async function clearBacktestHistory(dir: string): Promise<void> {
  await rm(join(dir, "backtest_history.jsonl"), { force: true });
  await rm(join(dir, "backtest_runs"), { recursive: true, force: true });
}
