// Local time-of-day for a decision; prefixed with the date only when it's not "today"
// (so a multi-day decision log doesn't look scrambled when every row shows just HH:MM:SS).
export function formatDecisionTime(ts: string, nowMs: number): string {
  const d = new Date(ts);
  const time = d.toLocaleTimeString();
  if (d.toDateString() === new Date(nowMs).toDateString()) return time;
  return `${d.toLocaleDateString(undefined, { month: "short", day: "numeric" })}, ${time}`;
}
