"""Tests for check_docs_wrapping.

The cases are the mistakes this check was built after: a pattern substitution
that left a 142-column line, a first version that compared everything against a
flat 80 and reported hundreds of non-findings, and a paragraph running into a
fenced block that the rewrapper would have swallowed.
"""

import check_docs_wrapping as mod


def write(tmp_path, name, text):
    """Write `text` to `tmp_path / name`, creating parent directories as needed.

    Returns the path, so a caller can hand it straight to mod.process()/main()
    without a separate variable.
    """
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def git(repo, *args):
    """Run git with GIT_* stripped, for the same reason the script does.

    A hook runs with GIT_DIR and GIT_INDEX_FILE set, and those outrank `-C`,
    so without this the test repo's commands reach the real repository
    instead. The suite passed outside the hook and failed inside it.
    """
    import os
    import subprocess

    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    subprocess.run(["git", "-C", str(repo), *args], check=True, env=env)


def git_repo(tmp_path):
    """Initialise tmp_path as an empty git repo with a usable commit identity.

    Only `init` plus `user.email`/`user.name` — no commit is made here, so a
    caller still has to `git(repo, "add", ...)` any file it writes before
    markdown_files() (which reads the index) can see it.
    """
    tmp_path.mkdir(parents=True, exist_ok=True)
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "t@t")
    git(tmp_path, "config", "user.name", "t")
    return tmp_path


class TestTargetWidth:
    """target_width(): a file is measured against its own median line, not a fixed convention."""

    def test_narrow_file_measured_as_eighty(self):
        """A file with no long lines reads as the 80-column default."""
        lines = ["x" * 78 for _ in range(20)]
        assert mod.target_width(lines) == 80

    def test_wide_file_keeps_its_own_width(self):
        """A file consistently wrapped near 88 is measured as 88, not forced to 80."""
        # two chapters here are written at ~88; forcing 80 would rewrite them
        lines = ["x" * 87 for _ in range(20)]
        assert mod.target_width(lines) == 88

    def test_too_few_lines_keeps_the_default(self):
        """Nine lines — one short of MIN_SAMPLE (10) — still fall back to the 80-column default.

        Pins the threshold itself, not merely "a small sample is ignored":
        the old fixture used only two 200-column lines, nowhere near
        MIN_SAMPLE, so it held for any threshold between 3 and 200 and never
        exercised the boundary at all. All nine lines here are 200 columns
        wide — if MIN_SAMPLE were anything at or below 9, that alone would
        already be enough evidence to read this as an intentionally wide file
        and return 88 instead of 80.
        """
        assert mod.target_width(["x" * 200 for _ in range(9)]) == 80

    def test_one_overlong_line_does_not_widen_a_narrow_file(self):
        """A single 200-column outlier must not raise the median it is then measured against."""
        # the defect must not raise the width it is measured against
        lines = ["x" * 76 for _ in range(9)] + ["y" * 200]
        assert mod.target_width(lines) == 80

    def test_a_bullet_heavy_file_is_measured_by_its_bullets(self):
        """A file made mostly of bullets is measured by its bullets, not its handful of prose.

        item-checklist/docs/roadmap.md is 831 lines wrapped at 88 with only six
        paragraphs. Sampling prose alone let those six decide, the width came
        out eight columns short, and every bullet in the file read as too long.
        """
        lines = ["One paragraph of prose."] + ["- " + "x" * 85 for _ in range(30)]
        assert mod.target_width(lines) == 88

    def test_a_fenced_block_does_not_vote_on_the_width(self):
        """Lines inside a code fence are excluded from the width sample."""
        # a code line rarely looks like a heading or a table, so the prose-only
        # sample counted it — and admitting list items would newly admit every
        # "- id: foo" in a YAML example
        lines = ["```yaml"] + ["- id: " + "x" * 90 for _ in range(30)] + ["```"]
        assert mod.target_width(lines) == 80

    def test_front_matter_does_not_count_as_prose(self):
        """YAML front matter between `---` markers is skipped, not sampled as prose."""
        lines = ["---", "description: " + "x" * 200, "---"] + ["y" * 76] * 20
        assert mod.target_width(lines) == 80


class TestIsProse:
    """is_prose(): a plain flowing-text line, as opposed to a heading, table, list, or quote."""

    def test_headings_tables_lists_quotes_are_not_prose(self):
        """None of a heading, table, list, quote, or indented line is prose."""
        for line in (
            "# H",
            "| a |",
            "- item",
            "* item",
            "> quote",
            "1. item",
            "  indented",
        ):
            assert not mod.is_prose(line), line

    def test_a_plain_sentence_is_prose(self):
        """An ordinary sentence is prose."""
        assert mod.is_prose("A plain sentence.")

    def test_leading_emphasis_is_prose_not_a_bullet(self):
        """A line opening with `*emphasis*` is prose, not a list item ending the paragraph early.

        "*pattern*, but see [the warning](x.md) before" being misread as a
        bullet ended the paragraph right there, putting the rest of it out of
        the wrapper's reach. An actual bullet still requires the marker to be
        followed by whitespace.
        """
        # "*pattern*, but see ..." ended the paragraph, putting the rest of it
        # out of the wrapper's reach
        assert mod.is_prose("*pattern*, but see [the warning](x.md) before")
        assert mod.is_prose("**bold start** of a continued sentence")
        assert not mod.is_prose("* an actual bullet")


class TestDefects:
    """defects(): the reasons a paragraph is mis-wrapped, or an empty list if it is fine."""

    def test_flags_a_line_far_past_the_target(self):
        """A line far past the target, with an earlier break available, is flagged."""
        para = ["word " * 30, "tail"]
        assert mod.defects(para, 80)

    def test_does_not_flag_an_unbreakable_long_token(self):
        """An unbreakable code span or link is not flagged — it has to overshoot."""
        # a code span or link cannot be split; the line has to overshoot
        para = ["`" + "x" * 120 + "`", "tail"]
        assert not mod.defects(para, 80)

    def test_does_not_flag_a_break_forced_by_the_next_word(self):
        """A short line is not flagged when the next word would not have fit on it anyway."""
        line = "x" * 60
        para = [line, "y" * 25 + " rest"]  # 60 + 1 + 25 = 86 > 80
        assert not mod.defects(para, 80)

    def test_flags_a_break_that_had_room_to_spare(self):
        """A short line is flagged when the next word would have fit on it with room left over."""
        para = ["x" * 40, "short rest"]  # 40 + 1 + 5 well under 80
        assert mod.defects(para, 80)

    def test_does_not_flag_a_line_that_ends_a_thought(self):
        """A line ending on a colon is not flagged — it opens a block on purpose."""
        para = ["Consider the following:", "next line here"]
        assert not mod.defects(para, 80)


class TestParagraphs:
    """paragraphs(): the (start, end) spans of prose outside code fences."""

    def test_a_fence_ends_a_paragraph(self):
        """A fenced code block ends the paragraph before it, rather than being swallowed into it.

        Regression: a fence line opens with a backtick, which is not itself a
        special leading character — the paragraph used to run straight into
        it, and a rewrap would then have destroyed the code block.
        """
        # regression: a fence line starts with a backtick, which is not a
        # special leading character — the paragraph used to swallow it and a
        # rewrap would have destroyed the code block
        lines = ["Text here.", "More text. Each:", "```json", '{"a": 1}', "```"]
        spans = list(mod.paragraphs(lines))
        assert spans == [(0, 2)]

    def test_content_inside_a_fence_is_never_a_paragraph(self):
        """Text that only looks like prose is not paragraphed while inside a fence."""
        lines = ["```", "this looks like prose but is code", "```"]
        assert list(mod.paragraphs(lines)) == []

    def test_front_matter_is_skipped(self):
        """YAML front matter is excluded from the paragraph spans paragraphs() yields."""
        lines = ["---", "name: x", "---", "Real prose here.", "and more of it."]
        assert list(mod.paragraphs(lines)) == [(3, 5)]


class TestProcess:
    """process(): check or, with fix=True, rewrite one file's wrapping."""

    def test_fix_rewraps_and_changes_only_whitespace(self, tmp_path):
        """Fixing a paragraph changes only whitespace; the words survive and fit the width."""
        import re

        original = "# T\n\n" + "word " * 40 + "\nend.\n"
        p = write(tmp_path, "a.md", original)
        _problems, rewrapped = mod.process(p, fix=True)
        assert rewrapped == 1
        after = p.read_text()
        assert re.sub(r"\s+", " ", after).strip() == re.sub(r"\s+", " ", original).strip()
        assert max(len(line) for line in after.splitlines()) <= 80

    def test_fix_leaves_a_code_block_intact(self, tmp_path):
        """A fenced code block is never rewrapped, even right after prose that is."""
        original = '# T\n\nA sentence. Each:\n```json\n{ "a": 1 }\n```\n'
        p = write(tmp_path, "a.md", original)
        mod.process(p, fix=True)
        assert p.read_text() == original

    def test_check_reports_without_writing(self, tmp_path):
        """fix=False reports what fix=True would act on, but leaves the file untouched."""
        original = "# T\n\n" + "word " * 40 + "\nend.\n"
        p = write(tmp_path, "a.md", original)
        problems, rewrapped = mod.process(p, fix=False)
        assert problems and rewrapped == 0
        assert p.read_text() == original

    def test_clean_file_reports_nothing(self, tmp_path):
        """A short, already-tidy paragraph produces no problems and no rewrap."""
        p = write(tmp_path, "a.md", "# T\n\nA short tidy paragraph that needs no help.\n")
        problems, rewrapped = mod.process(p, fix=False)
        assert problems == [] and rewrapped == 0

    def test_fix_then_check_reports_clean(self, tmp_path):
        """Running fix and then check on the same file leaves nothing left to report.

        fix mode always exits 0, and nothing else checks that what it
        flagged actually got fixed — a round trip is the only thing that
        would notice a fixer and a checker that had drifted apart.
        """
        # fix mode always exits 0, and nothing else checks that what it
        # flagged actually got fixed — a round trip is the only thing that
        # would notice a fixer and a checker that had drifted apart
        original = (
            "# T\n\n"
            + "word " * 40
            + "\n- "
            + "word " * 30
            + "end of a genuinely long list item.\n"
        )
        p = write(tmp_path, "a.md", original)
        mod.process(p, fix=True)
        problems, rewrapped = mod.process(p, fix=False)
        assert problems == [] and rewrapped == 0

    def test_check_mode_reports_an_overlong_single_line_paragraph(self, tmp_path):
        """A single over-long line is still reported, not skipped for having no break to get wrong.

        A substitution that joins two lines leaves a paragraph exactly one
        line long, and an earlier "shorter than two lines" skip hid the
        longest line in the file — which is the very defect this check was
        written for.
        """
        # a substitution that joins two lines leaves a paragraph one line long,
        # and the "shorter than two lines" skip then hid the longest line in
        # the file — which is the very defect this check was written for
        original = "# T\n\n" + "word " * 40 + "\n"
        p = write(tmp_path, "a.md", original)
        problems, rewrapped = mod.process(p, fix=False)
        assert rewrapped == 0
        assert any("a.md:3" in why for why in problems)

    def test_fix_rewraps_a_single_line_paragraph(self, tmp_path):
        """A single-line paragraph, not just a multi-line one, is rewrapped to fit the width."""
        original = "# T\n\n" + "word " * 40 + "\n"
        p = write(tmp_path, "a.md", original)
        _problems, rewrapped = mod.process(p, fix=True)
        assert rewrapped == 1
        assert max(len(line) for line in p.read_text().splitlines()) <= 80

    def test_a_lone_short_paragraph_stays_untouched(self, tmp_path):
        """A single short line is not itself a defect, and fix leaves the file unchanged."""
        # one line is not by itself a defect — only an over-long one is
        original = "# T\n\nA single tidy line that says all it needs to.\n"
        p = write(tmp_path, "a.md", original)
        problems, rewrapped = mod.process(p, fix=True)
        assert problems == [] and rewrapped == 0
        assert p.read_text() == original


class TestLinks:
    """A link split across lines is the defect this check exists for."""

    def test_a_line_ending_before_a_link_is_reported(self):
        """A line ending just before a link is reported as broken in the wrong place."""
        para = ["some words and then —", "[" + "x" * 70 + "](t.md) tail"]
        assert any("should have stayed" in why for _, why in mod.defects(para, 80))

    def test_split_link_is_reported(self):
        """A link whose text and target fall on two different lines is reported as a split link."""
        para = ["text with [a link", "text](target.md) after"]
        assert any("link split" in why for _, why in mod.defects(para, 80))

    def test_wrap_never_splits_a_link(self):
        """wrap_tokens() never produces a line with unbalanced brackets from a split link."""
        text = "word " * 12 + "[a fairly long link text](some/target.md) and more words after"
        for line in mod.wrap_tokens(text, 80):
            assert line.count("[") == line.count("]")

    def test_a_link_with_trailing_punctuation_still_counts(self):
        """A link with trailing punctuation, "[x](y),", is one token, not its own line."""
        # "[x](y)," is one token and must not be pushed onto its own line
        text = "short lead in " + "[" + "x" * 70 + "](t.md), tail words here"
        lines = mod.wrap_tokens(text, 80)
        assert lines[0].startswith("short lead in [")
        assert lines[0].rstrip().endswith("),")

    def test_link_stays_on_the_line_it_started(self):
        """wrap_tokens() keeps a link on the line it started on even if that line overshoots.

        The break falls after the link instead.
        """
        # the line may overshoot; the break falls after the link
        text = "short lead in " + "[" + "x" * 70 + "](t.md)" + " tail words here"
        lines = mod.wrap_tokens(text, 80)
        assert lines[0].startswith("short lead in [")
        assert lines[0].rstrip().endswith(")")
        assert lines[1].startswith("tail")


class TestListItems:
    """A bullet and its hanging indent have to survive a rewrap.

    A first attempt fed the whole first line into the wrapper *and* re-added
    the bullet as an indent, producing "- - text" and corrupting real files.
    """

    def test_bullet_appears_exactly_once(self, tmp_path):
        """Fix mode never emits "- -" or a doubled bullet marker, link included."""
        link = "[a very long link text indeed](some-target-file.md)"
        p = write(
            tmp_path,
            "a.md",
            f"# T\n\n- A bullet with plenty of words before {link} and after it.\n",
        )
        mod.process(p, fix=True)
        lines = p.read_text().splitlines()
        assert not any(line.lstrip().startswith("- -") for line in lines)
        assert sum(line.lstrip().startswith("- ") for line in lines) == 1

    def test_rewrap_preserves_the_words(self, tmp_path):
        """Rewrapping a list item changes only whitespace — the words survive, link included."""
        import re

        original = "# T\n\n- " + "word " * 30 + "[link](t.md) tail.\n"
        p = write(tmp_path, "a.md", original)
        mod.process(p, fix=True)
        assert re.sub(r"\s+", " ", p.read_text()).strip() == re.sub(r"\s+", " ", original).strip()

    def test_continuation_lines_keep_their_indent(self, tmp_path):
        """A list item's continuations keep the indent, never starting with a bullet."""
        p = write(tmp_path, "a.md", "# T\n\n- " + "word " * 30 + "end.\n")
        mod.process(p, fix=True)
        body = [
            line for line in p.read_text().splitlines() if line.strip() and not line.startswith("#")
        ]
        assert body[0].startswith("- ")
        for line in body[1:]:
            assert line.startswith("  ") and not line.lstrip().startswith("-")

    def test_a_list_after_a_code_fence_is_still_a_list(self, tmp_path):
        """A list item right after a closing fence is rewrapped as a list, not merged into it."""
        # the pixaki case: list items directly after a closing fence
        original = "# T\n\n```\ncode\n```\n\n- " + "word " * 30 + "[l](t.md) end.\n"
        p = write(tmp_path, "a.md", original)
        mod.process(p, fix=True)
        assert not any(line.lstrip().startswith("- -") for line in p.read_text().splitlines())

    def test_check_mode_reports_an_overlong_list_item(self, tmp_path):
        """Check mode reports the same over-long list item fix mode would rewrap.

        Regression: check mode used to skip straight past the defect the
        early-out any() had just found, so --fix rewrapped what check had
        reported clean.
        """
        # regression: check mode used to skip straight past the defect the
        # early-out any() had just found, so --fix rewrapped what check
        # reported clean
        original = "# T\n\n- " + "word " * 30 + "end of a genuinely long list item.\n"
        p = write(tmp_path, "a.md", original)
        problems, rewrapped = mod.process(p, fix=False)
        assert rewrapped == 0
        assert p.read_text() == original
        assert any("a.md:3" in why and "list item" in why for why in problems)

    def test_check_mode_is_silent_on_a_list_item_ending_on_a_link_and_a_full_stop(self, tmp_path):
        """A list item ending on a link and a period is not reported, per prose's exemption.

        The list path used to exempt a long line only via a trailing ")"; a
        link followed by punctuation ends on "." instead, so the list path
        has to match that shape too.
        """
        # the list path exempted a long line via a trailing ")"; a link
        # followed by punctuation ends on "." instead, and prose already
        # exempts that shape via LINK_TOKEN — the list path has to match it
        link = "[" + "a fairly long link text for this exact case" + "](target-file-name.md)"
        original = "# T\n\n- some lead-in words before the " + link + ".\n"
        p = write(tmp_path, "a.md", original)
        problems, rewrapped = mod.process(p, fix=False)
        assert problems == [] and rewrapped == 0

    def test_check_mode_reports_a_list_item_that_breaks_far_too_early(self, tmp_path):
        """A list item breaking far short of target is still reported, not excused as merely short.

        A substitution that *shortens* a line leaves the break in the wrong
        place. Prose has been checked for that all along; the list path only
        ever looked for lines that were too long, so a bullet left at 26
        columns beside 78-column neighbours used to read as correctly
        wrapped.
        """
        # a substitution that *shortens* a line leaves the break in the wrong
        # place. Prose has been checked for that all along; the list path only
        # ever looked for lines that were too long, so a bullet left at 26
        # columns beside 78-column neighbours read as correctly wrapped
        original = "# T\n\n- a short lead\n  " + "word " * 12 + "end.\n"
        p = write(tmp_path, "a.md", original)
        problems, rewrapped = mod.process(p, fix=False)
        assert rewrapped == 0
        assert p.read_text() == original
        assert any("a.md:3" in why and "list item" in why for why in problems)

    def test_fix_rejoins_a_list_item_that_broke_too_early(self, tmp_path):
        """Fix mode rejoins a list item whose break fell too early, not leaving it short."""
        original = "# T\n\n- a short lead\n  " + "word " * 12 + "end.\n"
        p = write(tmp_path, "a.md", original)
        _problems, rewrapped = mod.process(p, fix=True)
        assert rewrapped == 1
        assert p.read_text().splitlines()[2].startswith("- a short lead word")

    def test_check_mode_is_silent_on_a_list_item_that_ends_a_thought(self, tmp_path):
        """A list item introducing a block ("Consider the following:") is not reported as short.

        Prose's own exemption for this shape applies to list items too.
        """
        # the exemptions prose already has must come along, or every bullet
        # introducing a block would be reported
        original = "# T\n\n- Consider the following:\n  " + "word " * 12 + "end.\n"
        p = write(tmp_path, "a.md", original)
        problems, rewrapped = mod.process(p, fix=False)
        assert problems == [] and rewrapped == 0


class TestVisibleWidth:
    """A link is far longer in source than on screen.

    An editor that keeps the source line breaks renders the paragraph ragged
    because of it.
    """

    def test_a_link_counts_as_its_text(self):
        """visible_len() counts a link by its rendered text, not its full source markup."""
        assert mod.visible_len("[multiplayer and server](multiplayer-and-server.md)") == 22

    def test_emphasis_and_code_are_not_discounted(self):
        """Bold and code markers are not stripped from the width count.

        Bold renders wider, code renders in another face — dropping their
        markers would swap one wrong measure for another.
        """
        # bold renders wider, code renders in another face — dropping their
        # markers would swap one wrong measure for another
        assert mod.visible_len("**bold**") == 8
        assert mod.visible_len("`code`") == 6

    def test_masking_round_trips(self):
        """mask_links()/unmask_links() round-trip: masking then unmasking restores the text."""
        text = "see [a link](t.md) and [another one](u.md) here"
        masked, links = mod.mask_links(text)
        assert "](" not in masked
        assert mod.unmask_links(masked, links) == text

    def test_placeholder_has_the_visible_width(self):
        """A masked link's placeholder is exactly its visible length, for textwrap to measure by."""
        masked, _ = mod.mask_links("[multiplayer and server](multiplayer-and-server.md)")
        assert len(masked) == 22

    def test_wrapping_fills_the_visible_width(self):
        """wrap_tokens() fills to the visible width even when a link makes the source line longer.

        The source line may overshoot; what must not happen is a visible
        line that stops far short of the target.
        """
        link = "[a link with text](a-considerably-longer-target-file-name.md)"
        text = f"Start here {link} and then some more words that follow it along."
        lines = mod.wrap_tokens(text, 80)
        # the source line may overshoot; what must not happen is a visible line
        # that stops far short of the target
        assert all(mod.visible_len(line) <= 80 for line in lines)
        assert mod.visible_len(lines[0]) > 60


class TestFixpoint:
    """What the fixer produces, the checker must accept.

    Otherwise the gate blocks on a state --fix cannot leave: pulling a link
    onto the previous line makes that line overshoot, which forces the next
    line to start short — and the short-line rule then reported it.
    """

    # Read-only fixture data, never mutated or appended to below -- no
    # cross-instance sharing hazard for RUF012 to catch.
    CASES = [  # noqa: RUF012
        "One mechanic solves two problems: **click-outside-to-close** and "
        "[mouse-wheel ownership](#mouse-wheel-ownership-is-decided-by-the-hover-flag). "
        "Note the direction: screen to world is fine and useful; the dead end "
        "that [prefabs and rendering](prefabs-and-rendering.md) warns about is "
        "the opposite projection.",
        "Short lead " + "[" + "x" * 60 + "](t.md)" + " and a tail of ordinary words here.",
        "word " * 40,
        "See [a](b.md) — for one thing, and for [another](c.md#anchor).",
    ]

    def test_wrapping_output_is_accepted_by_the_checker(self):
        """Every fixture wrap_tokens() produces is accepted by defects() as clean at both widths."""
        for text in self.CASES:
            for width in (80, 88):
                wrapped = mod.wrap_tokens(text, width)
                assert mod.defects(wrapped, width) == [], (text[:40], width, wrapped)

    def test_fix_mode_leaves_a_file_the_checker_accepts(self, tmp_path):
        """Fix mode converges: the file it rewrites is reported clean by a fresh check run.

        A file's width is measured once, from the lines the run finds on
        entry — and the run then changes those lines. Rewrapping six long
        paragraphs adds a short tail to each, the median falls, and the file
        measured at 88 is now a file measured at 80, with lines the first
        pass was right to leave alone. caveling-divining-rod committed clean
        and was rejected by the gate it had just installed; this pins that
        the extra FIX_PASSES actually close that gap.
        """

        # A file's width is measured once, from the lines the run finds on
        # entry — and the run then changes those lines. Rewrapping six long
        # paragraphs adds a short tail to each, the median falls, and the file
        # measured at 88 is now a file measured at 80, with lines the first
        # pass was right to leave alone. caveling-divining-rod committed clean
        # and was rejected by the gate it had just installed.
        def line(n):
            words = ("word " * (n // 5 + 2))[:n]
            return words.rstrip() + "x" * (n - len(words.rstrip()))

        body = [line(150)] * 6 + [line(70)] * 5 + [line(95)]
        p = write(tmp_path, "a.md", "# T\n\n" + "\n\n".join(body) + "\n")
        assert mod.main(["prog", str(p)]) == 1, "input was meant to be defective"
        assert mod.main(["prog", "--fix", str(p)]) == 0
        assert mod.main(["prog", str(p)]) == 0

    def test_wrapping_is_idempotent(self):
        """Wrapping text twice yields the same lines — wrap_tokens() carries no drifting state."""
        for text in self.CASES:
            once = mod.wrap_tokens(text, 80)
            twice = mod.wrap_tokens(" ".join(line.strip() for line in once), 80)
            assert once == twice


class TestMarkdownFiles:
    """No test at all until now, unlike its sibling in check_docs_links.

    Both hooks are configured pass_filenames: false, which makes this the
    only path production ever takes — worth covering beyond the bare
    minimum, and this script's own FROZEN exclusion has no sibling
    equivalent to borrow coverage from.
    """

    def test_strips_inherited_git_env_so_dash_c_is_honoured(self, tmp_path, monkeypatch):
        """markdown_files() lists the requested repo's files, not one named by inherited GIT_DIR.

        A hook runs with both set, and they outrank `-C`; left inherited,
        this would list the "decoy" repository's files while asked for
        "real" — mixing the two repositories' files together.
        """
        # a hook runs with GIT_DIR/GIT_INDEX_FILE set, and those outrank -C;
        # inherited, listing "real" while GIT_DIR still points at "decoy"
        # mixes the two repositories' files together
        decoy = git_repo(tmp_path / "decoy")
        write(decoy, "decoy.md", "# Decoy\n")
        git(decoy, "add", "decoy.md")

        real = git_repo(tmp_path / "real")
        write(real, "real.md", "# Real\n")
        git(real, "add", "real.md")

        monkeypatch.setenv("GIT_DIR", str(decoy / ".git"))
        monkeypatch.setenv("GIT_INDEX_FILE", str(decoy / ".git" / "index"))
        assert [f.name for f in mod.markdown_files(real)] == ["real.md"]

    def test_ignores_files_git_is_told_to_ignore(self, tmp_path):
        """A file matched by .gitignore is excluded, even though it exists on disk."""
        repo = git_repo(tmp_path)
        write(repo, ".gitignore", "scratch/\n")
        write(repo, "scratch/notes.md", "# Ignored\n")
        assert mod.markdown_files(repo) == []

    def test_includes_untracked_files(self, tmp_path):
        """An untracked file is still included, not just a tracked one.

        A chapter written and not yet staged is the file most likely to
        need a wrapping fix — skipping it would report OK on exactly the
        wrong run.
        """
        # a chapter written and not yet staged is the file most likely to
        # need a wrapping fix — skipping it would report OK on exactly the
        # wrong run
        repo = git_repo(tmp_path)
        write(repo, "untracked.md", "# Not staged yet\n")
        assert [f.name for f in mod.markdown_files(repo)] == ["untracked.md"]

    def test_excludes_a_frozen_spec(self, tmp_path):
        """A tracked file under docs/specs/ is excluded.

        Reformatting a design spec would rewrite a record of a past decision
        for no reader's benefit.
        """
        # a design spec records a decision at a point in time; reformatting
        # one rewrites history for no reader's benefit
        repo = git_repo(tmp_path)
        write(repo, "docs/specs/plan.md", "# T\n\n" + "word " * 40 + "\nend.\n")
        git(repo, "add", "docs/specs/plan.md")
        assert mod.markdown_files(repo) == []

    def test_excludes_a_frozen_review_answer_key(self, tmp_path):
        """A tracked file under the ck-docs-review scoring directory is excluded.

        The scoring keys sit beside the fixtures they grade and are the same
        kind of object: a record a run is compared against. Freezing one
        half of an instrument and reformatting the other is the worst of
        both.
        """
        # the scoring keys sit beside the fixtures they grade and are the same
        # kind of object: a record a run is compared against. Freezing one half
        # of an instrument and reformatting the other is the worst of both
        repo = git_repo(tmp_path)
        key = ".claude/skills/ck-docs-review/scoring/planted-errors.md"
        write(repo, key, "# T\n\n" + "word " * 40 + "\nend.\n")
        git(repo, "add", key)
        assert mod.markdown_files(repo) == []

    def test_a_prefix_adjacent_directory_is_not_frozen(self, tmp_path):
        """A directory merely sharing a frozen prefix's letters is not itself treated as frozen.

        FROZEN checks startswith("docs/specs/") with the trailing slash — a
        naive prefix match without it would also catch this sibling
        directory, whose name merely starts with the same letters.
        """
        # FROZEN checks startswith("docs/specs/") with the trailing slash —
        # a naive prefix match without it would also catch this sibling
        # directory, whose name merely starts with the same letters
        repo = git_repo(tmp_path)
        write(repo, "docs/specification/plan.md", "# T\n\n" + "word " * 40 + "\nend.\n")
        git(repo, "add", "docs/specification/plan.md")
        assert [f.name for f in mod.markdown_files(repo)] == ["plan.md"]

    def test_a_tracked_but_deleted_file_is_silently_dropped(self, tmp_path):
        """A file tracked in the index but no longer on disk is silently dropped, not reported.

        Deliberate, unlike the sibling: check_docs_links surfaces this as
        "tracked but not on disk" because a dead link target is itself the
        defect it checks for. This script only has wrapping to check, and a
        deleted file has no content left to mis-wrap — pinning the current
        (silent) behaviour, not asserting it is the only sound choice.
        """
        # deliberate, unlike the sibling: check_docs_links surfaces this as
        # "tracked but not on disk" because a dead link target is itself the
        # defect it checks for. This script only has wrapping to check, and
        # a deleted file has no content left to mis-wrap — pinning the
        # current (silent) behaviour, not asserting it is the only sound
        # choice
        repo = git_repo(tmp_path)
        write(repo, "kept.md", "# Kept\n")
        write(repo, "gone.md", "# Gone\n")
        git(repo, "add", "kept.md", "gone.md")
        (repo / "gone.md").unlink()
        assert [f.name for f in mod.markdown_files(repo)] == ["kept.md"]


class TestMain:
    """main() and its exit code are what the pre-commit hook actually reads.

    A gate that finds a defect and exits 0 does not block anything.
    """

    def test_exits_zero_on_a_clean_file(self, tmp_path, capsys):
        """main() exits 0 and prints "OK" for a file with nothing to report."""
        p = write(tmp_path, "a.md", "# T\n\nA short tidy paragraph that needs no help.\n")
        assert mod.main(["prog", str(p)]) == 0
        assert "OK" in capsys.readouterr().out

    def test_exits_nonzero_on_a_mis_wrapped_file(self, tmp_path, capsys):
        """main() exits 1 and prints "mis-wrapped" when a file has a wrapping defect."""
        original = "# T\n\n" + "word " * 40 + "\nend.\n"
        p = write(tmp_path, "a.md", original)
        assert mod.main(["prog", str(p)]) == 1
        assert "mis-wrapped" in capsys.readouterr().out

    def test_a_directory_argument_is_scanned_as_a_root(self, tmp_path, capsys):
        """Passing a directory scans it as its own repository's root.

        check_docs_links already took a root, which is how a mod repo runs
        the parent's copy over its own tree. This script took files only
        and died on a directory, so it could not be wired in there at all.
        """
        # check_docs_links takes a root, which is how a mod repo runs the
        # parent's copy over its own tree. This script took files only and
        # died on a directory, so it could not be wired there at all
        repo = git_repo(tmp_path / "modrepo")
        write(repo, "docs/a.md", "# T\n\n" + "word " * 40 + "\nend.\n")
        git(repo, "add", "docs/a.md")
        assert mod.main(["prog", str(repo)]) == 1
        assert "docs/a.md" in capsys.readouterr().out

    def test_a_directory_root_finds_nothing_to_report_when_clean(self, tmp_path, capsys):
        """A directory resolving to a clean file reports OK, same as passing the file directly."""
        repo = git_repo(tmp_path / "modrepo")
        write(repo, "docs/a.md", "# T\n\nA short tidy paragraph.\n")
        git(repo, "add", "docs/a.md")
        assert mod.main(["prog", str(repo)]) == 0
        assert "OK" in capsys.readouterr().out

    def test_fix_mode_exits_zero_and_rewrites(self, tmp_path, capsys):
        """--fix exits 0 despite fixing a defect, and leaves the file's content changed."""
        original = "# T\n\n" + "word " * 40 + "\nend.\n"
        p = write(tmp_path, "a.md", original)
        assert mod.main(["prog", "--fix", str(p)]) == 0
        assert p.read_text() != original
