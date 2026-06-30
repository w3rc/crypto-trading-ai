import { test, expect } from "vitest";
import { pinnedEnv } from "./spawn";

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
