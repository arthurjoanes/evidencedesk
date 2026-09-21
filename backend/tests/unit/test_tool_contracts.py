import pytest
from pydantic import ValidationError

from evidencedesk.config import Settings
from evidencedesk.investigations.tools import ReadArguments, SearchArguments, plan_investigation
from evidencedesk.model_runtime.release import freeze_release, load_release


@pytest.mark.parametrize("field", ["tenant_id", "actor_id", "sql", "url", "path", "command"])
def test_model_cannot_add_authority_to_tool_arguments(field):
    with pytest.raises(ValidationError):
        SearchArguments.model_validate({"query": "pagamento", field: "untrusted"})


def test_source_intervals_and_plans_are_bounded():
    with pytest.raises(ValidationError):
        ReadArguments(evidence_id="known", length=8001)
    with pytest.raises(ValidationError):
        plan_investigation(" " * 8)
    assert plan_investigation("Quais dados faltam?").questions == ("Quais dados faltam?",)


@pytest.mark.parametrize("mode", ["lexical", "hybrid", "hybrid_reranked"])
def test_retrieval_profile_and_revisions_are_frozen(mode):
    release = freeze_release(Settings(retrieval_mode=mode))
    assert load_release(release.model_dump()).retrieval_profile == mode
    assert bool(release.embedding_revision) == (mode != "lexical")
    assert bool(release.reranker_revision) == (mode == "hybrid_reranked")
    altered = release.model_dump() | {"embedding_revision": "unreviewed-weights"}
    from evidencedesk.errors import Problem

    with pytest.raises(Problem):
        load_release(altered)
