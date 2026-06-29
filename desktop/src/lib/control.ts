import { writeFile, mkdir } from "fs/promises";
import { join } from "path";

const VALID = new Set(["paper", "shadow", "live"]);

export async function writeControl(dir: string, mode: string): Promise<void> {
  if (!VALID.has(mode)) throw new Error(`invalid mode: ${mode}`);
  await mkdir(dir, { recursive: true });
  await writeFile(join(dir, "control.json"), JSON.stringify({ mode }), "utf8");
}
