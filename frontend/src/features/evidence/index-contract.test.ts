import { describe, expect, it } from "vitest";
import { indexSchema } from "./index-contract";
import { label } from "@/lib/format";

const pending = {
  evidence_snapshot_id: "snapshot",
  embedding_revision: "revision",
  total_documents: 10,
  indexed_documents: 3,
  complete: false,
  indexing_enabled: false,
  disabled_reason: "Perfil não configurado",
  job: null,
};
describe("index capability and coverage", () => {
  it("keeps capability separate from partial document coverage", () => {
    expect(indexSchema.parse(pending)).toMatchObject({
      indexing_enabled: false,
      complete: false,
      indexed_documents: 3,
    });
  });
  it("rejects missing capability and contradictory completion or counts", () => {
    expect(
      indexSchema.safeParse({ ...pending, indexing_enabled: undefined })
        .success,
    ).toBe(false);
    expect(indexSchema.safeParse({ ...pending, complete: true }).success).toBe(
      false,
    );
    expect(
      indexSchema.safeParse({ ...pending, indexed_documents: 11 }).success,
    ).toBe(false);
  });
  it("translates each durable investigation stage", () => {
    for (const stage of [
      "reconciliation",
      "planning",
      "retrieval",
      "generation",
      "validation",
    ])
      expect(label(stage)).not.toBe(stage);
  });
});
