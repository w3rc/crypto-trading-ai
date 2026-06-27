export function sentimentLabel(score: number): string {
  if (score <= -0.5) return "Extreme Fear";
  if (score < -0.15) return "Fear";
  if (score <= 0.15) return "Neutral";
  if (score < 0.5) return "Greed";
  return "Extreme Greed";
}

export function gaugePct(score: number): number {
  return Math.max(0, Math.min(100, ((score + 1) / 2) * 100));
}
