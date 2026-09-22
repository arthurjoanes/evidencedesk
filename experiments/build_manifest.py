"""Build the public model evidence index; does not inspect settings, credentials or holdout."""

import hashlib
import json
from pathlib import Path

from evidencedesk.retrieval.chunking import DOCUMENT_CHUNK_REVISION
from evidencedesk.retrieval.lexical import LEXICAL_REVISION
from evidencedesk.retrieval.local_models import (
    EMBEDDING_MODEL,
    EMBEDDING_REVISION,
    RERANKER_MODEL,
    RERANKER_REVISION,
)


def main():
    root = Path(__file__).resolve().parents[1]
    paths = [
        "experiments/protocol.json",
        "experiments/requirements-ml.lock",
        "experiments/Dockerfile",
        "experiments/patch_accelerate.py",
        "experiments/test_checkpoint_security.py",
        "experiments/data/train.jsonl",
        "experiments/data/dev.jsonl",
        "backend/src/evidencedesk/retrieval/local_models.py",
        "backend/src/evidencedesk/retrieval/chunking.py",
        "backend/src/evidencedesk/model_runtime/release.py",
        "backend/src/evidencedesk/reconciliation/rules.py",
    ]
    report_index = json.loads((root / "experiments/reports/index.json").read_text())
    paths.extend("experiments/reports/" + name for name in report_index)
    paths.append("experiments/reports/index.json")
    hashes = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in paths}
    manifest = {
        "schema_version": "1",
        "artifact_kind": "model_and_evaluation_evidence_index",
        "review_date": "2026-09-22",
        "contains_credentials": False,
        "local_models": [
            {
                "role": "embedding",
                "model": EMBEDDING_MODEL,
                "revision": EMBEDDING_REVISION,
                "license": "MIT",
                "dimensions": 384,
                "status": "base_optional_ml_profile",
            },
            {
                "role": "reranker",
                "model": RERANKER_MODEL,
                "revision": RERANKER_REVISION,
                "license": "Apache-2.0",
                "status": "base_optional_ml_profile",
            },
        ],
        "candidate": {
            "run": "20260921T074245Z-train",
            "status": "trained_not_promoted",
            "weights_location": "private experiment_runs Docker volume; not committed",
            "checkpoint_file_hashes": "experiments/reports/candidate-files.json",
            "human_gate": "pending",
            "reserved_evaluation_used": False,
        },
        "generation": {
            "provider": "azure_openai",
            "model": "runtime_deployment_not_inferred",
            "configuration": "frozen per run, returned model recorded in private result",
            "store": False,
            "background": False,
        },
        "retrieval": {
            "lexical_revision": LEXICAL_REVISION,
            "current_ingestion_chunk_policy": DOCUMENT_CHUNK_REVISION,
            "ranking_experiment_corpus": "124 whole synthetic documents; predates chunk policy v2",
            "ranking_quality_transfer_to_v2": "requires_re_evaluation",
        },
        "ml_image_verification": {
            "report": "experiments/reports/ml-final-build.json",
            "scope": "locked dependency build, pip check and real HTTP smoke",
            "vulnerability_scan": "not_performed_in_this_task",
        },
        "ml_checkpoint_security": {
            "report": "experiments/reports/checkpoint-security.json",
            "patch_id": "evidencedesk-accelerate-shards-v1",
            "scope": "local Accelerate backport; 15 offline loader regressions",
            "package_version_metadata": "preserved; version-based scanners still report advisory",
            "training_or_quality_re_evaluation": False,
        },
        "artifacts_sha256": hashes,
        "limitations": [
            "Synthetic annotation is not human adjudication.",
            "Development improvements do not certify production quality.",
            "The deployment also requires application/image/corpus revisions.",
            "Manifest hashes identify files, not an independent signature of trust.",
        ],
    }
    (root / "model-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"artifact_count": len(hashes), "candidate_promoted": False}))


if __name__ == "__main__":
    main()
