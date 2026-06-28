export function positionSide(qty: number): "Long" | "Short" {
  return qty < 0 ? "Short" : "Long";
}

export function leverageLabel(lev?: number): string {
  return `${lev ?? 1}×`;
}

export function liqLabel(liq?: number): string {
  return liq && liq > 0 ? `$${liq.toFixed(2)}` : "—";
}
