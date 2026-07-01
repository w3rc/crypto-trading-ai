// Build a child-process env that can NEVER carry a live-trading arm.
//
// We SET LIVE_TRADING_ARMED to "no" (not `delete` it): the engine's
// `load_dotenv` (engine/env.py) uses "real env wins" — `if key not in
// os.environ` — so it only loads a value from .env when the key is ABSENT.
// Deleting the key would let a .env file containing `LIVE_TRADING_ARMED=yes`
// re-arm a spawned `engine.bot`. Pinning it present-and-"no" survives that:
// the key is in the child env, so load_dotenv won't override it.
export function pinnedEnv(base: NodeJS.ProcessEnv): NodeJS.ProcessEnv {
  return { ...base, LIVE_TRADING_ARMED: "no" };
}

import { join } from "path";

// Resolve the Python interpreter for the engine, preferring a project .venv — cross-platform.
// Windows venvs live at .venv\Scripts\python.exe (fallback `python`); POSIX at .venv/bin/python
// (fallback `python3`). The old code only knew the POSIX layout, so on Windows it fell through to
// a depless global `python3` → "ModuleNotFoundError: No module named 'ccxt'".
export function resolvePython(
  repoRoot: string,
  platform: NodeJS.Platform,
  exists: (p: string) => boolean,
): string {
  if (platform === "win32") {
    const venv = join(repoRoot, ".venv", "Scripts", "python.exe");
    return exists(venv) ? venv : "python";
  }
  const venv = join(repoRoot, ".venv", "bin", "python");
  return exists(venv) ? venv : "python3";
}

// A fresh clone that skipped `pip install` crashes on the first import. Show the fix, not a traceback.
export function depHint(stderrTail: string): string {
  return /ModuleNotFoundError: No module named/.test(stderrTail)
    ? "Python dependencies not installed — run  pip install -r requirements.txt  in a .venv in the project folder."
    : stderrTail;
}
