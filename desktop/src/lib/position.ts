export function positionSide(qty: number): "Long" | "Short" {
  return qty < 0 ? "Short" : "Long";
}
