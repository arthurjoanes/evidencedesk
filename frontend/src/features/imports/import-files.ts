import { importManifestSchema, type ImportManifest } from "@/lib/contracts";

export class PackageValidationError extends Error {}
export function parseManifest(text: string): ImportManifest {
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    throw new PackageValidationError(
      "O manifesto precisa ser um arquivo JSON válido.",
    );
  }
  const result = importManifestSchema.safeParse(value);
  if (!result.success)
    throw new PackageValidationError(
      result.error.issues
        .map((issue) => issue.path.join(".") + ": " + issue.message)
        .join(" · "),
    );
  const names = new Set<string>();
  const identifiers = new Set<string>();
  for (const entry of result.data.entries) {
    if (names.has(entry.filename) || identifiers.has(entry.entry_id))
      throw new PackageValidationError(
        "O manifesto contém nomes de arquivo ou IDs de entrada repetidos.",
      );
    names.add(entry.filename);
    identifiers.add(entry.entry_id);
  }
  return result.data;
}
export function matchFiles(
  manifest: ImportManifest,
  files: File[],
): Map<string, File> {
  if (new Set(files.map((file) => file.name)).size !== files.length)
    throw new PackageValidationError(
      "Foram selecionados arquivos com nomes repetidos.",
    );
  if (files.length !== manifest.entries.length)
    throw new PackageValidationError(
      "Selecione exatamente os arquivos descritos no manifesto, sem o próprio manifesto.",
    );
  const matched = new Map<string, File>();
  for (const entry of manifest.entries) {
    const file = files.find((candidate) => candidate.name === entry.filename);
    if (!file)
      throw new PackageValidationError("Arquivo ausente: " + entry.filename);
    if (file.size !== entry.byte_size)
      throw new PackageValidationError(
        "O tamanho de " + entry.filename + " difere do manifesto.",
      );
    matched.set(entry.entry_id, file);
  }
  return matched;
}
export async function verifyFiles(
  manifest: ImportManifest,
  files: File[],
  onProgress: (text: string) => void,
): Promise<Map<string, File>> {
  const matched = matchFiles(manifest, files);
  for (const entry of manifest.entries) {
    onProgress("Conferindo integridade de " + entry.filename);
    const hash = await crypto.subtle.digest(
      "SHA-256",
      await matched.get(entry.entry_id)!.arrayBuffer(),
    );
    const actual = Array.from(new Uint8Array(hash))
      .map((byte) => byte.toString(16).padStart(2, "0"))
      .join("");
    if (actual !== entry.sha256.replace(/^sha256:/i, "").toLowerCase())
      throw new PackageValidationError(
        "O conteúdo de " +
          entry.filename +
          " difere do SHA-256 declarado. Nenhum novo pacote foi enviado.",
      );
  }
  return matched;
}
