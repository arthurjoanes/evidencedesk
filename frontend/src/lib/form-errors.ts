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
