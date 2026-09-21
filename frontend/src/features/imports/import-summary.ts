import type { ImportBatch } from "@/lib/contracts";
export function summarizeEntries(entries: ImportBatch["entries"]) {
  const summary = {
    total: entries.length,
    valid: 0,
    pending: 0,
    failed: 0,
    unknown: 0,
  };
  for (const entry of entries) {
    if (entry.error || ["failed", "rejected"].includes(entry.state))
      summary.failed++;
    else if (entry.state === "valid") summary.valid++;
    else if (
      ["pending", "uploading", "uploaded", "processing"].includes(entry.state)
    )
      summary.pending++;
    else summary.unknown++;
  }
  return summary;
}
