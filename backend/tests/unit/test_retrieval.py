from datetime import UTC, datetime

import pytest

from evidencedesk.retrieval.chunking import chunk_text
from evidencedesk.retrieval.ranking import Candidate, RetrievalScope, fuse_rankings, select_context

AT = datetime(2026, 5, 1, tzinfo=UTC)


def candidate(
    evidence_id,
    *,
    document=None,
    tenant="tenant-a",
    snapshot="snapshot-1",
    role="applicable_procedure",
    valid_from=datetime(2026, 1, 1, tzinfo=UTC),
    valid_until=None,
    text="Trecho original.",
):
    return Candidate(
        evidence_id=evidence_id,
        tenant_id=tenant,
        evidence_snapshot_id=snapshot,
        document_id=document or evidence_id,
        text=text,
        temporal_role=role,
        valid_from=valid_from,
        valid_until=valid_until,
    )


def scope(purpose="applicable_procedure"):
    return RetrievalScope(
        tenant_id="tenant-a", evidence_snapshot_id="snapshot-1", purpose=purpose, incident_at=AT
    )


def test_foreign_tenant_is_rejected_instead_of_silently_postfiltered():
    with pytest.raises(ValueError, match="tenant/snapshot"):
        fuse_rankings([candidate("foreign", tenant="tenant-b")], [], scope())


def test_other_snapshot_is_rejected():
    with pytest.raises(ValueError):
        fuse_rankings([candidate("old", snapshot="snapshot-old")], [], scope())


def test_duplicate_ranks_do_not_inflate_score():
    item = candidate("a")
    result = fuse_rankings([item, item], [candidate("b")], scope())
    assert result[0].score == result[1].score


def test_hybrid_rank_rewards_appearance_in_both_lists_and_is_stable():
    first, second, common = candidate("a"), candidate("b"), candidate("c")
    result = fuse_rankings([first, common], [second, common], scope())
    assert result[0].candidate.evidence_id == "c"
    assert [item.candidate.evidence_id for item in result[1:]] == ["a", "b"]


def test_outdated_procedure_is_not_treated_as_current():
    obsolete = candidate("old", valid_until=datetime(2026, 4, 1, tzinfo=UTC))
    unknown = candidate("unknown", valid_from=None)
    assert fuse_rankings([obsolete, unknown], [], scope()) == []


def test_historical_artifact_is_still_searchable_as_history():
    obsolete = candidate(
        "old", role="historical_artifact", valid_until=datetime(2026, 4, 1, tzinfo=UTC)
    )
    assert fuse_rankings([obsolete], [], scope("historical_artifact"))[0].candidate == obsolete


def test_same_evidence_id_cannot_change_text_between_rankings():
    with pytest.raises(ValueError, match="conteúdo diferente"):
        fuse_rankings([candidate("same")], [candidate("same", text="Outra versão.")], scope())


def test_per_document_limit_prevents_one_document_dominating_context():
    items = [candidate(str(index), document="same-doc") for index in range(8)]
    assert len(fuse_rankings(items, [], scope(), per_document=2)) == 2


def test_context_budget_does_not_cut_text_while_preserving_original_locator():
    ranking = fuse_rankings(
        [candidate("a", text="texto extenso"), candidate("b", text="curto")], [], scope()
    )
    selected = select_context(ranking, max_characters=5)
    assert [item.candidate.evidence_id for item in selected] == ["b"]
    assert selected[0].candidate.text == "curto"


def test_chunking_preserves_offsets_and_honors_supplied_tokenizer_budget():
    text = "Primeiro parágrafo com evidência.\n\nSegundo parágrafo com outra evidência." * 10
    chunks = chunk_text(text, lambda value: len(value) + 2, max_tokens=50)
    assert "".join(chunk.text for chunk in chunks) == text
    assert all(chunk.text == text[chunk.char_start : chunk.char_end] for chunk in chunks)
    assert all(chunk.token_count <= 50 for chunk in chunks)


def test_chunking_does_not_accept_an_impossible_prefix_budget():
    with pytest.raises(ValueError, match="prefixo"):
        chunk_text("evidência", lambda value: len(value) + 100, max_tokens=10)
