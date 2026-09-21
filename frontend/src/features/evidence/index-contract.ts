import { z } from "zod";
import { jobStateSchema, problemSchema } from "@/lib/contracts";

export const indexSchema = z
  .object({
    evidence_snapshot_id: z.string(),
    embedding_revision: z.string(),
    total_documents: z.number().int().nonnegative(),
    indexed_documents: z.number().int().nonnegative(),
    complete: z.boolean(),
    indexing_enabled: z.boolean(),
    disabled_reason: z.string().nullable(),
    job: z
      .object({
        id: z.string(),
        state: jobStateSchema,
        stage: z.string(),
        error: problemSchema.nullable(),
        attempt: z.number().int().nonnegative(),
      })
      .nullable(),
  })
  .refine(
    (value) =>
      value.indexed_documents <= value.total_documents &&
      value.complete === (value.total_documents === value.indexed_documents),
    "Inconsistent index coverage",
  );
