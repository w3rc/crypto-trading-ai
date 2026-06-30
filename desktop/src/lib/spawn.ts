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
