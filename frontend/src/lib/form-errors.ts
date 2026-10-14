export function validationMessages(errors: unknown): string[] {
  const messages = new Set<string>();
  function visit(value: unknown) {
    if (!value || typeof value !== "object") return;
    for (const [key, item] of Object.entries(value)) {
      if (key === "ref") continue;
      if (key === "message" && typeof item === "string") messages.add(item);
      else if (key !== "types") visit(item);
    }
  }
  visit(errors);
  return [...messages];
}

export function validationIssues(
  errors: unknown,
): { path: string; message: string }[] {
  const issues: { path: string; message: string }[] = [];
  function visit(value: unknown, path: string[]) {
    if (!value || typeof value !== "object") return;
    const record = value as Record<string, unknown>;
    if (typeof record.message === "string")
      issues.push({
        path: path.filter((part) => part !== "root").join("."),
        message: record.message,
      });
    for (const [key, item] of Object.entries(record))
      if (!["ref", "message", "type", "types"].includes(key))
        visit(item, [...path, key]);
  }
  visit(errors, []);
  return issues;
}
