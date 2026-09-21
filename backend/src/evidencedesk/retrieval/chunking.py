"""Preserve canonical offsets while honoring the actual model tokenizer."""

from collections.abc import Callable
from dataclasses import dataclass

DOCUMENT_CHUNK_REVISION = "utf8-bytes-352-v2"
DOCUMENT_CHUNK_MAX_BYTES = 352


@dataclass(frozen=True)
class TextChunk:
    text: str
    char_start: int
    char_end: int
    token_count: int


def chunk_text(
    text: str, count_tokens: Callable[[str], int], *, max_tokens: int = 384
) -> list[TextChunk]:
    """Create non-overlapping spans; count_tokens must include the model's prefix/special tokens.

    Page boundaries belong to the extraction layer. Call once per canonical page and
    add its base offset when persisting locators. No gold/expected-answer input exists.
    """
    if max_tokens < 8:
        raise ValueError("Limite de chunk insuficiente.")
    chunks = []
    start = 0
    while start < len(text):
        # Bounded probes avoid repeatedly tokenizing an entire large document.
        end = min(len(text), start + max_tokens * 16)
        if count_tokens(text[start:end]) > max_tokens:
            low, high = start + 1, end
            while low < high:
                middle = (low + high + 1) // 2
                if count_tokens(text[start:middle]) <= max_tokens:
                    low = middle
                else:
                    high = middle - 1
            end = low
        # Prefer paragraphs/lines without discarding source characters.
        if end < len(text):
            boundary = text.rfind("\n\n", start + 1, end)
            if boundary < 0:
                boundary = text.rfind("\n", start + 1, end)
            if boundary >= 0 and boundary - start >= (end - start) // 3:
                end = boundary + 1
        token_count = count_tokens(text[start:end])
        # Prefix tokenization is not strictly monotonic for every tokenizer.
        while token_count > max_tokens and end > start + 1:
            end -= 1
            token_count = count_tokens(text[start:end])
        if token_count > max_tokens:
            raise ValueError("Um caractere mais o prefixo excede o orçamento do tokenizer.")
        chunk = text[start:end]
        chunks.append(TextChunk(chunk, start, end, token_count))
        start = end
    return chunks
