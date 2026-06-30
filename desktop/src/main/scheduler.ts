import { runBot } from "./engine";
import { Schedule } from "../lib/scheduler";

let handle: NodeJS.Timeout | null = null;
let inFlight = false;

export function applySchedule(s: Schedule): void {
  if (handle) { clearInterval(handle); handle = null; }
  if (!s.enabled) return;
  handle = setInterval(() => {
    if (inFlight) return;                          // skip pile-up; bot.lock is the real guard
    inFlight = true;
    runBot().catch(() => {}).finally(() => { inFlight = false; });   // forever-repeating tick: never let it emit an unhandledRejection
  }, s.intervalSeconds * 1000);
}
