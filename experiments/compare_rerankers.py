"""Paired base/candidate evaluation over frozen, actually retrieved candidates."""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import random
import resource
import statistics
import time
from pathlib import Path

import torch
from evidencedesk.retrieval.local_models import RERANKER_MODEL, RERANKER_REVISION
from retrieve_dev import rank_metrics
from sentence_transformers import CrossEncoder


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * fraction))]


def evaluate(model_path: str, revision: str | None, retrieval: dict) -> dict:
    model = CrossEncoder(
        model_path,
        revision=revision,
        device="cuda",
        max_length=512,
        local_files_only=True,
        trust_remote_code=False,
    )
    first = next(iter(retrieval["cases"].values()))
    model.predict(
        [(first["query"], retrieval["documents"][key]) for key in first["hybrid"]],
        batch_size=4,
    )
    torch.cuda.synchronize()
    torch.cuda.reset_peak_memory_stats()
    cases = {}
    for key, case in retrieval["cases"].items():
        # No positive is added if retrieval missed it. IDs and labels never enter model input.
        candidates = case["hybrid"]
        pairs = [
            (case["query"], retrieval["documents"][identifier])
            for identifier in candidates
        ]
        times = []
        scores = []
        for _ in range(3):
            torch.cuda.synchronize()
            started = time.monotonic()
            scores = model.predict(
                pairs, batch_size=4, show_progress_bar=False
            ).tolist()
            torch.cuda.synchronize()
            times.append((time.monotonic() - started) * 1000)
        ranked = [
            identifier
            for _, identifier in sorted(
                zip(scores, candidates, strict=True),
                key=lambda item: (-item[0], item[1]),
            )
        ]
        cases[key] = {
            "family": case["family"],
            "ranked": ranked,
            "metrics": rank_metrics(ranked, case["relevance"]),
            "latency_median_ms": statistics.median(times),
        }
    result = {
        "model": model_path,
        "revision": revision,
        "cases": cases,
        "metrics": {
            metric: statistics.mean(case["metrics"][metric] for case in cases.values())
            for metric in ("ndcg_at_10", "recall_at_10", "mrr_at_10")
        },
        "latency_p95_ms": percentile(
            [case["latency_median_ms"] for case in cases.values()], 0.95
        ),
        "peak_gpu_allocated_mib": torch.cuda.max_memory_allocated() / 2**20,
        "process_peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        / 1024,
    }
    del model
    gc.collect()
    torch.cuda.empty_cache()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument(
        "--retrieval", type=Path, default=Path("/runs/retrieval-dev.json")
    )
    parser.add_argument(
        "--output", type=Path, default=Path("/runs/reranker-comparison.json")
    )
    args = parser.parse_args()
    retrieval = json.loads(args.retrieval.read_text())
    torch.set_num_threads(2)
    base = evaluate(RERANKER_MODEL, RERANKER_REVISION, retrieval)
    candidate = evaluate(str(args.candidate), None, retrieval)
    deltas = [
        candidate["cases"][key]["metrics"]["ndcg_at_10"]
        - base["cases"][key]["metrics"]["ndcg_at_10"]
        for key in base["cases"]
    ]
    randomizer = random.Random(42)
    bootstrap = [
        statistics.mean(randomizer.choices(deltas, k=len(deltas))) for _ in range(1000)
    ]
    gain = statistics.mean(deltas)
    ratio = candidate["latency_p95_ms"] / base["latency_p95_ms"]
    family_deltas = {
        family: statistics.mean(
            candidate["cases"][key]["metrics"]["ndcg_at_10"]
            - base["cases"][key]["metrics"]["ndcg_at_10"]
            for key, case in base["cases"].items()
            if case["family"] == family
        )
        for family in {case["family"] for case in base["cases"].values()}
    }
    report = {
        "protocol": json.loads(Path("experiments/protocol.json").read_text()),
        "retrieval_report_sha256": hashlib.sha256(
            args.retrieval.read_bytes()
        ).hexdigest(),
        "annotation": "synthetic_not_human_adjudicated",
        "reserved_evaluation_used": False,
        "base": base,
        "candidate": candidate,
        "paired_ndcg_at_10_gain": gain,
        "bootstrap_95_percent_interval": [
            percentile(bootstrap, 0.025),
            percentile(bootstrap, 0.975),
        ],
        "p95_latency_ratio": ratio,
        "group_deltas": family_deltas,
        "gates": {
            "gain_at_least_0_02": gain >= 0.02,
            "p95_latency_ratio_at_most_1_25": ratio <= 1.25,
            "process_peak_rss_at_most_3gib": candidate["process_peak_rss_mib"] <= 3072,
            "critical_semantic_regressions": "not_evaluated_requires_human_review",
            "human_semantic_gate": "pending",
        },
        "promotion": "not_promoted",
        "limitations": [
            "Synthetic templated relevance, not validated human judgments.",
            "Thirty new case groups with four known shared references; no unseen-domain claim.",
            "Warm GPU latency measured sequentially, three repeats/query; not production throughput.",
            "RSS peak is cumulative for the evaluation process, not an isolated per-model comparison.",
            "A candidate cannot recover a relevant document that the retriever did not return.",
        ],
    }
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "paired_ndcg_at_10_gain",
                    "bootstrap_95_percent_interval",
                    "p95_latency_ratio",
                    "gates",
                    "promotion",
                )
            }
        )
    )


if __name__ == "__main__":
    main()
