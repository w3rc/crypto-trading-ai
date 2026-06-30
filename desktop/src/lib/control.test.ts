import { test, expect } from "vitest";
import { writeControl, writeAutoExecute } from "./control";
import { mkdtempSync, readFileSync, existsSync } from "fs";
import { tmpdir } from "os";
import { join } from "path";

test("writeControl writes {mode} for valid modes", async () => {
  const d = mkdtempSync(join(tmpdir(), "ctrl-"));
  await writeControl(d, "shadow");
  expect(JSON.parse(readFileSync(join(d, "control.json"), "utf8"))).toEqual({ mode: "shadow" });
});

test("writeControl writes {mode: 'live'} for the live mode", async () => {
  const d = mkdtempSync(join(tmpdir(), "ctrl-"));
  await writeControl(d, "live");
  expect(JSON.parse(readFileSync(join(d, "control.json"), "utf8"))).toEqual({ mode: "live" });
});

test("writeControl rejects an invalid mode and writes nothing", async () => {
  const d = mkdtempSync(join(tmpdir(), "ctrl-"));
  await expect(writeControl(d, "bogus")).rejects.toThrow();
  expect(existsSync(join(d, "control.json"))).toBe(false);
});

test("writeControl preserves an existing auto_execute", async () => {
  const d = mkdtempSync(join(tmpdir(), "ctrl-"));
  await writeAutoExecute(d, true);
  await writeControl(d, "live");
  expect(JSON.parse(readFileSync(join(d, "control.json"), "utf8"))).toEqual({ auto_execute: true, mode: "live" });
});

test("writeAutoExecute preserves an existing mode", async () => {
  const d = mkdtempSync(join(tmpdir(), "ctrl-"));
  await writeControl(d, "shadow");
  await writeAutoExecute(d, true);
  expect(JSON.parse(readFileSync(join(d, "control.json"), "utf8"))).toEqual({ mode: "shadow", auto_execute: true });
});

test("writeAutoExecute false round-trips", async () => {
  const d = mkdtempSync(join(tmpdir(), "ctrl-"));
  await writeAutoExecute(d, false);
  expect(JSON.parse(readFileSync(join(d, "control.json"), "utf8"))).toEqual({ auto_execute: false });
});
