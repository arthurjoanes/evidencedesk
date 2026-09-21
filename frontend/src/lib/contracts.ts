import { z } from "zod";

const nullableText = z.string().nullable();
const identifiers = z.array(z.string());
export const outcomeSchema = z.enum([
  "evidence_found",
  "conflicting_evidence",
  "insufficient_evidence",
  "unsupported_scope",
]);
export const jobStateSchema = z.enum([
  "queued",
  "running",
  "retry_wait",
  "succeeded",
  "failed",
  "cancelled",
]);
export const problemSchema = z.object({
  code: z.string(),
  message: z.string(),
});
export const apiErrorSchema = z.object({
  error: problemSchema.extend({
    request_id: z.string(),
    retryable: z.boolean(),
    field_errors: z.record(z.string(), z.array(z.string())).optional(),
  }),
});
export const sessionSchema = z.object({
  user: z.object({
    id: z.string(),
    name: z.string(),
    role: z.enum(["tenant_admin", "analyst", "reviewer"]),
  }),
  tenant: z.object({ id: z.string(), name: z.string() }),
  csrf_token: z.string(),
  expires_at: z.string(),
  permissions: identifiers,
  runtime: z.object({
    generation_enabled: z.boolean(),
    provider: z.string(),
    model_display_name: z.string(),
    disabled_reason: nullableText,
  }),
});
export type Session = z.infer<typeof sessionSchema>;

export function pageSchema<T extends z.ZodType>(item: T) {
  return z.object({
    items: z.array(item),
    next_cursor: nullableText,
    total: z.number().int().nonnegative().nullable(),
    evidence_snapshot_id: z.string().optional(),
  });
}
export const coverageSchema = z.object({
  event_types: z.array(z.string()).optional(),
  clock_uncertainty_ms: z
    .number()
    .int()
    .nonnegative()
    .max(86_400_000)
    .nullable()
    .optional(),
  source_system: z.string(),
  status: z.string(),
  from: nullableText,
  to: nullableText,
  gaps: z.array(z.string()),
});
export type Coverage = z.infer<typeof coverageSchema>;
export const collectionSchema = z.object({
  id: z.string(),
  name: z.string(),
  description: z.string(),
  active_snapshot_id: nullableText,
});
export const runSummarySchema = z.object({
  id: z.string(),
  state: jobStateSchema,
  stage: z.string(),
  outcome: outcomeSchema.nullable(),
  created_at: z.string(),
});
export const incidentSchema = z.object({
  id: z.string(),
  title: z.string(),
  status: z.enum(["open", "in_review", "resolved"]),
  description: z.string(),
  collection_id: z.string(),
  window: z.object({ from: z.string(), to: z.string(), time_zone: z.string() }),
  created_at: z.string(),
  updated_at: z.string(),
  evidence_snapshot_id: z.string(),
  available_snapshots: z.array(
    z.object({ id: z.string(), published_at: z.string() }),
  ),
  coverage: z.array(coverageSchema),
  counts: z.object({ orders: z.number().int(), divergences: z.number().int() }),
  latest_run: runSummarySchema.nullable(),
  dossier_id: nullableText,
  permissions: identifiers,
});
export type Incident = z.infer<typeof incidentSchema>;
export const timelineRowSchema = z.object({
  id: z.string(),
  evidence_id: z.string(),
  order_reference: nullableText,
  source_system: z.string(),
  event_type: z.string(),
  occurred_at: nullableText,
  observed_at: nullableText,
  ingested_at: z.string(),
  temporal_quality: z.string(),
  delivery_count: z.number().int(),
});
export type TimelineRow = z.infer<typeof timelineRowSchema>;
export const timelinePageSchema = pageSchema(timelineRowSchema).extend({
  coverage: z.array(coverageSchema),
  ordering: z.literal("occurred_at_nulls_last"),
});
export const divergenceSchema = z.object({
  id: z.string(),
  order_reference: nullableText,
  rule_code: z.string(),
  rule_revision: z.string(),
  status: z.enum(["divergence", "observation", "not_evaluable"]),
  summary: z.string(),
  evidence_ids: identifiers,
});
export const divergencePageSchema = pageSchema(divergenceSchema).extend({
  coverage: z.array(coverageSchema),
});
export const evidenceKindSchema = z.enum([
  "document_span",
  "source_event",
  "delivery_attempt",
  "order_snapshot",
  "reconciliation_result",
]);
export const evidenceSummarySchema = z.object({
  id: z.string(),
  kind: evidenceKindSchema,
  title: z.string(),
  version: z.string(),
  source_system: z.string(),
  temporal_role: nullableText,
  excerpt: z.string(),
});
export const evidenceSchema = evidenceSummarySchema
  .omit({ excerpt: true })
  .extend({
    sha256: z.string(),
    valid_from: nullableText,
    valid_until: nullableText,
    canonical_text: z.string(),
    locator: z.object({
      page: z.number().int().optional(),
      line_start: z.number().int().optional(),
      line_end: z.number().int().optional(),
      char_start: z.number().int().optional(),
      char_end: z.number().int().optional(),
      as_of: z.string().optional(),
    }),
    original: z
      .object({
        media_type: z.string(),
        byte_size: z.number().int(),
        content_url: z.string(),
      })
      .nullable(),
  });
export type Evidence = z.infer<typeof evidenceSchema>;
export type EvidenceSummary = z.infer<typeof evidenceSummarySchema>;

export const claimInputSchema = z.object({
  claim_id: z.string().optional(),
  kind: z.enum(["observed_fact", "hypothesis"]),
  text: z.string().trim().min(1).max(3000),
  order_references: identifiers,
  evidence_links: z.array(
    z.object({
      evidence_id: z.string(),
      relation: z.enum(["supports", "contradicts", "context"]),
    }),
  ),
  support_status: z.enum(["pending_review", "contested", "reviewed"]),
  missing_information: identifiers,
  suggested_checks: identifiers,
});
export const claimSchema = claimInputSchema.extend({ claim_id: z.string() });
export type Claim = z.infer<typeof claimSchema>;
export type ClaimInput = z.infer<typeof claimInputSchema>;
const reviewStateSchema = z.enum([
  "draft",
  "submitted",
  "approved",
  "changes_requested",
]);
export const impactSummarySchema = z.object({
  source: z.literal("deterministic_reconciliation"),
  evidence_snapshot_id: z.string(),
  rule_revision: z.string(),
  observations: z.number().int().nonnegative(),
  logical_events: z.number().int().nonnegative(),
  orders: z.number().int().nonnegative(),
  divergences: z.number().int().nonnegative(),
  not_evaluable: z.number().int().nonnegative(),
});
export const revisionSchema = z.object({
  review: z
    .object({
      submitted_by: nullableText,
      reviewed_by: nullableText,
      reason: nullableText,
      claim_ids: z.array(z.string()),
      updated_at: nullableText,
    })
    .optional(),
  impact_summary: impactSummarySchema.nullable().optional(),
  missing_information: z.array(z.string()).optional(),
  suggested_checks: z.array(z.string()).optional(),
  id: z.string(),
  number: z.number().int(),
  base_revision_id: nullableText,
  summary: z.string(),
  claims: z.array(claimSchema),
  outcome: outcomeSchema,
  created_by: z.string(),
  created_at: z.string(),
  review_status: reviewStateSchema,
  etag: z.string(),
});
export type Revision = z.infer<typeof revisionSchema>;
export const dossierSummarySchema = z.object({
  id: z.string(),
  origin: z.enum(["manual", "ai"]),
  created_at: z.string(),
  approved_revision_id: nullableText,
  current_revision_id: z.string(),
});
export const dossierSchema = z.object({
  incident_id: z.string(),
  id: z.string(),
  origin: z.enum(["manual", "ai"]),
  evidence_snapshot_id: z.string(),
  current_revision_id: z.string(),
  approved_revision_id: nullableText,
  revisions: z.array(
    z.object({
      id: z.string(),
      number: z.number().int(),
      author: z.string(),
      created_at: z.string(),
      review_status: reviewStateSchema,
    }),
  ),
  permissions: identifiers,
});
export type Dossier = z.infer<typeof dossierSchema>;
export const runSchema = runSummarySchema.extend({
  steps: z.array(
    z.object({
      key: z.string(),
      status: z.string(),
      started_at: nullableText,
      completed_at: nullableText,
    }),
  ),
  cancel_requested: z.boolean(),
  last_event_id: z.number().int(),
  evidence_snapshot_id: z.string(),
  dossier_id: nullableText,
  revision_id: nullableText,
  error: problemSchema.nullable(),
  started_at: nullableText,
  completed_at: nullableText,
  usage: z.object({
    status: z.string(),
    input_tokens: z.number().nullable(),
    output_tokens: z.number().nullable(),
  }),
});
export type Run = z.infer<typeof runSchema>;
export const streamEventSchema = z.object({
  seq: z.number().int(),
  type: z.enum(["progress", "snapshot", "terminal", "resync_required"]),
  payload: z.unknown(),
});

export const importManifestSchema = z
  .object({
    schema_version: z.literal("1"),
    title: z.string().min(1).max(200),
    source_tenant: z.string().nullable().optional(),
    coverage: z.array(coverageSchema.strict()).max(200),
    entries: z
      .array(
        z
          .object({
            entry_id: z.string().regex(/^[A-Za-z0-9_-]{1,100}$/),
            filename: z
              .string()
              .min(1)
              .refine(
                (name) => !/[\\/]/.test(name) && !name.includes(".."),
                "Nome de arquivo inválido.",
              ),
            kind: z.enum(["events", "snapshots", "document", "mappings"]),
            media_type: z.string(),
            byte_size: z
              .number()
              .int()
              .positive()
              .max(10 * 1024 * 1024),
            sha256: z.string().regex(/^[a-f0-9]{64}$/),
            metadata: z.record(z.string(), z.unknown()).optional(),
          })
          .strict(),
      )
      .min(1)
      .max(40),
  })
  .strict()
  .refine(
    (manifest) =>
      manifest.entries.reduce((sum, entry) => sum + entry.byte_size, 0) <=
      40 * 1024 * 1024,
    "O pacote excede 40 MiB.",
  );
export type ImportManifest = z.infer<typeof importManifestSchema>;
export const importSchema = z.object({
  id: z.string(),
  collection_id: z.string(),
  title: z.string(),
  state: z.enum([
    "receiving",
    "sealed",
    "processing",
    "ready",
    "rejected",
    "failed",
    "cancelled",
  ]),
  created_at: z.string(),
  evidence_snapshot_id: nullableText,
  entries: z.array(
    z.object({
      entry_id: z.string(),
      filename: z.string(),
      kind: z.string(),
      byte_size: z.number(),
      sha256: z.string(),
      state: z.string(),
      error: problemSchema.nullable(),
    }),
  ),
  error: problemSchema.nullable(),
});
export type ImportBatch = z.infer<typeof importSchema>;
export const exportSchema = z.object({
  id: z.string(),
  state: jobStateSchema,
  revision_id: z.string(),
  download_url: nullableText,
  expires_at: nullableText,
  error: problemSchema.nullable(),
});
export type ExportJob = z.infer<typeof exportSchema>;
