import pytest

from evidencedesk.errors import Problem
from evidencedesk.pagination import decode_named_cursor, encode_cursor, named_page


def test_named_cursor_roundtrips_unicode_and_remains_bound_to_context():
    context = {"tenant": "one", "user": "author", "operation": "collections"}
    name = "📚" * 120
    result = named_page(
        [{"name": name, "id": "a" * 200}, {"name": "next", "id": "next"}], 1, context
    )
    assert decode_named_cursor(result["next_cursor"], context) == (name, "a" * 200)
    with pytest.raises(Problem):
        decode_named_cursor(result["next_cursor"], context | {"user": "other"})


@pytest.mark.parametrize("position", ['"scalar"', '[null,"id"]', '["name",3]', '["name"]'])
def test_signed_but_malformed_named_cursor_is_rejected(position):
    context = {"operation": "collections"}
    with pytest.raises(Problem) as error:
        decode_named_cursor(encode_cursor(context, position), context)
    assert error.value.code == "cursor_context_changed"
