"""Lazy, CPU-first adapters. Weight installation is a separate explicit setup command."""

from __future__ import annotations

import math
from collections.abc import Sequence

from .ranking import RankedEvidence

EMBEDDING_MODEL = "intfloat/multilingual-e5-small"
EMBEDDING_REVISION = "614241f622f53c4eeff9890bdc4f31cfecc418b3"
RERANKER_MODEL = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
RERANKER_REVISION = "1427fd652930e4ba29e8149678df786c240d8825"


class ModelTokenLimitError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class E5Encoder:
    dimensions = 384

    def __init__(
        self, *, local_files_only: bool = True, batch_size: int = 8, device: str = "cpu"
    ) -> None:
        if not 1 <= batch_size <= 32:
            raise ValueError("Batch de embedding inválido.")
        if device not in {"cpu", "cuda"}:
            raise ValueError("Dispositivo de embedding inválido.")
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(
            EMBEDDING_MODEL,
            revision=EMBEDDING_REVISION,
            device=device,
            local_files_only=local_files_only,
            trust_remote_code=False,
        )
        self._model.max_seq_length = 512
        self.batch_size = batch_size

    def encode_query(self, query: str) -> list[float]:
        return self._encode(["query: " + query], error_code="model_query_too_long")[0]

    def encode_passages(self, passages: Sequence[str]) -> list[list[float]]:
        if len(passages) > self.batch_size:
            raise ValueError("Faça chamadas em lotes limitados.")
        return self._encode(["passage: " + passage for passage in passages])

    def _encode(
        self, texts: Sequence[str], *, error_code: str = "evidence_requires_rechunking"
    ) -> list[list[float]]:
        if not texts:
            return []
        # Chunking must respect the same tokenizer; do not silently lose evidence.
        lengths = [
            len(self._model.tokenizer.encode(text, add_special_tokens=True)) for text in texts
        ]
        if any(length > 512 for length in lengths):
            raise ModelTokenLimitError(error_code)
        vectors = self._model.encode(
            list(texts),
            batch_size=self.batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        return vectors.tolist()


class LocalReranker:
    def __init__(
        self, *, local_files_only: bool = True, batch_size: int = 4, device: str = "cpu"
    ) -> None:
        if not 1 <= batch_size <= 16:
            raise ValueError("Batch de reranking inválido.")
        if device not in {"cpu", "cuda"}:
            raise ValueError("Dispositivo de reranking inválido.")
        from sentence_transformers import CrossEncoder

        self._model = CrossEncoder(
            RERANKER_MODEL,
            revision=RERANKER_REVISION,
            device=device,
            max_length=512,
            local_files_only=local_files_only,
            trust_remote_code=False,
        )
        self.batch_size = batch_size

    def rerank(self, query: str, candidates: Sequence[RankedEvidence]) -> list[RankedEvidence]:
        if len(candidates) > 20:
            raise ValueError("Reranking limitado a 20 candidatos.")
        if not candidates:
            return []
        scores = self.score_passages(query, [item.candidate.text for item in candidates])
        scored = sorted(
            ((float(score), item) for item, score in zip(candidates, scores, strict=True)),
            key=lambda pair: (-pair[0], pair[1].candidate.evidence_id),
        )
        return [item.model_copy(update={"reranker_score": score}) for score, item in scored]

    def score_passages(self, query: str, passages: Sequence[str]) -> list[float]:
        if len(passages) > 20:
            raise ValueError("Reranking limitado a 20 candidatos.")
        if not passages:
            return []
        if any(
            len(self._model.tokenizer.encode(query, passage, add_special_tokens=True)) > 512
            for passage in passages
        ):
            raise ModelTokenLimitError("evidence_requires_rechunking")
        scores = self._model.predict(
            [(query, passage) for passage in passages],
            batch_size=self.batch_size,
            show_progress_bar=False,
        )
        if any(not math.isfinite(float(score)) for score in scores):
            raise ValueError("Reranker devolveu score não finito.")
        return [float(score) for score in scores]
