import { parsePending, type Pending } from "./parse";

export { parsePending };
export type { Pending };

export async function removePending(dir: string, sym: string): Promise<Pending> {
  const { readFile, writeFile, mkdir } = await import("fs/promises");
  const { join } = await import("path");
  let current: Pending = {};
  try {
    current = parsePending(JSON.parse(await readFile(join(dir, "pending.json"), "utf8")));
  } catch {
    current = {};                 // missing/corrupt -> nothing to remove
  }
  delete current[sym];
  await mkdir(dir, { recursive: true });
  await writeFile(join(dir, "pending.json"), JSON.stringify(current), "utf8");
  return current;
}
