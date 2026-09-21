import { readFile } from "node:fs/promises";
import { describe, expect, it } from "vitest";
import { matchFiles, parseManifest, verifyFiles } from "./import-files";
const sha = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad";
function manifest() {
  return {
    schema_version: "1" as const,
    title: "Pacote",
    coverage: [],
    entries: [
      {
        entry_id: "doc1",
        filename: "note.md",
        kind: "document" as const,
        media_type: "text/markdown",
        byte_size: 3,
        sha256: sha,
      },
    ],
  };
}
describe("import package validation before upload", () => {
  it("verifies actual content, not just the claimed hash", async () => {
    const input = parseManifest(JSON.stringify(manifest()));
    await expect(
      verifyFiles(input, [new File(["abc"], "note.md")], () => {}),
    ).resolves.toBeInstanceOf(Map);
    await expect(
      verifyFiles(input, [new File(["xyz"], "note.md")], () => {}),
    ).rejects.toThrow("SHA-256");
  });
  it("preserves temporal coverage qualifiers when serializing a manifest", () => {
    const input = {
      ...manifest(),
      coverage: [
        {
          source_system: "payments",
          status: "partial",
          from: "2026-07-01T00:00:00Z",
          to: "2026-07-02T00:00:00Z",
          gaps: ["Delivery gap"],
          event_types: ["payment.confirmed"],
          clock_uncertainty_ms: 500,
        },
      ],
    };
    const parsed = parseManifest(JSON.stringify(input));
    expect(parsed.coverage).toEqual(input.coverage);
  });
  it("rejects invalid JSON and traversal filenames", () => {
    expect(() => parseManifest("{")).toThrow("JSON");
    const input = manifest();
    input.entries[0].filename = "../note.md";
    expect(() => parseManifest(JSON.stringify(input))).toThrow(
      "Nome de arquivo",
    );
  });
  it("rejects duplicate entry identity even under different filenames", () => {
    const input = manifest();
    input.entries.push({ ...input.entries[0], filename: "other.md" });
    expect(() => parseManifest(JSON.stringify(input))).toThrow("repetidos");
  });
  it("rejects extra, missing, and wrongly sized files", () => {
    const input = parseManifest(JSON.stringify(manifest()));
    expect(() => matchFiles(input, [])).toThrow("exatamente");
    expect(() => matchFiles(input, [new File(["abc"], "other.md")])).toThrow(
      "ausente",
    );
    expect(() => matchFiles(input, [new File(["abcd"], "note.md")])).toThrow(
      "tamanho",
    );
    expect(() =>
      matchFiles(input, [
        new File(["abc"], "note.md"),
        new File(["abc"], "other.md"),
      ]),
    ).toThrow("exatamente");
  });
  it("enforces per-file and complete package memory bounds", () => {
    const input = manifest();
    input.entries[0].byte_size = 10 * 1024 * 1024 + 1;
    expect(() => parseManifest(JSON.stringify(input))).toThrow();
    input.entries = Array.from({ length: 5 }, (_, index) => ({
      ...input.entries[0],
      byte_size: 10 * 1024 * 1024,
      entry_id: "e" + index,
      filename: index + ".md",
    }));
    expect(() => parseManifest(JSON.stringify(input))).toThrow("40 MiB");
  });
});

it("ships a downloadable example whose actual bytes match its manifest", async () => {
  const manifest = parseManifest(
    await readFile("public/examples/manifesto-exemplo.json", "utf8"),
  );
  const entry = manifest.entries[0];
  const content = await readFile("public/examples/" + entry.filename);
  await expect(
    verifyFiles(manifest, [new File([content], entry.filename)], () => {}),
  ).resolves.toBeInstanceOf(Map);
  expect(manifest.coverage).toEqual([]);
});
