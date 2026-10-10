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

from decompile_structure import Structure
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
