// Claude Code's Windows Credential Manager reader and writer, restated.
//
// Run with Bun, because Bun.secrets is the API Claude Code itself calls. The
// three functions below follow the 2.1.322 binary statement for statement
// (its minified names were Ye, fe and ze); the only liberty taken is naming
// things. They exist so a Windows runner can answer two questions without a
// real login:
//
//   does Shambles read what the vendor's code writes, and
//   does the vendor's code read what Shambles writes?
//
// Usage:
//   bun vendor_credman.mjs set    <service> <name> <file>   store the file's text
//   bun vendor_credman.mjs get    <service> <name> <file>   write what is stored
//   bun vendor_credman.mjs delete <service> <name>
//
// `get` exits 3 when nothing is stored.
import { readFileSync, writeFileSync } from "node:fs";

const CHUNK = 2400;
const MAX_CHUNKS = 256;
const secrets = globalThis.Bun?.secrets;
if (!secrets) {
  console.error("Bun.secrets is not available in this runtime");
  process.exit(2);
}

const part = (entry, suffix) => ({ service: entry.service, name: `${entry.name}#${suffix}` });

function validMeta(value) {
  if (!value || typeof value !== "object") return null;
  const { n, l } = value;
  if (typeof n === "number" && typeof l === "number" && Number.isInteger(n) &&
      Number.isInteger(l) && n > 0 && n <= MAX_CHUNKS && l > 0 && l <= n * CHUNK) {
    return { n, l };
  }
  return null;
}

async function readMeta(entry) {
  const raw = await secrets.get(part(entry, "m"));
  if (!raw) return null;
  try { return validMeta(JSON.parse(raw)); } catch { return null; }
}

async function read(entry) {
  const meta = await readMeta(entry);
  if (!meta) return secrets.get(entry);
  const pieces = await Promise.all(
    Array.from({ length: meta.n }, (_, i) => secrets.get(part(entry, i))));
  const joined = pieces.join("");
  if (joined.length !== meta.l || pieces.some((p) => p == null)) {
    throw Error(`chunked read inconsistent: got ${joined.length}B of ${meta.l}B across ${meta.n} chunks`);
  }
  return Buffer.from(joined, "base64").toString("utf8");
}

async function write(entry, text) {
  const old = await readMeta(entry);
  const size = Buffer.byteLength(text, "utf8");
  if (size <= CHUNK) {
    await secrets.set({ ...entry, value: text });
    if (old) {
      await secrets.set({ ...part(entry, "p"), value: String(old.n) });
      await secrets.delete(part(entry, "m"));
      await Promise.allSettled(
        Array.from({ length: old.n }, (_, i) => secrets.delete(part(entry, i))));
      await secrets.delete(part(entry, "p")).catch(() => {});
    }
    return;
  }
  const encoded = Buffer.from(text, "utf8").toString("base64");
  const count = Math.ceil(encoded.length / CHUNK);
  if (count > MAX_CHUNKS) throw Error("too large for Credential Manager");
  await secrets.set({ ...part(entry, "p"), value: String(Math.max(old?.n ?? 0, count)) });
  await Promise.all(Array.from({ length: count }, (_, i) =>
    secrets.set({ ...part(entry, i), value: encoded.slice(i * CHUNK, (i + 1) * CHUNK) })));
  await secrets.set({ ...part(entry, "m"), value: JSON.stringify({ n: count, l: encoded.length }) });
  const cleanup = [secrets.delete(entry)];
  for (let i = count; i < (old?.n ?? 0); i++) cleanup.push(secrets.delete(part(entry, i)));
  await Promise.allSettled(cleanup);
  await secrets.delete(part(entry, "p")).catch(() => {});
}

async function remove(entry) {
  const meta = await readMeta(entry);
  const steps = [secrets.delete(entry)];
  if (meta) {
    for (let i = 0; i < meta.n; i++) steps.push(secrets.delete(part(entry, i)));
    steps.push(secrets.delete(part(entry, "m")));
  }
  await Promise.all(steps);
  await secrets.delete(part(entry, "p")).catch(() => {});
}

const [command, service, name, file] = process.argv.slice(2);
const entry = { service, name };
if (command === "set") {
  await write(entry, readFileSync(file, "utf8"));
} else if (command === "get") {
  const text = await read(entry);
  if (text == null) process.exit(3);
  writeFileSync(file, text, "utf8");
} else if (command === "delete") {
  await remove(entry);
} else {
  console.error("usage: set|get|delete <service> <name> [file]");
  process.exit(2);
}
