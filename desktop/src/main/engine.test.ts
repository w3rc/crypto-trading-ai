import { vi, test, expect, beforeEach, afterEach } from "vitest";

const spawnMock = vi.fn();
vi.mock("child_process", () => ({ spawn: (...a: unknown[]) => spawnMock(...a) }));

import { runBot, executeSuggestion } from "./engine";

function fakeChild() {
  return {
    stderr: { on: () => {} },
    on: (e: string, cb: (c: number) => void) => { if (e === "close") cb(0); },
  };
}

beforeEach(() => { spawnMock.mockReset(); spawnMock.mockReturnValue(fakeChild()); });
afterEach(() => { delete process.env.LIVE_TRADING_ARMED; });

test("executeSuggestion inherits the real LIVE_TRADING_ARMED (NOT pinned to 'no')", async () => {
  process.env.LIVE_TRADING_ARMED = "yes";
  await executeSuggestion("ETH/USDT");
  const opts = spawnMock.mock.calls[0][2] as { env: NodeJS.ProcessEnv };
  expect(opts.env.LIVE_TRADING_ARMED).toBe("yes");           // armed click can place a real order
  expect(spawnMock.mock.calls[0][1]).toContain("engine.execute");
});

test("runBot pins LIVE_TRADING_ARMED to 'no' regardless of the real env", async () => {
  process.env.LIVE_TRADING_ARMED = "yes";
  await runBot();
  const opts = spawnMock.mock.calls[0][2] as { env: NodeJS.ProcessEnv };
  expect(opts.env.LIVE_TRADING_ARMED).toBe("no");            // scheduler/Run-now can never auto-fire live
});
