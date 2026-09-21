"""Real E5 + PostgreSQL FTS/pgvector retrieval before any relevance labels are scored."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from collections import defaultdict
from pathlib import Path

import psycopg
import torch
from evidencedesk.retrieval.lexical import LEXEME_PLAN_SQL
from evidencedesk.retrieval.local_models import EMBEDDING_REVISION, E5Encoder


def rank_metrics(ranked: list[str], relevance: dict[str, float], k: int = 10) -> dict:
    relevant = {key for key, value in relevance.items() if value > 0}
    gains = [relevance.get(key, 0.0) for key in ranked[:k]]
    ideal = sorted(relevance.values(), reverse=True)[:k]
    dcg = lambda values: sum(
        (2**grade - 1) / math.log2(index + 2) for index, grade in enumerate(values)
    )
    return {
        "recall_at_10": len(set(ranked[:k]) & relevant) / len(relevant),
        "ndcg_at_10": dcg(gains) / dcg(ideal),
        "mrr_at_10": next(
            (
                1 / (index + 1)
                for index, key in enumerate(ranked[:k])
                if key in relevant
            ),
            0.0,
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--planner", choices=["lexical-v1", "lexical-v2"], default="lexical-v2"
    )
    parser.add_argument(
        "--output", type=Path, default=Path("/runs/retrieval-dev-lexical-v2.json")
    )
    args = parser.parse_args()
    path = Path("experiments/data/dev.jsonl")
    rows = [json.loads(line) for line in path.read_text().splitlines() if line]
    documents = {row["document_lineage"]: row["passage"] for row in rows}
    queries = {
        row["query_group"]: {"query": row["query"], "family": row["scenario_family"]}
        for row in rows
    }
    torch.set_num_threads(2)
    encoder = E5Encoder(device="cuda", batch_size=8)
    identifiers = sorted(documents)
    vectors = []
    started = time.monotonic()
    for offset in range(0, len(identifiers), encoder.batch_size):
        batch = identifiers[offset : offset + encoder.batch_size]
        vectors.extend(encoder.encode_passages([documents[key] for key in batch]))
    query_vectors = {
        key: encoder.encode_query(value["query"]) for key, value in queries.items()
    }
    encode_seconds = time.monotonic() - started
    del encoder
    torch.cuda.empty_cache()
    results = {}
    # Dedicated ephemeral laboratory database: no application users, tenants, credentials or records.
    with psycopg.connect(
        "postgresql://experiment:synthetic_local_only@retrieval-db:5432/retrieval_lab",
        autocommit=True,
    ) as connection:
        connection.execute("CREATE EXTENSION IF NOT EXISTS vector")
        connection.execute(
            "CREATE TEMP TABLE corpus(id text PRIMARY KEY, content text, embedding vector(384), terms tsvector)"
        )
        with connection.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO corpus VALUES(%s,%s,%s::vector,to_tsvector('portuguese',%s))",
                [
                    (key, documents[key], json.dumps(vector), documents[key])
                    for key, vector in zip(identifiers, vectors, strict=True)
                ],
            )
        for key, item in queries.items():
            started = time.monotonic()
            if args.planner == "lexical-v2":
                planned = connection.execute(
                    LEXEME_PLAN_SQL.replace(":query", "%(query)s"),
                    {"query": item["query"]},
                ).fetchone()[0]
                lexical_sql = "SELECT id FROM corpus WHERE terms @@ to_tsquery('simple',%s) ORDER BY ts_rank_cd(terms,to_tsquery('simple',%s)) DESC,id LIMIT 30"
            else:
                planned = item["query"]
                lexical_sql = "SELECT id FROM corpus WHERE terms @@ websearch_to_tsquery('portuguese',%s) ORDER BY ts_rank_cd(terms,websearch_to_tsquery('portuguese',%s)) DESC,id LIMIT 30"
            lexical = [
                row[0]
                for row in connection.execute(
                    lexical_sql,
                    (planned, planned),
                )
            ]
            vector = [
                row[0]
                for row in connection.execute(
                    "SELECT id FROM corpus ORDER BY embedding <=> %s::vector,id LIMIT 30",
                    (json.dumps(query_vectors[key]),),
                )
            ]
            rrf: dict[str, float] = defaultdict(float)
            for ranking in (lexical, vector):
                for rank, identifier in enumerate(ranking, 1):
                    rrf[identifier] += 1 / (60 + rank)
            hybrid = sorted(rrf, key=lambda identifier: (-rrf[identifier], identifier))[
                :20
            ]
            results[key] = {
                **item,
                "lexical": lexical,
                "vector": vector,
                "hybrid": hybrid,
                "retrieval_ms": (time.monotonic() - started) * 1000,
            }
    # Only now attach synthetic labels for measurement. They never enter retrieval queries.
    scores = []
    for key, item in results.items():
        relevance = {
            row["document_lineage"]: row["label"]
            for row in rows
            if row["query_group"] == key
        }
        item["relevance"] = relevance
        item["metrics"] = {
            mode: rank_metrics(item[mode], relevance)
            for mode in ("lexical", "vector", "hybrid")
        }
        scores.append(item["metrics"])
    report = {
        "version": "synthetic-document-retrieval-v2",
        "lexical_revision": args.planner,
        "embedding_revision": EMBEDDING_REVISION,
        "dataset_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "annotation": "synthetic_not_human_adjudicated",
        "reserved_evaluation_used": False,
        "corpus_documents": len(documents),
        "queries": len(queries),
        "encode_seconds": encode_seconds,
        "retrieval": "PostgreSQL Portuguese FTS + exact pgvector cosine + RRF k60; top20 actual candidates",
        "summary": {
            mode: {
                metric: sum(row[mode][metric] for row in scores) / len(scores)
                for metric in scores[0][mode]
            }
            for mode in ("lexical", "vector", "hybrid")
        },
        "cases": results,
        "documents": documents,
    }
    destination = args.output
    destination.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(
        json.dumps(
            {
                "report": str(destination),
                "summary": report["summary"],
                "queries": len(queries),
            }
        )
    )


if __name__ == "__main__":
    main()
