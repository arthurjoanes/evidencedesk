import copy
import json
from html.parser import HTMLParser

import pytest

from evidencedesk.reviews.exporting import render_export, render_source_text


class MarkupText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text: list[str] = []
        self.tags: list[str] = []
        self.code_classes: list[str | None] = []
        self.pre_blocks: list[str] = []
        self.in_pre = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append(tag)
        if tag == "code":
            self.code_classes.append(dict(attrs).get("class"))
        if tag == "pre":
            self.in_pre = True
            self.pre_blocks.append("")

    def handle_endtag(self, tag: str) -> None:
        if tag == "pre":
            self.in_pre = False

    def handle_data(self, data: str) -> None:
        self.text.append(data)
        if self.in_pre:
            self.pre_blocks[-1] += data


def parsed_markup(value: str) -> MarkupText:
    parser = MarkupText()
    parser.feed(value)
    parser.close()
    return parser


@pytest.mark.parametrize(
    "source",
    [
        ' \r\n{"n":9007199254740993,"n":1.00e+02,"escaped":"\\u0041, { \\" ok",'
        '"unicode":"ação 東京","values":[true,false,null,-0]}\t',
        '{"same" \n : "same", "text": "true null -12 { }"}',
        '{"payload":"<img src=x onerror=alert(1)><script>alert(1)</script>&amp;"}',
        '"a standalone string"',
        "null",
        "true",
        "1e400",
        "9" * 5000,
        "[]",
        "{}",
    ],
)
def test_valid_json_preserves_every_character_and_escapes_markup(source):
    rendered = render_source_text(source)
    assert "\r" not in rendered  # CR must survive HTML's newline normalization.
    markup = parsed_markup(rendered)
    assert "".join(markup.text) == source
    assert markup.code_classes == ["language-json"]
    assert set(markup.tags) <= {"code", "span"}


@pytest.mark.parametrize(
    "source",
    [
        "\r\nTexto canônico sem JSON <script>alert(1)</script>&amp;",
        '{"incomplete":',
        '{"number":NaN}',
        '{"number":Infinity}',
        '{"number":-Infinity}',
        '{"trailing":1,}',
        "",
    ],
)
def test_plain_or_invalid_json_stays_literal(source):
    rendered = render_source_text(source)
    assert "\r" not in rendered
    markup = parsed_markup(rendered)
    assert "".join(markup.text) == source
    assert markup.code_classes == []
    assert markup.tags == ["span"]
    assert "json-" not in rendered


@pytest.fixture
def export_fixture():
    dossier = {
        "origin": "manual",
        "incident_id": "fixture-incident",
        "snapshot_id": "fixture-snapshot",
    }
    revision = {
        "number": 1,
        "id": "fixture-revision",
        "summary": "Fixture de apresentação — sem aprovação ou exportação operacional.",
        "claims": [],
        "missing_information": [],
        "suggested_checks": [],
        "impact_summary": {"amount_cents": 12500, "complete": True, "note": None},
        "review": {"note": "Fonte fictícia <script>não executar</script>"},
    }
    sources = {
        "fixture-json": {
            "title": "Evento fictício — somente teste de apresentação",
            "version": "1",
            "sha256": "fixture-hash-preservado",
            "locator": {"line": 2, "source": "fixture.jsonl"},
            "canonical_text": '\r\n{"amount_cents":9007199254740993,"amount_cents":1.00e+02,'
            '"event":"payment.confirmed","confirmed":true,"note":null,"escape":"\\u0041"}',
        },
        "fixture-text": {
            "title": "Texto fictício <img src=x>",
            "version": "2",
            "sha256": "outro-fixture-hash",
            "locator": {"page": 1},
            "canonical_text": "\nTexto original com <script>marcação literal</script> e &amp;.",
        },
    }
    return dossier, revision, sources


def test_export_colors_json_sources_locator_and_provenance_without_changing_data(export_fixture):
    dossier, revision, sources = export_fixture
    original = copy.deepcopy(export_fixture)
    exported = render_export(dossier, revision, sources)
    assert isinstance(exported, bytes)
    markup = parsed_markup(exported.decode())
    assert markup.pre_blocks[1:] == [source["canonical_text"] for source in sources.values()]
    assert json.loads(markup.pre_blocks[0]) == {
        "incident_id": dossier["incident_id"],
        "evidence_snapshot_id": dossier["snapshot_id"],
        "impact_summary": revision["impact_summary"],
        "review": revision["review"],
    }
    assert markup.code_classes == ["language-json"] * 4  # Provenance, two locators, JSON source.
    assert "script" not in markup.tags and "img" not in markup.tags
    assert "fixture-hash-preservado" in "".join(markup.text)
    assert "Localizador: " + json.dumps(sources["fixture-json"]["locator"]) in "".join(markup.text)
    assert export_fixture == original
    assert b"default-src 'none'" in exported
