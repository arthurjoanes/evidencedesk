export type Decision = "" | "approved" | "changes_requested";

export function reviewReadiness(
  decision: Decision,
  reason: string,
  claimIds: string[],
  confirmed: ReadonlySet<string>,
  abstentionConfirmed: boolean,
) {
  const remaining = claimIds.filter((id) => !confirmed.has(id)).length;
  const allReviewed =
    claimIds.length > 0 ? remaining === 0 : abstentionConfirmed;
  const validReason =
    Array.from(reason.trim()).length >= 5 && Array.from(reason).length <= 3000;
  return {
    remaining,
    allReviewed,
    canRecord:
      validReason &&
      decision !== "" &&
      (decision !== "approved" || allReviewed),
  };
}
