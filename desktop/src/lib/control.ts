import { writeFile, mkdir, readFile } from "fs/promises";
import { join } from "path";

const VALID = new Set(["paper", "shadow", "live"]);
const VALID_STRATEGIES = new Set([
  "hybrid", "indicator_rule", "sentiment_rule",
  "ma_cross", "macd_cross", "rsi_reversion", "bollinger",
]);

async function _merge(dir: string, patch: Record<string, unknown>): Promise<void> {
  await mkdir(dir, { recursive: true });
  let current: Record<string, unknown> = {};
  try {
    const parsed = JSON.parse(await readFile(join(dir, "control.json"), "utf8"));
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) current = parsed;
  } catch {
    current = {};                 // missing/corrupt -> start clean
  }
  await writeFile(join(dir, "control.json"), JSON.stringify({ ...current, ...patch }), "utf8");
}

export async function writeControl(dir: string, mode: string): Promise<void> {
  if (!VALID.has(mode)) throw new Error(`invalid mode: ${mode}`);
  await _merge(dir, { mode });
}

export async function writeAutoExecute(dir: string, on: boolean): Promise<void> {
  await _merge(dir, { auto_execute: on });
}

export async function writeStrategy(dir: string, name: string): Promise<void> {
  if (!VALID_STRATEGIES.has(name)) throw new Error(`invalid strategy: ${name}`);
  await _merge(dir, { strategy: name });
}
