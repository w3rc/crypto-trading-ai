import { test, expect } from "vitest";
import { writeControl } from "./control";
import { mkdtempSync, readFileSync, existsSync } from "fs";
import { tmpdir } from "os";
import { join } from "path";

test("writeControl writes {mode} for valid modes", async () => {
  const d = mkdtempSync(join(tmpdir(), "ctrl-"));
  await writeControl(d, "shadow");
  expect(JSON.parse(readFileSync(join(d, "control.json"), "utf8"))).toEqual({ mode: "shadow" });
});

test("writeControl rejects an invalid mode and writes nothing", async () => {
  const d = mkdtempSync(join(tmpdir(), "ctrl-"));
  await expect(writeControl(d, "bogus")).rejects.toThrow();
  expect(existsSync(join(d, "control.json"))).toBe(false);
});
