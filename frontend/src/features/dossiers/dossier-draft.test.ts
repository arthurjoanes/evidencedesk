import { expect, it } from "vitest";
import { editorSchema } from "./dossier-draft";
import { validationMessages } from "@/lib/form-errors";
const valid = {
  summary: "Sem cobertura suficiente para concluir.",
  outcome: "insufficient_evidence",
  missing_information: [],
  suggested_checks: [],
  claims: [],
};
it("permits honest abstention without fabricated claims", () => {
  expect(editorSchema.safeParse(valid).success).toBe(true);
});
it("explains excessive note count and excessive line size", () => {
  for (const values of [Array(21).fill("lacuna"), ["x".repeat(1001)]]) {
    const result = editorSchema.safeParse({
      ...valid,
      missing_information: values,
    });
    expect(result.success).toBe(false);
    if (!result.success)
      expect(result.error.issues[0].message).toMatch(/1.000|20 linhas/);
  }
});
it("collects nested field and array errors without following DOM refs", () => {
  expect(
    validationMessages({
      missing_information: [{ message: "Linha longa" }],
      claims: { root: { message: "Muitas alegações" } },
      ref: { message: "ignored" },
    }),
  ).toEqual(["Linha longa", "Muitas alegações"]);
});
const claim = {
  kind: "observed_fact",
  text: "A observação consta da fonte.",
  order_references: [],
  evidence_links: [{ evidence_id: "source-1", relation: "supports" }],
  support_status: "pending_review",
  missing_information: [],
  suggested_checks: [],
};
it.each(["evidence_found", "conflicting_evidence"])(
  "requires cited claims for outcome %s",
  (outcome) => {
    expect(editorSchema.safeParse({ ...valid, outcome }).success).toBe(false);
    expect(
      editorSchema.safeParse({ ...valid, outcome, claims: [claim] }).success,
    ).toBe(true);
  },
);
it.each([
  ["missing_information", Array(21).fill("lacuna"), /20 linhas/],
  ["suggested_checks", ["x".repeat(1001)], /1.000 caracteres/],
  ["order_references", Array(31).fill("order-1"), /30 pedidos/],
  ["order_references", ["x".repeat(201)], /200 caracteres/],
  ["evidence_links", Array(21).fill(claim.evidence_links[0]), /20 fontes/],
  ["text", " ", /Descreva a alegação/],
])("explains the server limit for claim field %s", (field, value, message) => {
  const result = editorSchema.safeParse({
    ...valid,
    claims: [{ ...claim, [field]: value }],
  });
  expect(result.success).toBe(false);
  if (!result.success)
    expect(result.error.issues[0].message).toMatch(message as RegExp);
});
