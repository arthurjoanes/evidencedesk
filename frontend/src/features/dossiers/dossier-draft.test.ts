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
