import { describe, expect, it } from "vitest";
import { summarizeEntries } from "./import-summary";
import { label, tone } from "@/lib/format";
import type { ImportBatch } from "@/lib/contracts";
const entry = (
  state: string,
  error: ImportBatch["entries"][number]["error"] = null,
) => ({
  entry_id: state,
  filename: state,
  kind: "document",
  byte_size: 1,
  sha256: "a",
  state,
  error,
});
describe("faithful import summary", () => {
  it("does not count uploaded files as validated", () => {
    expect(
      summarizeEntries([entry("uploaded"), entry("valid"), entry("pending")]),
    ).toEqual({ total: 3, valid: 1, pending: 2, failed: 0, unknown: 0 });
  });
  it("treats explicit errors as failures even if state contradicts them", () => {
    expect(
      summarizeEntries([entry("valid", { code: "bad", message: "Rejected" })])
        .failed,
    ).toBe(1);
  });
  it("keeps unknown states separate and neutral", () => {
    expect(summarizeEntries([entry("future_state")]).unknown).toBe(1);
    expect(tone("future_state")).toBe("neutral");
  });
  it("has PT-BR names for the manifest kinds and validation state", () => {
    expect(
      ["document", "events", "snapshots", "mappings", "valid"].map(label),
    ).toEqual([
      "Documento",
      "Eventos",
      "Snapshots de pedidos",
      "Mapeamentos",
      "Válido",
    ]);
  });
});
