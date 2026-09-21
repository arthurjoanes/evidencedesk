"""CLI de extração: stdin/stdout tipados, prazo imposto pelo worker pai."""

import base64
import io
import json
import sys

from pypdf import PdfReader

from evidencedesk.reconciliation.contracts import EventInput, IdentityMapping
from evidencedesk.reconciliation.parsing import parse_snapshot_csv


def restrict_process() -> None:
    if sys.platform == "linux":
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024,) * 2)
        resource.setrlimit(resource.RLIMIT_CPU, (15, 15))
        resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))

    # Parsers never need network/subprocess access. This is additional Python-level
    # containment; the worker container also runs non-root with dropped capabilities.
    def deny_external_effects(event: str, args: tuple) -> None:
        if event.startswith(("socket.", "subprocess.")) or event in {"os.system", "os.posix_spawn"}:
            raise PermissionError("Parser sem acesso à rede ou execução de programas")

    sys.addaudithook(deny_external_effects)


def parse_content(kind: str, media_type: str, content: bytes) -> dict:
    if media_type == "application/pdf":
        if not content.startswith(b"%PDF-"):
            raise ValueError("Assinatura PDF inválida.")
        reader = PdfReader(io.BytesIO(content), strict=True)
        if reader.is_encrypted or len(reader.pages) > 100:
            raise ValueError("PDF criptografado ou com mais de 100 páginas não é aceito.")
        pages = [page.extract_text() or "" for page in reader.pages]
        if not any(page.strip() for page in pages):
            return {"requires_ocr": True, "pages": []}
        if sum(map(len, pages)) > 1_000_000:
            raise ValueError("Texto extraído excede o limite.")
        return {"pages": pages}
    text_content = content.decode("utf-8-sig")
    if "\x00" in text_content:
        raise ValueError("Arquivo textual contém bytes nulos.")
    if kind in {"events", "mappings"}:
        model = EventInput if kind == "events" else IdentityMapping
        rows: list[dict] = []
        for line_number, line in enumerate(text_content.splitlines(), 1):
            if not line.strip():
                continue
            if len(line) > 32_768 or len(rows) >= 100_000:
                raise ValueError("Entrada JSONL excede os limites de linha/registros.")
            value = model.model_validate_json(line).model_dump(mode="json")
            rows.append({"line_number": line_number, "value": value})
        return {"rows": rows}
    if kind == "snapshots":
        return {
            "rows": [
                {"line_number": index + 2, "value": row.model_dump(mode="json")}
                for index, row in enumerate(parse_snapshot_csv(text_content))
            ]
        }
    if len(text_content) > 1_000_000:
        raise ValueError("Documento textual excede o limite de caracteres.")
    return {"pages": [text_content]}


def main() -> None:
    restrict_process()
    request = json.loads(sys.stdin.buffer.read(15 * 1024 * 1024))
    try:
        result = parse_content(
            request["kind"],
            request["media_type"],
            base64.b64decode(request["content"], validate=True),
        )
        print(json.dumps({"ok": True, "result": result}, ensure_ascii=True))
    except (ValueError, UnicodeDecodeError, OSError) as error:
        # Validation errors may contain source payload. Return only a safe class code.
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": {
                        "code": "invalid_file",
                        "message": "Arquivo inválido para o schema ou tipo declarado.",
                        "category": type(error).__name__,
                    },
                }
            )
        )
        sys.exit(2)


if __name__ == "__main__":
    main()
