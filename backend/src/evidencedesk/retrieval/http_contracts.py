"""Internal model API. No tenant, database query, URL or tool execution is accepted."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

TextInput = Annotated[str, Field(min_length=1, max_length=12_000)]
FiniteFloat = Annotated[float, Field(allow_inf_nan=False)]
Vector = Annotated[list[FiniteFloat], Field(min_length=384, max_length=384)]


class Request(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: str = Field(pattern=r"^[a-f0-9]{40}$")


class EmbeddingRequest(Request):
    task: Literal["query", "passage"]
    texts: list[TextInput] = Field(min_length=1, max_length=8)


class RerankRequest(Request):
    query: str = Field(min_length=1, max_length=3000)
    passages: list[TextInput] = Field(min_length=1, max_length=20)


class EmbeddingResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: str
    dimensions: Literal[384] = 384
    vectors: list[Vector] = Field(min_length=1, max_length=8)


class RerankResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: str
    scores: list[FiniteFloat] = Field(min_length=1, max_length=20)


class ModelServiceError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable
