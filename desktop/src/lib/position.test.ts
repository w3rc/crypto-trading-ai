import { test, expect } from "vitest";
import { positionSide, leverageLabel, liqLabel } from "./position";

test("positionSide by sign", () => {
  expect(positionSide(0.5)).toBe("Long");
  expect(positionSide(-0.5)).toBe("Short");
});

test("leverageLabel formats with x suffix", () => {
  expect(leverageLabel(5)).toBe("5×");
  expect(leverageLabel(1)).toBe("1×");
  expect(leverageLabel(undefined)).toBe("1×");
});

test("liqLabel shows price or dash", () => {
  expect(liqLabel(123.456)).toBe("$123.46");
  expect(liqLabel(0)).toBe("—");
  expect(liqLabel(undefined)).toBe("—");
});
