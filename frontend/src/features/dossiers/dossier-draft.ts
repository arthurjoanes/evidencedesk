import { z } from "zod";
import { claimInputSchema, outcomeSchema } from "@/lib/contracts";

const noteList = z
  .array(
    z
      .string()
      .max(
        1000,
        "Cada linha de lacuna ou verificação aceita até 1.000 caracteres.",
      ),
  )
  .max(20, "Use no máximo 20 linhas por lista de lacunas ou verificações.");
const editorClaimSchema = claimInputSchema.extend({
  text: z
    .string()
    .trim()
    .min(1, "Descreva a alegação.")
    .max(3000, "O texto da alegação aceita até 3.000 caracteres."),
  order_references: z
    .array(
      z
        .string()
        .trim()
        .max(200, "Cada referência de pedido aceita até 200 caracteres."),
    )
    .max(30, "Vincule no máximo 30 pedidos por alegação."),
  evidence_links: claimInputSchema.shape.evidence_links
    .min(1, "Vincule ao menos uma fonte autorizada a esta alegação.")
    .max(20, "Vincule no máximo 20 fontes por alegação."),
  missing_information: noteList,
  suggested_checks: noteList,
});

export const editorSchema = z
  .object({
    summary: z
      .string()
      .trim()
      .min(10, "Registre um resumo com pelo menos 10 caracteres.")
      .max(6000, "O resumo aceita até 6.000 caracteres."),
    outcome: outcomeSchema,
    missing_information: noteList,
    suggested_checks: noteList,
    claims: z
      .array(editorClaimSchema)
      .max(30, "Uma revisão aceita no máximo 30 alegações."),
  })
  .refine(
    (draft) =>
      !["evidence_found", "conflicting_evidence"].includes(draft.outcome) ||
      draft.claims.length > 0,
    {
      path: ["outcome"],
      message:
        "Um resultado com evidências exige ao menos uma alegação com fonte vinculada.",
    },
  );
export type Draft = z.infer<typeof editorSchema>;
