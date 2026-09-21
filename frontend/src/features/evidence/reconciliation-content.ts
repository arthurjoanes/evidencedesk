import { z } from "zod";

const count = z.number().int().nonnegative().max(Number.MAX_SAFE_INTEGER);
const instant = z.iso.datetime({ offset: true });
const windowSchema = z.object({ from: instant, to: instant });
const aggregateSchema = z
  .object({
    counts: z
      .object({
        orders: count.optional(),
        observations: count.optional(),
        logical_events: count.optional(),
        divergences: count.optional(),
        not_evaluable: count.optional(),
      })
      .optional(),
    rule_revision: z.string().min(1).optional(),
    window: windowSchema.optional(),
    coverage: z
      .array(
        windowSchema.extend({
          source_system: z.string().min(1),
          status: z.enum(["complete", "partial", "unknown"]),
          gaps: z.array(z.string()).optional(),
          event_types: z.array(z.string()).optional(),
          clock_uncertainty_ms: count.nullable().optional(),
        }),
      )
      .optional(),
    divergences: z
      .array(
        z.object({
          id: z.string(),
          order_reference: z.string().nullable(),
          rule_code: z.string(),
          rule_revision: z.string(),
          status: z.enum(["divergence", "observation", "not_evaluable"]),
          summary: z.string(),
        }),
      )
      .optional(),
    divergences_included: count.optional(),
    divergences_total: count.optional(),
  })
  .superRefine((value, context) => {
    if (!Object.values(value).some((field) => field !== undefined))
      context.addIssue({
        code: "custom",
        message: "No recognized aggregate fields",
      });
    if (
      value.divergences !== undefined &&
      value.divergences_included !== undefined &&
      value.divergences.length !== value.divergences_included
    )
      context.addIssue({
        code: "custom",
        message: "Included count contradicts the embedded records",
      });
    if (
      value.divergences_included !== undefined &&
      value.divergences_total !== undefined &&
      value.divergences_included > value.divergences_total
    )
      context.addIssue({
        code: "custom",
        message: "Included count exceeds total",
      });
  });

export type ReconciliationContent = z.infer<typeof aggregateSchema>;

export function readReconciliation(text: string): ReconciliationContent | null {
  try {
    const result = aggregateSchema.safeParse(JSON.parse(text));
    return result.success ? result.data : null;
  } catch {
    return null;
  }
}

// Insert presentation whitespace without serializing numbers, changing escapes,
// or losing duplicate keys. The canonical string is never rewritten.
export function formatJsonForReading(text: string): string | null {
  try {
    JSON.parse(text);
  } catch {
    return null;
  }
  let output = "";
  let depth = 0;
  let quoted = false;
  let escaped = false;
  for (const character of text) {
    if (quoted) {
      output += character;
      if (escaped) escaped = false;
      else if (character === "\\") escaped = true;
      else if (character === '"') quoted = false;
    } else if (character === '"') {
      quoted = true;
      output += character;
    } else if (character === "{" || character === "[") {
      depth++;
      output += character + "\n" + "  ".repeat(depth);
    } else if (character === "}" || character === "]") {
      depth--;
      output += "\n" + "  ".repeat(depth) + character;
    } else if (character === ",") output += ",\n" + "  ".repeat(depth);
    else if (character === ":") output += ": ";
    else if (!/\s/.test(character)) output += character;
  }
  return output;
}
