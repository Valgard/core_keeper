"""Tests for decompile_structure.

The fixtures are small C# files rather than slices of the real decompile,
because what is under test is the shape the parser reports, and a 16 MB file
makes a failure unreadable. The real corpus has its own suite
(`test_structure_corpus.py`), which is where a claim about the *handbook* gets
checked.

Two distinctions carry the design and each has its own test: `None` means
nothing is known about a file while `Structure(elements=())` means it was
parsed and holds nothing, and `params` is `None` for a member that has no
parameter list at all while a nullary method's is `()`. Collapsing either turns
an open question into a silent verdict.
"""

import json

import decompile_structure
from citation_notation import Citation
from decompile_structure import Structure
from decompile_structure import describe
from decompile_structure import locate
from decompile_structure import structure_of

SIMPLE = """\
using System;

namespace Pug
{
    public class Foo
    {
        private int bar;

        public void Baz(int a, string b)
        {
            bar = a;
        }

        public void Baz()
        {
        }
    }
}
"""


def write(tmp_path, text, name="A.decompiled.cs"):
    """Write `text` to `name` under `tmp_path` and return the path."""
    path = tmp_path / name
    path.write_text(text)
    return path


def test_a_type_and_its_members_are_all_elements(tmp_path):
    """One element per type and one per member, so both anchor tiers exist."""
    s = structure_of(write(tmp_path, SIMPLE))
    named = [(e.type_name, e.member) for e in s.elements]
    assert ("Foo", None) in named
    assert ("Foo", "bar") in named
    assert named.count(("Foo", "Baz")) == 2


def test_members_carry_parameter_types_and_types_carry_none(tmp_path):
    """A nullary method's params are (), a field's and a type's are None."""
    s = structure_of(write(tmp_path, SIMPLE))
    by_name = {(e.member, e.params) for e in s.elements}
    assert ("Baz", ("int", "string")) in by_name
    assert ("Baz", ()) in by_name
    assert (None, None) in by_name
    assert ("bar", None) in by_name


def test_elements_are_ordered_and_members_nest_inside_their_type(tmp_path):
    """describe() picks the innermost element, which needs both to hold."""
    s = structure_of(write(tmp_path, SIMPLE))
    assert [e.start for e in s.elements] == sorted(e.start for e in s.elements)
    foo = next(e for e in s.elements if e.member is None)
    for member in (e for e in s.elements if e.member):
        assert foo.start <= member.start
        assert member.end <= foo.end


def test_an_explicit_interface_implementation_keeps_its_qualifier(tmp_path):
    """Two members share a name and a parameter list; only the qualifier differs.

    tree-sitter's `name` field returns `Serialize` for both, so a layer reading
    only that field would merge them and measure a citation to either against
    the other.
    """
    text = """\
class RpcSerializer : IRpcCommandSerializer<Rpc>
{
    public void Serialize(int a) { }
    void IRpcCommandSerializer<Rpc>.Serialize(int a) { }
}
"""
    s = structure_of(write(tmp_path, text))
    assert {e.member for e in s.elements if e.member} == {
        "Serialize",
        "IRpcCommandSerializer<Rpc>.Serialize",
    }


def test_an_empty_file_is_parsed_and_empty_not_unknown(tmp_path):
    """Review Focus 4: () is a verdict about the file, None is the absence of one."""
    assert structure_of(write(tmp_path, "")) == Structure(elements=(), error_ranges=())


def test_a_truncated_declaration_appears_in_error_ranges(tmp_path):
    """A caller may only say "not checking the location here" if it is told."""
    s = structure_of(write(tmp_path, "class Foo {\n    public void Baz(\n"))
    assert s is not None
    assert s.error_ranges


def test_a_non_csharp_file_is_unknown(tmp_path):
    """A `.prefab` is cited by line and has no elements to know about."""
    assert structure_of(write(tmp_path, "x: 1\n", name="Thing.prefab")) is None


def test_a_missing_path_is_unknown(tmp_path):
    """An unreadable path is the other way nothing is known."""
    assert structure_of(tmp_path / "absent.decompiled.cs") is None


def test_a_second_call_does_not_reparse(tmp_path, monkeypatch):
    """A cache hit does not reach the parser at all.

    The whole point: 7.8 s for the 25 cited assemblies is not a price a
    pre-commit gate can pay once per run, let alone per citation.
    """
    path = write(tmp_path, SIMPLE)
    cache = tmp_path / "cache"
    first = structure_of(path, cache_dir=cache)
    calls = []
    monkeypatch.setattr(decompile_structure, "_parse", lambda p: calls.append(p))
    assert structure_of(path, cache_dir=cache) == first
    assert calls == []


def test_a_changed_mtime_reparses(tmp_path):
    """A regenerated decompile must not keep serving the old index."""
    path = write(tmp_path, SIMPLE)
    cache = tmp_path / "cache"
    structure_of(path, cache_dir=cache)
    path.write_text(SIMPLE.replace("Baz", "Qux"))
    s = structure_of(path, cache_dir=cache)
    assert "Qux" in {e.member for e in s.elements if e.member}


def test_the_build_identity_is_recorded_but_not_part_of_the_key(tmp_path, monkeypatch):
    """The key is the file's identity; the build travels along for diagnostics.

    A decompile regenerated without a version change is the failure this
    arrangement exists to avoid, so the build must not be able to decide a hit.
    """
    path = write(tmp_path, SIMPLE)
    cache = tmp_path / "cache"
    structure_of(path, cache_dir=cache)
    entry = next(cache.iterdir())
    assert "build" in json.loads(entry.read_text())

    stored = json.loads(entry.read_text())
    stored["build"] = "9.9.9.9-ffff"
    entry.write_text(json.dumps(stored))
    calls = []
    monkeypatch.setattr(decompile_structure, "_parse", lambda p: calls.append(p))
    assert structure_of(path, cache_dir=cache) is not None
    assert calls == []


def test_an_entry_in_an_older_shape_is_reparsed_not_raised_on(tmp_path):
    """Review Focus 2: Element will gain fields, and old entries must not crash.

    The file's own identity is left intact, so the entry still looks fresh and
    the decoder is the thing under test. Blanking the size as well would make
    this pass through the staleness check without ever reaching it.
    """
    path = write(tmp_path, SIMPLE)
    cache = tmp_path / "cache"
    structure_of(path, cache_dir=cache)
    entry = next(cache.iterdir())
    stored = json.loads(entry.read_text())
    stored["elements"] = [{"unexpected": 1}]
    entry.write_text(json.dumps(stored))
    assert structure_of(path, cache_dir=cache) is not None


def test_a_truncated_entry_is_reparsed_not_read_as_complete(tmp_path):
    """Review Focus 5: the main checkout and a worktree share one cache directory."""
    path = write(tmp_path, SIMPLE)
    cache = tmp_path / "cache"
    expected = structure_of(path, cache_dir=cache)
    entry = next(cache.iterdir())
    half = entry.read_text()
    entry.write_text(half[: len(half) // 2])
    assert structure_of(path, cache_dir=cache) == expected


def test_the_environment_overrides_the_default_location(tmp_path, monkeypatch):
    """`.envrc` decides where the cache lives, so a machine can move it."""
    monkeypatch.setenv("CK_STRUCTURE_CACHE", str(tmp_path / "elsewhere"))
    structure_of(write(tmp_path, SIMPLE))
    assert (tmp_path / "elsewhere").is_dir()


def test_describe_prefers_the_member_over_the_type(tmp_path):
    """The innermost anchor wins, because it is exposed to the least."""
    s = structure_of(write(tmp_path, SIMPLE))
    body = SIMPLE.splitlines().index("            bar = a;") + 1
    c = describe(s, body, "A")
    assert (c.type_name, c.member) == ("Foo", "Baz(int, …)")


def test_describe_falls_back_to_the_type_between_members(tmp_path):
    """The type tier: inside a class, inside none of its members."""
    s = structure_of(write(tmp_path, SIMPLE))
    brace = SIMPLE.splitlines().index("    {") + 1
    c = describe(s, brace, "A")
    assert (c.type_name, c.member) == ("Foo", None)


def test_describe_falls_back_to_absolute_outside_every_type(tmp_path):
    """The escape hatch, and only here: a `using` line has nothing to name."""
    s = structure_of(write(tmp_path, SIMPLE))
    c = describe(s, 1, "A")
    assert (c.type_name, c.member, c.first) == (None, None, 1)


def test_describe_uses_the_bare_name_when_it_is_unique(tmp_path):
    """No parameter list where the name alone identifies the member."""
    s = structure_of(write(tmp_path, SIMPLE))
    field = SIMPLE.splitlines().index("        private int bar;") + 1
    assert describe(s, field, "A").member == "bar"


def test_describe_adds_the_shortest_unique_prefix_with_an_ellipsis(tmp_path):
    """One type separates these overloads, so the other two are elided."""
    text = """\
class Foo
{
    void Baz(int a, string b, bool c) { }
    void Baz(long a, string b, bool c) { }
}
"""
    s = structure_of(write(tmp_path, text))
    assert describe(s, 3, "A").member == "Baz(int, …)"


def test_describe_omits_the_ellipsis_when_the_prefix_is_the_whole_list(tmp_path):
    """Nothing was left out, so nothing claims to have been."""
    text = """\
class Foo
{
    void Baz(int a) { }
    void Baz(long a) { }
}
"""
    s = structure_of(write(tmp_path, text))
    assert describe(s, 3, "A").member == "Baz(int)"


def test_locate_is_the_inverse_of_describe(tmp_path):
    """Every line of the fixture round trips, the escape hatch included.

    The property that would have caught both throwaway recognisers' bugs the
    day they were written.
    """
    s = structure_of(write(tmp_path, SIMPLE))
    for line in range(1, len(SIMPLE.splitlines()) + 1):
        c = describe(s, line, "A")
        assert locate(s, c) == line, f"round trip broke at line {line}"


def test_locate_returns_none_for_an_absent_member(tmp_path):
    """A renamed or removed member is the third drift outcome, not a silent hit."""
    s = structure_of(write(tmp_path, SIMPLE))
    assert locate(s, Citation("A", "Foo", "Gone", 1, 1)) is None


def test_locate_returns_none_when_the_offset_leaves_the_element(tmp_path):
    """Review Focus 3: never clamp, never hand back a line outside the element."""
    s = structure_of(write(tmp_path, SIMPLE))
    assert locate(s, Citation("A", "Foo", "Baz(int, …)", 1, 400)) is None
    assert locate(s, Citation("A", "Foo", "Baz(int, …)", 400, 400)) is None


def test_locate_resolves_a_whole_element_citation_to_its_first_line(tmp_path):
    """`Assembly:Class` and `Assembly:Class:member` are grammar forms too.

    They carry no line, so locate has to answer with the element's own first
    line rather than raising on the missing offset.
    """
    s = structure_of(write(tmp_path, SIMPLE))
    assert locate(s, Citation("A", "Foo", None, None, None)) == 5
    assert locate(s, Citation("A", "Foo", "bar", None, None)) == 7


def test_a_namespace_level_member_falls_back_to_an_absolute_citation(tmp_path):
    """A member with no enclosing type cannot be spelled, so it is not claimed.

    `Assembly:member:N` would re-parse as the *type* tier and break the round
    trip, so describe reaches for the escape hatch instead of inventing a form.
    """
    s = structure_of(write(tmp_path, "delegate void Handler(int a);\n"))
    c = describe(s, 1, "A")
    assert (c.type_name, c.member, c.first) == (None, None, 1)
    assert locate(s, c) == 1
