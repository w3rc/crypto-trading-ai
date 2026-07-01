import { spawn } from "child_process";
import { existsSync } from "fs";
import { join, resolve } from "path";
import { dataDir } from "../lib/snapshot";
import { buildBacktestArgs, isIsoDate, BacktestOpts } from "../lib/backtest";
import { pinnedEnv } from "../lib/spawn";

export type RunResult = { ok: boolean; code: number | null; stderrTail: string };

function pythonPath(repoRoot: string): string {
  const venv = join(repoRoot, ".venv", "bin", "python");
  return existsSync(venv) ? venv : "python3";
}

// ponytail: dev-local repoRoot/venv resolution; packaged-app python bundling (deferred C1) is out of scope.
function runEngine(args: string[], env: NodeJS.ProcessEnv): Promise<RunResult> {
  const repoRoot = resolve(dataDir(), "..");
  return new Promise((resolveP) => {
    const child = spawn(pythonPath(repoRoot), args, { cwd: repoRoot, env });
    let stderr = "";
    child.stderr.on("data", (d) => { stderr = (stderr + d.toString()).slice(-2048); });
    child.on("error", (e) => resolveP({ ok: false, code: null, stderrTail: e.message }));
    child.on("close", (code) => resolveP({ ok: code === 0, code, stderrTail: stderr.trim() }));
  });
}

// Pinned: the scheduler, Run-now, and backtest can NEVER carry a live-trading arm.
function spawnEngine(args: string[]): Promise<RunResult> {
  return runEngine(args, pinnedEnv(process.env));
}

// The ONE un-pinned engine spawn. Manual Execute inherits the operator's real
// LIVE_TRADING_ARMED so a confirmed click can place a real order in live mode.
// Reachable ONLY from the execute-suggestion IPC. The engine still enforces the
// two-switch (mode:live + LIVE_TRADING_ARMED=yes + no data/HALT); an unarmed app fails closed.
function spawnEngineArmed(args: string[]): Promise<RunResult> {
  return runEngine(args, process.env);
}

export function runBacktest(opts: BacktestOpts): Promise<RunResult> {
  if (!isIsoDate(opts.since)) {
    return Promise.resolve({ ok: false, code: null, stderrTail: `invalid since date: ${opts.since} (expected YYYY-MM-DD)` });
  }
  return spawnEngine(buildBacktestArgs(opts));
}

export function runBot(): Promise<RunResult> {
  return spawnEngine(["-m", "engine.bot"]);
}

export function runSentiment(): Promise<RunResult> {
  return spawnEngine(["-m", "engine.analyze_sentiment"]);   // sentiment-only; no trading, pinned
}

export function executeSuggestion(symbol: string): Promise<RunResult> {
  return spawnEngineArmed(["-m", "engine.execute", symbol]);
}
