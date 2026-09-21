from pydantic import ConfigDict, Field

from evidencedesk.model_runtime.contracts import GeneratedDossier


class ManualDossierInput(GeneratedDossier):
    model_config = ConfigDict(extra="forbid")
    evidence_snapshot_id: str = Field(min_length=1, max_length=200)


class RevisionInput(GeneratedDossier):
    base_revision_id: str = Field(min_length=1, max_length=200)
