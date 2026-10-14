import { describe, expect, it } from "vitest";
import { exportSchema } from "./contracts";
import { validationIssues } from "./form-errors";

describe("audit contract regressions", () => {
  it.each(["expired", "failed", "cancelled"])(
    "accepts terminal export %s without an error payload",
    (state) => {
      expect(
        exportSchema.parse({
          id: "export",
          state,
          revision_id: "revision",
          download_url: null,
          expires_at: null,
          error: null,
        }).state,
      ).toBe(state);
    },
  );
  it("preserves the paths of identical messages in different claims", () => {
    expect(
      validationIssues({
        claims: [
          { missing_information: { message: "Too many" } },
          { missing_information: { message: "Too many" } },
        ],
      }),
    ).toEqual([
      { path: "claims.0.missing_information", message: "Too many" },
      { path: "claims.1.missing_information", message: "Too many" },
    ]);
  });
});
