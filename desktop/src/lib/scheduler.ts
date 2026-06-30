import { readFile, writeFile, mkdir } from "fs/promises";
import { join } from "path";

export type Schedule = { enabled: boolean; intervalSeconds: number };

export const DEFAULT_SCHEDULE: Schedule = { enabled: false, intervalSeconds: 900 };

export function clampInterval(n: number): number {
  return Math.max(60, (isFinite(n) && Math.round(n)) || 900);   // floor 60s; 0/NaN/Infinity -> 900
}

export function parseSchedule(raw: unknown): Schedule {
  const o = raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
  const intervalSeconds = clampInterval(typeof o.intervalSeconds === "number" ? o.intervalSeconds : 900);
  return { enabled: o.enabled === true, intervalSeconds };
}

const schedulePath = (dir: string): string => join(dir, "scheduler.json");

export async function readSchedule(dir: string): Promise<Schedule> {
  try {
    return parseSchedule(JSON.parse(await readFile(schedulePath(dir), "utf8")));
  } catch {
    return { ...DEFAULT_SCHEDULE };   // missing/corrupt -> off (fresh copy; never hand out the shared singleton)
  }
}

export async function writeSchedule(dir: string, s: Schedule): Promise<Schedule> {
  const clamped: Schedule = { enabled: s.enabled === true, intervalSeconds: clampInterval(s.intervalSeconds) };
  await mkdir(dir, { recursive: true });
  await writeFile(schedulePath(dir), JSON.stringify(clamped), "utf8");
  return clamped;
}
