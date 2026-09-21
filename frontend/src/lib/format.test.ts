import { expect, it } from "vitest";
import { eventTimestamp } from "./format";
it("keeps 15s, 30s and 50s visibly distinct in Brasília", () => {
  expect(
    [15, 30, 50].map((second) => eventTimestamp(`2026-07-01T12:00:${second}Z`)),
  ).toEqual([
    "01/07/2026, 09:00:15",
    "01/07/2026, 09:00:30",
    "01/07/2026, 09:00:50",
  ]);
});
it("preserves declared fractional precision without adding it", () => {
  expect(eventTimestamp("2026-07-01T12:00:15.125Z")).toContain("09:00:15.125");
  expect(eventTimestamp("2026-07-01T12:00:15Z")).toContain("09:00:15");
  expect(eventTimestamp("2026-07-01T12:00:15Z")).not.toContain(".000");
});
it("does not render invalid or absent timestamps as real times", () => {
  expect(eventTimestamp(null)).toBe("Não informado");
  expect(eventTimestamp("bad")).toBe("Horário inválido");
});
