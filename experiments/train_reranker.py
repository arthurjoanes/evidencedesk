"""Resource-bounded reranker experiment. No Azure calls and no implicit downloads."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import time
from pathlib import Path


def read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def validate_pairs(train: list[dict], dev: list[dict]) -> None:
    for column in ("query_group", "scenario_instance"):
        if {row[column] for row in train} & {row[column] for row in dev}:
            raise ValueError(f"Vazamento de {column} entre treino e dev.")
    train_lineages = {
        row["document_lineage"] for row in train if not row["shared_reference"]
    }
    dev_lineages = {
        row["document_lineage"] for row in dev if not row["shared_reference"]
    }
    if train_lineages & dev_lineages:
        raise ValueError(
            "Linhagem de documento de caso compartilhada entre treino/dev."
        )
    from build_pairs import SHARED_REFERENCES

    for row in train + dev:
        if (
            row["shared_reference"]
            and SHARED_REFERENCES.get(row["document_lineage"]) != row["passage"]
        ):
            raise ValueError(
                "Referência compartilhada precisa constar do catálogo congelado."
            )
    if len(train) < 1000 or len({row["query_group"] for row in train}) < 150:
        raise ValueError("Experimento completo requer diversidade/pairs declarados.")
    if any(row["label"] not in {0, 0.5, 1} for row in train + dev):
        raise ValueError("Rótulo fora da escala congelada.")


def audit_synthetic_labels(rows: list[dict]) -> dict:
    """Check the declared toy task; this is not human semantic adjudication."""
    hard_negatives = 0
    for row in rows:
        if row["label"] == 1 and row["focus_order"] not in row["passage"]:
            raise ValueError("Documento positivo não pertence ao pedido declarado.")
        if row["label_rationale"] == "different_order_hard_negative":
            hard_negatives += 1
            if row["focus_order"] in row["passage"] or row["label"] != 0:
                raise ValueError("Negativo difícil contém o pedido consultado.")
        if row["human_adjudicated"]:
            raise ValueError("Este dataset não pode se declarar adjudicado por humano.")
    return {
        "method": "synthetic_rule_audit_v2",
        "pairs_checked": len(rows),
        "hard_negatives_checked": hard_negatives,
        "human_adjudicated": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode", choices=["validate", "smoke", "train"], default="validate"
    )
    parser.add_argument("--data", type=Path, default=Path("experiments/data"))
    parser.add_argument("--output", type=Path, default=Path("experiments/runs"))
    parser.add_argument(
        "--protocol", type=Path, default=Path("experiments/protocol.json")
    )
    parser.add_argument("--allow-download", action="store_true")
    parser.add_argument("--synthetic-labels-audited", action="store_true")
    args = parser.parse_args()
    protocol_bytes = args.protocol.read_bytes()
    protocol = json.loads(protocol_bytes)
    train, dev = (
        read_jsonl(args.data / "train.jsonl"),
        read_jsonl(args.data / "dev.jsonl"),
    )
    validate_pairs(train, dev)
    audit = audit_synthetic_labels(train + dev)
    if args.mode == "validate":
        print(
            json.dumps(
                {
                    "status": "protocol_and_splits_valid",
                    "train_pairs": len(train),
                    "dev_pairs": len(dev),
                    "weights_loaded": False,
                }
            )
        )
        return
    if args.mode == "train" and not args.synthetic_labels_audited:
        parser.error(
            "Treino completo exige revisão do protocolo e --synthetic-labels-audited."
        )
    # Heavy libraries load only after explicit experiment mode.
    import resource

    import torch
    from sentence_transformers import (
        CrossEncoder,
        CrossEncoderTrainer,
        CrossEncoderTrainingArguments,
    )
    from sentence_transformers.cross_encoder.losses import BinaryCrossEntropyLoss
    from transformers import TrainerCallback

    from datasets import Dataset

    torch.set_num_threads(protocol["torch_threads"])
    if protocol["device"] == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("GPU do protocolo indisponível; sem fallback implícito.")
    run_name = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + args.mode
    run_dir = args.output / run_name
    run_dir.mkdir(parents=True, exist_ok=False)
    manifest = {
        "mode": args.mode,
        "status": "started",
        "protocol": protocol,
        "protocol_sha256": hashlib.sha256(protocol_bytes).hexdigest(),
        "dataset_sha256": hashlib.sha256(
            (args.data / "train.jsonl").read_bytes()
        ).hexdigest(),
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "annotation": "synthetic_not_human_adjudicated",
        "promotion": "not_evaluated",
        "label_audit": audit,
        "device": protocol["device"],
        "torch_version": torch.__version__,
        "cuda_runtime": torch.version.cuda,
        "gpu": torch.cuda.get_device_name() if protocol["device"] == "cuda" else None,
    }
    manifest_path = run_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    started = time.monotonic()
    deadline_reached = False

    class DeadlineCallback(TrainerCallback):
        def on_step_end(self, args, state, control, **kwargs):
            nonlocal deadline_reached
            if time.monotonic() - started > protocol["max_wall_seconds"]:
                deadline_reached = True
                control.should_training_stop = True
            return control

    try:
        model = CrossEncoder(
            protocol["base_model"],
            revision=protocol["base_revision"],
            device=protocol["device"],
            max_length=protocol["max_length"],
            local_files_only=not args.allow_download,
            trust_remote_code=False,
            model_kwargs={"torch_dtype": torch.float32},
        )
        selected = train[:16] if args.mode == "smoke" else train
        # Metadata columns are deliberately excluded: Trainer interprets non-label columns as inputs.
        training_data = Dataset.from_dict(
            {
                "query": [row["query"] for row in selected],
                "passage": [row["passage"] for row in selected],
                "label": [row["label"] for row in selected],
            }
        )
        training_args = CrossEncoderTrainingArguments(
            output_dir=str(run_dir / "checkpoint"),
            num_train_epochs=protocol["epochs"],
            learning_rate=protocol["learning_rate"],
            seed=protocol["seed"],
            per_device_train_batch_size=protocol["batch_size"],
            gradient_accumulation_steps=protocol["gradient_accumulation_steps"],
            max_steps=2 if args.mode == "smoke" else -1,
            save_strategy="no",
            logging_steps=1,
            report_to=[],
            use_cpu=protocol["device"] == "cpu",
            dataloader_num_workers=0,
            dataloader_pin_memory=False,
        )
        trainer = CrossEncoderTrainer(
            model=model,
            args=training_args,
            train_dataset=training_data,
            loss=BinaryCrossEntropyLoss(model),
            callbacks=[DeadlineCallback()],
        )
        training_result = trainer.train()
        model.save_pretrained(str(run_dir / "candidate"))
        manifest.update(
            status="resource_stopped"
            if deadline_reached
            else "smoke_completed"
            if args.mode == "smoke"
            else "trained_not_promoted",
            training_metrics=training_result.metrics,
            elapsed_seconds=time.monotonic() - started,
            peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
            peak_gpu_allocated_mib=torch.cuda.max_memory_allocated() / 2**20
            if protocol["device"] == "cuda"
            else None,
            peak_gpu_reserved_mib=torch.cuda.max_memory_reserved() / 2**20
            if protocol["device"] == "cuda"
            else None,
            steps=trainer.state.global_step,
        )
        import mlflow

        mlflow.set_tracking_uri(
            "sqlite:///" + str((args.output / "mlflow.db").resolve()).replace("\\", "/")
        )
        experiment_name = "evidencedesk-reranker-documents-v2"
        experiment = mlflow.get_experiment_by_name(experiment_name)
        experiment_id = (
            experiment.experiment_id
            if experiment
            else mlflow.create_experiment(
                experiment_name,
                artifact_location=(args.output / "mlflow-artifacts").resolve().as_uri(),
            )
        )
        mlflow.set_experiment(experiment_id=experiment_id)
        with mlflow.start_run(run_name=run_name):
            mlflow.log_params(
                {
                    "base_model": protocol["base_model"],
                    "base_revision": protocol["base_revision"],
                    "dataset_sha256": manifest["dataset_sha256"],
                    "mode": args.mode,
                    "seed": protocol["seed"],
                    "learning_rate": protocol["learning_rate"],
                }
            )
            mlflow.log_metrics(
                {
                    key: float(value)
                    for key, value in training_result.metrics.items()
                    if isinstance(value, (int, float))
                }
            )
            mlflow.log_artifact(str(args.protocol))
        # Publication is explicitly a different action, after paired retrieval and human gates.
    except Exception as exc:
        manifest.update(
            status="failed",
            error_type=type(exc).__name__,
            elapsed_seconds=time.monotonic() - started,
        )
        raise
    finally:
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "run": str(run_dir),
                "status": manifest["status"],
                "promotion": manifest["promotion"],
            }
        )
    )


if __name__ == "__main__":
    main()
