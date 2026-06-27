import { readFile } from "fs/promises";
import { join, resolve } from "path";
import { parseTradesCsv, parseDecisions, parseSentiment, Snapshot, State, SentimentSnapshot } from "./parse";

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
  return { state, trades, decisions, sentiment };
}
