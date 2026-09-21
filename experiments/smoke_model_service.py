"""Real HTTP smoke with public synthetic input; no application or Azure credentials."""

import argparse
import json
import os
import time
from pathlib import Path

import httpx
from evidencedesk.retrieval.http_client import MODEL_SERVICE_URL, RemoteModels


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=Path("/runs/model-service-smoke.json")
    )
    args = parser.parse_args()
    token = os.environ.get(
        "ED_MODEL_SERVICE_TOKEN", "ed_model_local_demo_token_change_me"
    )
    started = time.monotonic()
    with httpx.Client(base_url=MODEL_SERVICE_URL, trust_env=False) as client:
        model = RemoteModels(client, token=token)
        query = model.encode_query("Como investigar um timeout de pagamento?")
        vectors = model.encode_passages(
            [
                "Um timeout não demonstra falha: o aceite pode ser desconhecido.",
                "A política de férias deve ser consultada no portal de pessoas.",
            ]
        )
        scores = model.score_passages(
            "Como investigar um timeout de pagamento?",
            [
                "Um timeout não demonstra falha: o aceite pode ser desconhecido.",
                "A política de férias deve ser consultada no portal de pessoas.",
            ],
        )
        assert len(query) == 384 and len(vectors) == 2
        assert scores[0] > scores[1]
        assert client.get("/metrics").status_code == 401
        metrics = client.get("/metrics", headers={"Authorization": "Bearer " + token})
        assert (
            metrics.status_code == 200
            and "ed_local_model_requests_total" in metrics.text
        )
        report = {
            "status": "passed",
            "transport": "real_internal_http",
            "dimensions": len(query),
            "passages": len(vectors),
            "scores": scores,
            "elapsed_seconds": time.monotonic() - started,
            "health": client.get("/healthz").json(),
            "provider_calls": 0,
        }
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
