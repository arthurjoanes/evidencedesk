"""Synthetic documents must not hide different temporal identities behind one hash."""

import hashlib
import importlib.util
import json
from pathlib import Path

from evidencedesk.ingestion.contracts import Manifest


def test_generated_packages_have_consistent_document_metadata_and_case_context(tmp_path):
    source = Path(__file__).resolve().parents[3] / "datasets/generate.py"
    spec = importlib.util.spec_from_file_location("demo_dataset_generator", source)
    assert spec is not None and spec.loader is not None
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    output = tmp_path / "generated"
    index = generator.generate(output, normal_orders=0)
    assert len(index["packages"]) == 6
    assert len(index["incidents"]) == 30
    assert index["counts"]["documents"] == 90
    identities = {}
    for package in index["packages"]:
        manifest = Manifest.model_validate_json((output / package["manifest"]).read_text())
        for entry in manifest.entries:
            content = (output / package["directory"] / entry.filename).read_bytes()
            assert len(content) == entry.byte_size
            assert hashlib.sha256(content).hexdigest() == entry.sha256
            if entry.kind != "document":
                continue
            identity = (package["tenant"], entry.sha256)
            metadata = json.dumps(entry.metadata, sort_keys=True)
            assert identities.setdefault(identity, metadata) == metadata
            case_id = entry.filename.split("-procedure-")[0].split("-retrospective.")[0]
            assert case_id in content.decode("utf-8")
    assert len(identities) == 90
