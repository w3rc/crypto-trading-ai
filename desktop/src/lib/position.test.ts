import { test, expect } from "vitest";
import { positionSide } from "./position";

test("positionSide by sign", () => {
  expect(positionSide(0.5)).toBe("Long");
  expect(positionSide(-0.5)).toBe("Short");
});
