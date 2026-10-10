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
