import { test, expect } from "vitest";
import { sentimentLabel, gaugePct } from "./sentiment";

test("sentimentLabel bands", () => {
  expect(sentimentLabel(-0.8)).toBe("Extreme Fear");
  expect(sentimentLabel(-0.5)).toBe("Extreme Fear");   // boundary: <= -0.5
  expect(sentimentLabel(-0.3)).toBe("Fear");
  expect(sentimentLabel(0)).toBe("Neutral");
  expect(sentimentLabel(0.15)).toBe("Neutral");        // boundary: <= 0.15
  expect(sentimentLabel(0.3)).toBe("Greed");
  expect(sentimentLabel(0.8)).toBe("Extreme Greed");
});

test("gaugePct maps and clamps", () => {
  expect(gaugePct(-1)).toBe(0);
  expect(gaugePct(0)).toBe(50);
  expect(gaugePct(1)).toBe(100);
  expect(gaugePct(-5)).toBe(0);    // clamped
  expect(gaugePct(5)).toBe(100);   // clamped
});
