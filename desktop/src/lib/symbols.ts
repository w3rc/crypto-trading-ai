import { writeFile, mkdir } from "fs/promises";
import { join } from "path";

const PAIR = /^[A-Z0-9]+\/[A-Z0-9]+$/;

export function validSymbol(s: string): boolean {
  return PAIR.test(s);
}

export function parseSymbols(raw: unknown): string[] {
  const list = Array.isArray(raw) ? raw : [];
  const out: string[] = [];
  for (const s of list) {
    if (typeof s !== "string") continue;
    const sym = s.trim().toUpperCase();
    if (validSymbol(sym) && !out.includes(sym)) out.push(sym);
  }
  return out;
}

export async function writeSymbols(dir: string, symbols: string[]): Promise<string[]> {
  const clean = parseSymbols(symbols);
  if (!clean.length) throw new Error("at least one symbol required");
  await mkdir(dir, { recursive: true });
  await writeFile(join(dir, "symbols.json"), JSON.stringify(clean), "utf8");
  return clean;
}
