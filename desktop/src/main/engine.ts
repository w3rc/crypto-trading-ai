import { spawn } from "child_process";
import { existsSync } from "fs";
import { join, resolve } from "path";
import { dataDir } from "../lib/snapshot";
import { buildBacktestArgs, isIsoDate, BacktestOpts } from "../lib/backtest";

export type RunResult = { ok: boolean; code: number | null; stderrTail: string };

function pythonPath(repoRoot: string): string {
  const venv = join(repoRoot, ".venv", "bin", "python");
  return existsSync(venv) ? venv : "python3";
}

// ponytail: dev-local repoRoot/venv resolution; packaged-app python bundling (deferred C1) is out of scope.
export function runBacktest(opts: BacktestOpts): Promise<RunResult> {
  if (!isIsoDate(opts.since)) {
    return Promise.resolve({ ok: false, code: null, stderrTail: `invalid since date: ${opts.since} (expected YYYY-MM-DD)` });
  }
  const repoRoot = resolve(dataDir(), "..");
  const env = { ...process.env };
  delete env.LIVE_TRADING_ARMED;          // a dashboard-launched process can never arm live
  return new Promise((resolveP) => {
    const child = spawn(pythonPath(repoRoot), buildBacktestArgs(opts), { cwd: repoRoot, env });
    let stderr = "";
    child.stderr.on("data", (d) => { stderr = (stderr + d.toString()).slice(-2048); });
    child.on("error", (e) => resolveP({ ok: false, code: null, stderrTail: e.message }));
    child.on("close", (code) => resolveP({ ok: code === 0, code, stderrTail: stderr.trim() }));
  });
}
