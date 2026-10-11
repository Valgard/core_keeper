"""Tests for citation_notation.

The cases are the five forms the grammar defines plus the third tier
(`Assembly:Class:7`), each checked in both directions at once: a form that
parses but does not render back is the failure that would make a migration
rewrite citations into something the checker no longer recognises.

The two single-case tests are the inputs that defeat a parser written over
punctuation rather than field position — a parameter list carrying a comma
inside a generic argument, and an explicitly interface-qualified member name
carrying a dot. Both are real shapes from the decompile, not invented ones.
"""

import pytest
from citation_notation import Citation
from citation_notation import find
from citation_notation import parse
from citation_notation import render
from citation_notation import tier

FORMS = [
    ("Pug.Other:Foo:Bar:7", Citation("Pug.Other", "Foo", "Bar", 7, 7)),
    ("Pug.Other:Foo:Bar:7-12", Citation("Pug.Other", "Foo", "Bar", 7, 12)),
    ("Pug.Other:Foo:Bar", Citation("Pug.Other", "Foo", "Bar", None, None)),
    ("Pug.Other:Foo", Citation("Pug.Other", "Foo", None, None, None)),
    ("Pug.Other:7", Citation("Pug.Other", None, None, 7, 7)),
    ("Pug.Other:Foo:7", Citation("Pug.Other", "Foo", None, 7, 7)),
    (
        "DedicatedServer/Pug.Other:Foo:Bar:7",
        Citation("DedicatedServer/Pug.Other", "Foo", "Bar", 7, 7),
    ),
    (
        "ControlMappingMenu.prefab:2459",
        Citation("ControlMappingMenu.prefab", None, None, 2459, 2459),
    ),
]


@pytest.mark.parametrize(("form", "expected"), FORMS)
def test_every_form_parses_and_renders_back(form, expected):
    """Each grammar form parses to its Citation and renders back unchanged."""
    assert parse(form) == expected
    assert render(expected) == form


def test_a_parameter_list_keeps_a_comma_inside_a_generic_argument():
    """A comma inside `Dictionary<int, string>` does not split the member.

    The case that refutes any parser phrased over punctuation: these are exactly
    the members whose signatures are worth spelling out, so losing them would
    cost the disambiguation the parameter list exists for.
    """
    form = "Pug.Other:Foo:Bar(Dictionary<int, string>, …):7"
    assert render(parse(form)) == form
    assert parse(form).member == "Bar(Dictionary<int, string>, …)"


def test_an_explicit_interface_qualifier_survives_the_round_trip():
    """A member name may carry an `Interface<T>.` qualifier and a dot with it.

    `RpcSerializer` holds both `Serialize` and
    `IRpcCommandSerializer<Rpc>.Serialize` with identical parameter types, so
    the qualifier is the only thing telling the two apart.
    """
    form = "Pug.Other:RpcSerializer:IRpcCommandSerializer<Rpc>.Serialize:3"
    assert render(parse(form)) == form


@pytest.mark.parametrize(
    ("form", "expected"),
    [
        ("Pug.Other:Foo:Bar:7", "member"),
        ("Pug.Other:Foo:7", "type"),
        ("Pug.Other:Foo", "type"),
        ("Pug.Other:7", "absolute"),
    ],
)
def test_tier_reports_the_anchor_not_the_line(form, expected):
    """The tier follows what is named, so a line does not change it."""
    assert tier(parse(form)) == expected


@pytest.mark.parametrize(
    "form",
    ["Pug.Other", ":419767", "Pug.Other:Foo:Bar:7-", "Pug.Other:Foo:Bar:12-7", ""],
)
def test_malformed_tokens_parse_to_none(form):
    """A token that is not a citation yields None rather than raising.

    The first two are the abbreviations `docs/ck/reverse-engineering.md` bans;
    the last two are a truncated and a reversed range. Checkers walk prose, so
    a near-miss is the normal case and must not be an exception.
    """
    assert parse(form) is None


@pytest.mark.parametrize(
    ("label", "fields"),
    [
        ("a member with no enclosing type", ("A", None, "Bar", 1, 1)),
        ("a location with only one end", ("A", "Foo", "Bar", None, 5)),
        ("a location with only a start", ("A", "Foo", "Bar", 5, None)),
        ("a reversed range", ("A", "Foo", "Bar", 3, 1)),
        ("a line before the first", ("A", "Foo", "Bar", 0, 0)),
        ("no assembly", ("", "Foo", "Bar", 1, 1)),
    ],
)
def test_a_citation_the_grammar_cannot_express_is_refused(label, fields):
    """Each of these used to be constructible, and each lied in its own way.

    Measured before the invariants existed: `first=None, last=5` made `locate`
    return the element's first line and `render` drop the end silently; a
    reversed range made `locate` return a line with no relation to the citation;
    a member with no type rendered `A:Bar:1`, which parses back as the *type*
    tier. Two of the three were silent, which is why this is a constructor
    check and not a documented convention.
    """
    with pytest.raises(ValueError):
        Citation(*fields)


def test_a_line_number_below_one_is_not_a_citation():
    """`A:0` is well-formed and names nothing; a 1-based grammar has no line 0."""
    assert parse("Pug.Other:0") is None
    assert parse("Pug.Other:Foo:Bar:0") is None


def test_finds_a_citation_in_either_grammar():
    """Both notations are live during the migration, so both must be found."""
    text = "see `Pug.Other:441234` and `Pug.Other:Foo:Bar:7` for the call"
    assert [token for token, _ in find(text)] == ["Pug.Other:441234", "Pug.Other:Foo:Bar:7"]


def test_finds_both_grammars_on_one_line_in_order():
    """A migrating chapter carries both, and the order is the report's order."""
    text = "`A:Foo:Bar:1` then `A:9` then `A:Baz:2-4`"
    assert [c.member for _, c in find(text)] == ["Bar", None, None]
    assert [c.first for _, c in find(text)] == [1, 9, 2]


def test_a_unity_fileid_is_not_a_citation():
    """`{fileID: 123456}` is Unity's own reference syntax, not a line reference."""
    assert find("the prefab points at `{fileID: 2456}`") == []


def test_a_doc_to_doc_line_reference_is_not_a_citation():
    """`docs/ck/index.md:12` names a file in this repository, not an assembly."""
    assert find("see `docs/ck/index.md:12`") == []


def test_a_malformed_token_is_dropped_not_returned():
    """`parse` is the judge; a candidate it refuses never reaches the caller.

    Reporting a malformed token is the style checker's job, and it reads
    `FINDER` directly for exactly that -- this function answers only with
    citations.
    """
    assert find("`Pug.Other:Foo:Bar:12-7`") == []


def test_text_with_no_citations_finds_nothing():
    """A backticked word and a bare number are prose, not references."""
    assert find("ordinary prose with a `backticked` word and a number 441234") == []
