import { z } from "zod";
import { claimInputSchema, outcomeSchema } from "@/lib/contracts";

export const editorSchema = z.object({
  summary: z
    .string()
    .trim()
    .min(10, "Registre um resumo com pelo menos 10 caracteres.")
    .max(6000, "O resumo aceita até 6.000 caracteres."),
  outcome: outcomeSchema,
  missing_information: z
    .array(
      z
        .string()
        .max(
          1000,
          "Cada linha de lacuna ou verificação aceita até 1.000 caracteres.",
        ),
    )
    .max(20, "Use no máximo 20 linhas por lista de lacunas ou verificações."),
  suggested_checks: z
    .array(
      z
        .string()
        .max(
          1000,
          "Cada linha de lacuna ou verificação aceita até 1.000 caracteres.",
        ),
    )
    .max(20, "Use no máximo 20 linhas por lista de lacunas ou verificações."),
  claims: z
    .array(
      claimInputSchema.refine((claim) => claim.evidence_links.length > 0, {
        path: ["evidence_links"],
        message: "Vincule ao menos uma fonte autorizada a esta alegação.",
      }),
    )
    .max(30, "Uma revisão aceita no máximo 30 alegações."),
});
export type Draft = z.infer<typeof editorSchema>;
