import { describe, expect, it } from "vitest";
import {
  formatJsonForReading,
  readReconciliation,
} from "./reconciliation-content";

describe("deterministic evidence presentation", () => {
  it("keeps zero, absence and partial coverage distinct", () => {
    const result = readReconciliation(
      JSON.stringify({
        counts: { orders: 222, divergences: 0 },
        coverage: [
          {
            source_system: "orders",
            from: "2026-07-01T12:00:00Z",
            to: "2026-07-01T12:30:00Z",
            status: "partial",
            gaps: ["Five minutes unavailable"],
            clock_uncertainty_ms: 0,
          },
        ],
      }),
    );
    expect(result?.counts?.divergences).toBe(0);
    expect(result?.counts?.observations).toBeUndefined();
    expect(result?.coverage?.[0].status).toBe("partial");
    expect(result?.coverage?.[0].clock_uncertainty_ms).toBe(0);
    expect(result?.divergences_total).toBeUndefined();
  });
  it.each([
    "invalid JSON",
    "{}",
    "[]",
    '{"counts":{"orders":"222"}}',
    '{"counts":{"orders":-1}}',
    '{"counts":{"orders":9007199254740993}}',
    '{"coverage":[{"status":"invented"}]}',
  ])("rejects incompatible aggregate: %s", (input) => {
    expect(readReconciliation(input)).toBeNull();
  });
  it("refuses contradictory embedded counts without repairing them", () => {
    expect(
      readReconciliation(
        '{"divergences":[],"divergences_included":1,"divergences_total":2}',
      ),
    ).toBeNull();
    expect(
      readReconciliation('{"divergences_included":2,"divergences_total":1}'),
    ).toBeNull();
    expect(
      readReconciliation(
        '{"divergences":[],"divergences_included":0,"divergences_total":10}',
      ),
    ).not.toBeNull();
  });
  it("formats only whitespace and preserves numeric lexemes, escapes and duplicate keys", () => {
    const original =
      '{"n":9007199254740993,"n":1.00e+02,"text":"\\u0041, { \\\" ok","array":[true,null]}';
    const formatted = formatJsonForReading(original);
    expect(formatted).toContain('"n": 9007199254740993');
    expect(formatted).toContain('"n": 1.00e+02');
    expect(formatted).toContain('"text": "\\u0041, { \\\" ok"');
    expect(formatted).toContain("\n");
    expect(JSON.parse(formatted!)).toEqual(JSON.parse(original));
  });
  it("does not try to format text or damaged JSON", () => {
    expect(formatJsonForReading("Fonte textual canônica.")).toBeNull();
    expect(formatJsonForReading('{"orders":')).toBeNull();
  });
});
