from pathlib import PurePath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from evidencedesk.reconciliation.contracts import SourceCoverage


class ManifestEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entry_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")
    filename: str = Field(min_length=1, max_length=160)
    kind: Literal["events", "snapshots", "document", "mappings"]
    media_type: str
    byte_size: int = Field(ge=1, le=10 * 1024 * 1024)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def allowed_file(self) -> "ManifestEntry":
        if any(char in self.filename for char in ("/", "\\", ":", "\x00")) or self.filename in {
            ".",
            "..",
        }:
            raise ValueError("Use somente o nome do arquivo, sem caminhos.")
        extensions = {
            "events": {".jsonl"},
            "snapshots": {".csv"},
            "mappings": {".jsonl"},
            "document": {".md", ".txt", ".pdf"},
        }
        suffix = PurePath(self.filename).suffix.casefold()
        if suffix not in extensions[self.kind]:
            raise ValueError("Extensão não permitida para este tipo de entrada.")
        expected_types = {
            ".jsonl": {"application/x-ndjson", "application/jsonl"},
            ".csv": {"text/csv"},
            ".md": {"text/markdown"},
            ".txt": {"text/plain"},
            ".pdf": {"application/pdf"},
        }
        if self.media_type not in expected_types[suffix]:
            raise ValueError("Tipo declarado não corresponde ao arquivo.")
        return self


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1"]
    title: str = Field(min_length=1, max_length=200)
    source_tenant: str | None = Field(default=None, max_length=200)
    coverage: list[SourceCoverage] = Field(max_length=200)
    entries: list[ManifestEntry] = Field(min_length=1, max_length=40)

    @model_validator(mode="after")
    def bounded_unique_files(self) -> "Manifest":
        if sum(entry.byte_size for entry in self.entries) > 40 * 1024 * 1024:
            raise ValueError("Pacote excede 40 MiB.")
        for values in (
            [entry.entry_id for entry in self.entries],
            [entry.filename for entry in self.entries],
        ):
            if len(values) != len(set(values)):
                raise ValueError("Entradas do manifesto não podem repetir nome ou ID.")
        return self


class ImportInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    collection_id: str = Field(min_length=1, max_length=200)
    manifest: Manifest
