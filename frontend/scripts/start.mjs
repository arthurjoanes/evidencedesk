import { cp } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const root = new URL("../", import.meta.url);
await cp(new URL("public/", root), new URL(".next/standalone/public/", root), {
  recursive: true,
});
await cp(
  new URL(".next/static/", root),
  new URL(".next/standalone/.next/static/", root),
  { recursive: true },
);
process.env.PORT ??= "3106";
process.env.HOSTNAME = process.env.FRONTEND_HOST ?? "127.0.0.1";
process.chdir(fileURLToPath(new URL(".next/standalone/", root)));
await import(new URL(".next/standalone/server.js", root).href);
