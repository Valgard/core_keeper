"""Unit tests for turning a Markdown changelog entry into a Workshop change note.

The failure this module exists to prevent is silent and permanent: a note sent
in the wrong dialect renders its own markup as text — `### Fixed` and `**bold**`
appear character for character — and a Workshop history entry can only be
corrected by hand, one web form at a time (`docs/ck/steam-workshop.md`). So the
tests here are about what the *reader* sees, not about the shape of the
conversion.

Two of them are the real ones: `test_a_bold_span_wrapped_over_two_lines_survives`
and its inline-code sibling. A line-wise replacer passes every other test in this
file and mangles those, and the corpus of real changelogs contains fourteen of
the first and two of the second.
"""

import re
from pathlib import Path

import pytest
import steam_bundle
import steam_changenote

# --- the version heading -----------------------------------------------------


def test_the_note_opens_with_the_version_as_a_heading():
    """The version heading is the only place a version can appear at all.

    SubmitItemUpdate takes the note and nothing else, so without it an
    entry shows only `Update: <date>` and cannot be told apart from
    another submitted the same day.
    """
    note = steam_changenote.render("1.4.0", "### Fixed\n\n- A thing.")

    assert note.startswith("[h2]1.4.0[/h2]\n")


def test_an_entry_with_an_empty_body_is_just_its_heading():
    """An empty body produces just the heading, not a trailing blank block.

    parse_changelog genuinely returns "" for a version heading with
    nothing under it, and the C# side accepts that.
    """
    assert steam_changenote.render("1.0.0", "") == "[h2]1.0.0[/h2]"


# --- block structure ---------------------------------------------------------


def test_a_section_heading_becomes_h3_under_the_version():
    """A `###` section heading converts to `[h3]`.

    That is the structural level BBCode has below the note's own `[h2]`
    version line.
    """
    assert steam_changenote.to_bbcode("### Fixed") == "[h3]Fixed[/h3]"


def test_every_heading_level_flattens_to_h3():
    """Every heading depth flattens to the same `[h3]`.

    There is only one structural level below the version, and an `[h1]`
    would otherwise outrank the note's own `[h2]` version line.
    """
    assert steam_changenote.to_bbcode("# Fixed") == "[h3]Fixed[/h3]"
    assert steam_changenote.to_bbcode("###### Fixed") == "[h3]Fixed[/h3]"


def test_consecutive_bullets_become_one_list():
    """Consecutive bullet lines become one `[list]` block, not a separate list per item."""
    assert steam_changenote.to_bbcode("- One.\n- Two.") == ("[list]\n[*] One.\n[*] Two.\n[/list]")


def test_a_blank_line_between_bullets_does_not_split_the_list():
    """A blank line between bullets does not split the list.

    Markdown calls that one (loose) list, and rendering it as two
    `[list]` blocks would show it as two lists.
    """
    assert steam_changenote.to_bbcode("- One.\n\n- Two.") == ("[list]\n[*] One.\n[*] Two.\n[/list]")


def test_a_sub_bullet_nests_inside_its_parent_item():
    """An indented sub-bullet nests inside its parent item's `[list]`.

    It must not flatten into a sibling at the top level.
    """
    note = steam_changenote.to_bbcode("- Parent.\n  - Child.\n- Sibling.")

    assert note == ("[list]\n[*] Parent.\n[list]\n[*] Child.\n[/list]\n[*] Sibling.\n[/list]")


def test_a_numbered_list_keeps_its_numbering():
    """A numbered list converts to `[olist]`, which keeps its numbering.

    Not to the unordered `[list]` bulleted markers use.
    """
    assert steam_changenote.to_bbcode("1. One.\n2. Two.") == (
        "[olist]\n[*] One.\n[*] Two.\n[/olist]"
    )


def test_blocks_are_separated_by_a_blank_line():
    """Consecutive blocks — a paragraph, a heading, a list — are joined by a blank line.

    They must not run together with no separator.
    """
    note = steam_changenote.to_bbcode("Preamble.\n\n### Fixed\n\n- A thing.")

    assert note == "Preamble.\n\n[h3]Fixed[/h3]\n\n[list]\n[*] A thing.\n[/list]"


def test_a_heading_needs_no_blank_line_to_end_the_paragraph_above_it():
    """A heading right under a paragraph, with no blank line between them, still ends the paragraph.

    It must not be read as the paragraph's own continuation.
    """
    assert steam_changenote.to_bbcode("Preamble.\n### Fixed") == ("Preamble.\n\n[h3]Fixed[/h3]")


# --- unwrapping --------------------------------------------------------------


def test_a_hard_wrapped_paragraph_becomes_one_line():
    """A hard-wrapped paragraph is joined into one line.

    Kept, its eighty-column breaks would ragged-edge the note in a
    browser column several times that wide, and mod.io — rendering the
    same source as Markdown — would show the same release differently.
    """
    assert steam_changenote.to_bbcode("One line\nand its continuation.") == (
        "One line and its continuation."
    )


def test_a_bullets_continuation_lines_join_its_item():
    """A bullet's wrapped continuation lines join back into that same item's text.

    Not starting a new item or a stray paragraph.
    """
    note = steam_changenote.to_bbcode("- A thing\n  that wrapped\n  twice.\n- Another.")

    assert note == "[list]\n[*] A thing that wrapped twice.\n[*] Another.\n[/list]"


def test_a_bold_span_wrapped_over_two_lines_survives():
    """A `**bold**` span wrapped across two source lines still converts.

    Verbatim from disable-durability 1.1.0. A line-wise replacer would see
    an odd number of asterisks on each line and emit neither tag, leaving
    the raw `**markup**` visible to the reader.
    """
    note = steam_changenote.to_bbcode(
        "- **In-game Enabled toggle.** Switch the mod on or off from **Options → Mod\n"
        "  Settings** without uninstalling it."
    )

    assert note == (
        "[list]\n"
        "[*] [b]In-game Enabled toggle.[/b] Switch the mod on or off from "
        "[b]Options → Mod Settings[/b] without uninstalling it.\n"
        "[/list]"
    )


def test_an_inline_code_span_wrapped_over_two_lines_survives():
    """A backtick code span wrapped across two source lines still converts.

    Verbatim from item-checklist 0.9.0, and the reason code spans are
    protected after unwrapping rather than before it.
    """
    note = steam_changenote.to_bbcode(
        "- Each concrete `(ingredient1,\n  ingredient2)` permutation is tracked."
    )

    assert (
        note
        == "[list]\n[*] Each concrete `(ingredient1, ingredient2)` permutation is tracked.\n[/list]"
    )


# --- inline conversion -------------------------------------------------------


def test_bold_becomes_b():
    """`**bold**` converts to `[b]…[/b]`."""
    assert steam_changenote.to_bbcode("A **loud** word.") == "A [b]loud[/b] word."


def test_italic_becomes_i():
    """`*italic*` converts to `[i]…[/i]`."""
    assert steam_changenote.to_bbcode("A *quiet* word.") == "A [i]quiet[/i] word."


def test_underscores_are_never_emphasis():
    """`_underscore_` and `__double__` emphasis is never converted.

    That dialect collides with identifiers these changelogs are full of,
    and converting it would silently italicise half a symbol name such as
    `requiredOn_2`.
    """
    assert steam_changenote.to_bbcode("A _quiet_ word.") == "A _quiet_ word."
    assert steam_changenote.to_bbcode("__loud__ words.") == "__loud__ words."


def test_inline_code_keeps_its_backticks_rather_than_becoming_a_code_tag():
    """An inline code span keeps its literal backticks rather than becoming `[code]`.

    That tag is block-level on Steam, so wrapping an inline identifier in
    it would split the sentence around every symbol name.
    """
    assert steam_changenote.to_bbcode("Patches `Player.Awake` on load.") == (
        "Patches `Player.Awake` on load."
    )


def test_markup_inside_inline_code_is_left_alone():
    """A `*` or `**` inside an inline code span is left alone, not read as emphasis.

    Code spans are protected before any inline rule runs.
    """
    assert steam_changenote.to_bbcode("Call `a * b` and `**p`.") == ("Call `a * b` and `**p`.")


def test_a_link_becomes_a_url_tag():
    """A Markdown link converts to `[url=target]text[/url]`."""
    assert steam_changenote.to_bbcode("See [the docs](https://example.com/x).") == (
        "See [url=https://example.com/x]the docs[/url]."
    )


def test_bold_inside_a_link_is_still_converted():
    """Bold markup inside a link's text still converts to `[b]`.

    It must not be swallowed whole by the link substitution that runs
    before it.
    """
    assert steam_changenote.to_bbcode("[**Loud**](https://example.com)") == (
        "[url=https://example.com][b]Loud[/b][/url]"
    )


def test_em_dashes_and_arrows_pass_through_unchanged():
    """Em dashes and arrows pass through unescaped.

    Unlike mod.io's own stored copy of the same changelog, which
    HTML-escapes `->` to `-&gt;` (see steam_backfill.divergence).
    """
    assert steam_changenote.to_bbcode("Options → Mod Settings — live.") == (
        "Options → Mod Settings — live."
    )


# --- the brackets decision ---------------------------------------------------


def test_a_bracket_that_is_not_a_link_is_left_exactly_as_written():
    """A `[bracket]` that is not a link (no following `(url)`) is left exactly as written.

    Deliberate: Steam's BBCode has no documented escape, so substituting
    anything here would be a guess about an undocumented parser, and a
    wrong guess turns text that renders correctly today into visible
    mangle.
    """
    assert steam_changenote.to_bbcode("Filed as [SB-367] upstream.") == (
        "Filed as [SB-367] upstream."
    )


def test_a_link_with_no_target_is_not_a_link():
    """A `[bracketed]` phrase with no `(target)` after it is left as plain text.

    Exactly like the non-link bracket case above, and not treated as a
    broken link.
    """
    assert steam_changenote.to_bbcode("[Keep a Changelog] is the format.") == (
        "[Keep a Changelog] is the format."
    )


# --- fenced code -------------------------------------------------------------


def test_a_fenced_block_becomes_a_code_block_and_is_not_unwrapped():
    """A fenced code block converts to `[code]`, the one place that block-level tag is correct.

    Its lines keep their own breaks and literal `**` markup rather than
    being unwrapped or inline-converted.
    """
    note = steam_changenote.to_bbcode("```csharp\nvar x = **1**;\nvar y = 2;\n```")

    assert note == "[code]\nvar x = **1**;\nvar y = 2;\n[/code]"


# --- against the real corpus -------------------------------------------------

_MODS = sorted(Path(__file__).resolve().parents[2].glob("*/CHANGELOG.md"))

_corpus = pytest.mark.skipif(
    len(_MODS) < 2,
    reason=(
        "fewer than two sibling mod repos with a CHANGELOG.md — the corpus guards below did NOT run"
    ),
)

# Markdown that would have rendered as itself. Deliberately not `[` or `` ` ``:
# both survive on purpose (see the two tests above). The `\[` in the asterisk
# lookbehind is what keeps BBCode's own `[*]` marker out of the net.
LEFTOVER = re.compile(r"(?m)^#{1,6} |\*\*|(?<![\w*\[])\*(?!\s)|^\s*[-+] |\]\(")


def _entries():
    for changelog in _MODS:
        for version, body in steam_bundle.changelog_entries(changelog.read_text()):
            yield changelog.parent.name, version, body


@_corpus
def test_no_real_entry_leaves_markdown_in_the_note():
    """The corpus is the test that matters: 51 entries across 13 mod repos.

    Nesting and wrapped spans occur there and nowhere in the invented cases
    above, and every one of them would be published permanently.
    """
    left = [
        f"{mod} {version}: {LEFTOVER.search(steam_changenote.render(version, body)).group(0)!r}"
        for mod, version, body in _entries()
        if LEFTOVER.search(steam_changenote.render(version, body))
    ]

    assert left == []


@_corpus
def test_every_real_entry_keeps_all_of_its_bullets():
    """Nothing is dropped on the way through — counted, not eyeballed.

    A block parser that mis-classifies a continuation line loses the item it
    belonged to, and the note still looks plausible.
    """
    for mod, version, body in _entries():
        bullets = len([line for line in body.splitlines() if re.match(r"^\s*[-*+] ", line)])
        note = steam_changenote.render(version, body)

        assert note.count("[*] ") == bullets, f"{mod} {version}"


@_corpus
def test_every_real_entry_balances_the_tags_it_opens():
    """Every opening tag across the real corpus has a matching closing tag.

    An unbalanced pair would render literally instead of formatting, or
    worse, swallow the rest of the note into the open tag's formatting.
    """
    for mod, version, body in _entries():
        note = steam_changenote.render(version, body)
        for tag in ("b", "i", "list", "olist", "h2", "h3", "url", "code"):
            opened = len(re.findall(rf"\[{tag}(?:[\]=])", note))

            assert opened == note.count(f"[/{tag}]"), f"{mod} {version}: {tag}"
