import { copyFile, cp, mkdir, readdir } from "node:fs/promises";
import { join } from "node:path";

await mkdir("public/fonts", { recursive: true });
await copyFile(
  "node_modules/pdfjs-dist/build/pdf.worker.min.mjs",
  "public/pdf.worker.min.mjs",
);

async function findFile(directory, matcher) {
  for (const item of await readdir(directory, { withFileTypes: true })) {
    const path = join(directory, item.name);
    if (item.isDirectory()) {
      const found = await findFile(path, matcher);
      if (found) return found;
    } else if (matcher.test(item.name)) return path;
  }
}

for (const [packageName, family, weight] of [
  ["plex-sans", "IBMPlexSans", "Regular"],
  ["plex-sans", "IBMPlexSans", "Medium"],
  ["plex-sans", "IBMPlexSans", "SemiBold"],
  ["plex-mono", "IBMPlexMono", "Regular"],
]) {
  const source = await findFile(
    `node_modules/@ibm/${packageName}`,
    new RegExp(`^${family}-${weight}\\.woff2$`),
  );
  if (!source)
    throw new Error(`Fonte local não encontrada: ${family}-${weight}`);
  await copyFile(source, `public/fonts/${family}-${weight}.woff2`);
}

await mkdir("public/licenses", { recursive: true });
await copyFile(
  "node_modules/@ibm/plex-sans/LICENSE.txt",
  "public/licenses/IBM-Plex-OFL.txt",
);
await copyFile(
  "node_modules/pdfjs-dist/LICENSE",
  "public/licenses/PDFjs-Apache-2.0.txt",
);

for (const directory of ["standard_fonts", "cmaps", "wasm"]) {
  await cp("node_modules/pdfjs-dist/" + directory, "public/pdf/" + directory, {
    recursive: true,
  });
}
