export type BacktestOpts = { since: string; until?: string; strategy?: string };

export function isIsoDate(s: string): boolean {
  return /^\d{4}-\d{2}-\d{2}$/.test(s);
}

export function buildBacktestArgs(opts: BacktestOpts): string[] {
  return [
    "-m", "engine.backtest",
    "--since", opts.since,
    ...(opts.until ? ["--until", opts.until] : []),
    ...(opts.strategy ? ["--strategy", opts.strategy] : []),
    "--out", "data/backtest_equity.csv",
  ];
}
