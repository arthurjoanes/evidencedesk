"""Aggregate extraction limits keep forty individually valid files bounded as a batch."""

from dataclasses import dataclass

from evidencedesk.errors import Problem


@dataclass
class ExtractionBudget:
    rows: int = 0
    text_bytes: int = 0
    evidence_records: int = 0

    def include(self, parsed: dict, derived_records: int = 0) -> None:
        rows = self.rows + len(parsed.get("rows", []))
        text_bytes = self.text_bytes + sum(
            len(page.encode("utf-8")) for page in parsed.get("pages", [])
        )
        records = self.evidence_records + derived_records
        if rows > 50_000 or text_bytes > 8 * 1024 * 1024 or records > 50_000:
            raise Problem(
                422,
                "extraction_budget_exceeded",
                "A extração do pacote excede 50 mil registros ou 8 MiB de texto. Divida os arquivos em pacotes menores.",
            )
        self.rows, self.text_bytes, self.evidence_records = rows, text_bytes, records
