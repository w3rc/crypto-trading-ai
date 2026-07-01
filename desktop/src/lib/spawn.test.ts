import { test, expect, describe } from "vitest";
import { join } from "path";
import { pinnedEnv, resolvePython, depHint } from "./spawn";

test("pinnedEnv forces LIVE_TRADING_ARMED to 'no' even if the base says yes", () => {
  const base = { LIVE_TRADING_ARMED: "yes", FOO: "bar" };
  const env = pinnedEnv(base);
  expect(env.LIVE_TRADING_ARMED).toBe("no");    // present-and-off, NOT absent — survives the engine's .env loader
  expect(env.FOO).toBe("bar");                  // other vars preserved
  expect(base.LIVE_TRADING_ARMED).toBe("yes");  // input not mutated
});

test("pinnedEnv sets 'no' when the base lacks the var", () => {
  expect(pinnedEnv({}).LIVE_TRADING_ARMED).toBe("no");
});

const ROOT = "/repo";

describe("resolvePython", () => {
  test("windows uses .venv\\Scripts\\python.exe when present", () => {
    const venv = join(ROOT, ".venv", "Scripts", "python.exe");
    expect(resolvePython(ROOT, "win32", (p) => p === venv)).toBe(venv);
  });

  test("windows falls back to `python` when no venv", () => {
    expect(resolvePython(ROOT, "win32", () => false)).toBe("python");
  });

  test("windows ignores a POSIX-layout venv (the original bug)", () => {
    const posixVenv = join(ROOT, ".venv", "bin", "python");
    expect(resolvePython(ROOT, "win32", (p) => p === posixVenv)).toBe("python");
  });

  test("posix uses .venv/bin/python when present", () => {
    const venv = join(ROOT, ".venv", "bin", "python");
    expect(resolvePython(ROOT, "linux", (p) => p === venv)).toBe(venv);
  });

  test("posix falls back to `python3` when no venv", () => {
    expect(resolvePython(ROOT, "darwin", () => false)).toBe("python3");
  });
});

describe("depHint", () => {
  test("rewrites a missing-module crash into an actionable hint", () => {
    const out = depHint("Traceback…\nModuleNotFoundError: No module named 'ccxt'");
    expect(out).toMatch(/pip install -r requirements\.txt/);
  });

  test("passes other errors through unchanged", () => {
    expect(depHint("some other stderr")).toBe("some other stderr");
  });
});
