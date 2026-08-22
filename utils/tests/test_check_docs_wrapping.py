"""Tests for check_docs_wrapping.

The cases are the mistakes this check was built after: a pattern substitution
that left a 142-column line, a first version that compared everything against a
flat 80 and reported hundreds of non-findings, and a paragraph running into a
fenced block that the rewrapper would have swallowed.
"""

import check_docs_wrapping as mod


def write(tmp_path, name, text):
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
    tmp_path.mkdir(parents=True, exist_ok=True)
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "t@t")
    git(tmp_path, "config", "user.name", "t")
    return tmp_path


class TestTargetWidth:
    def test_narrow_file_measured_as_eighty(self):
        lines = ["x" * 78 for _ in range(20)]
        assert mod.target_width(lines) == 80

    def test_wide_file_keeps_its_own_width(self):
        # two chapters here are written at ~88; forcing 80 would rewrite them
        lines = ["x" * 87 for _ in range(20)]
        assert mod.target_width(lines) == 88

    def test_too_few_lines_keeps_the_default(self):
        assert mod.target_width(["x" * 200, "y" * 200]) == 80

    def test_one_overlong_line_does_not_widen_a_narrow_file(self):
        # the defect must not raise the width it is measured against
        lines = ["x" * 76 for _ in range(9)] + ["y" * 200]
        assert mod.target_width(lines) == 80

    def test_front_matter_does_not_count_as_prose(self):
        lines = ["---", "description: " + "x" * 200, "---"] + ["y" * 76] * 20
        assert mod.target_width(lines) == 80


class TestIsProse:
    def test_headings_tables_lists_quotes_are_not_prose(self):
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
        assert mod.is_prose("A plain sentence.")

    def test_leading_emphasis_is_prose_not_a_bullet(self):
        # "*pattern*, but see ..." ended the paragraph, putting the rest of it
        # out of the wrapper's reach
        assert mod.is_prose("*pattern*, but see [the warning](x.md) before")
        assert mod.is_prose("**bold start** of a continued sentence")
        assert not mod.is_prose("* an actual bullet")


class TestDefects:
    def test_flags_a_line_far_past_the_target(self):
        para = ["word " * 30, "tail"]
        assert mod.defects(para, 80)

    def test_does_not_flag_an_unbreakable_long_token(self):
        # a code span or link cannot be split; the line has to overshoot
        para = ["`" + "x" * 120 + "`", "tail"]
        assert not mod.defects(para, 80)

    def test_does_not_flag_a_break_forced_by_the_next_word(self):
        line = "x" * 60
        para = [line, "y" * 25 + " rest"]  # 60 + 1 + 25 = 86 > 80
        assert not mod.defects(para, 80)

    def test_flags_a_break_that_had_room_to_spare(self):
        para = ["x" * 40, "short rest"]  # 40 + 1 + 5 well under 80
        assert mod.defects(para, 80)

    def test_does_not_flag_a_line_that_ends_a_thought(self):
        para = ["Consider the following:", "next line here"]
        assert not mod.defects(para, 80)


class TestParagraphs:
    def test_a_fence_ends_a_paragraph(self):
        # regression: a fence line starts with a backtick, which is not a
        # special leading character — the paragraph used to swallow it and a
        # rewrap would have destroyed the code block
        lines = ["Text here.", "More text. Each:", "```json", '{"a": 1}', "```"]
        spans = list(mod.paragraphs(lines))
        assert spans == [(0, 2)]

    def test_content_inside_a_fence_is_never_a_paragraph(self):
        lines = ["```", "this looks like prose but is code", "```"]
        assert list(mod.paragraphs(lines)) == []

    def test_front_matter_is_skipped(self):
        lines = ["---", "name: x", "---", "Real prose here.", "and more of it."]
        assert list(mod.paragraphs(lines)) == [(3, 5)]


class TestProcess:
    def test_fix_rewraps_and_changes_only_whitespace(self, tmp_path):
        import re

        original = "# T\n\n" + "word " * 40 + "\nend.\n"
        p = write(tmp_path, "a.md", original)
        problems, rewrapped = mod.process(p, fix=True)
        assert rewrapped == 1
        after = p.read_text()
        assert (
            re.sub(r"\s+", " ", after).strip() == re.sub(r"\s+", " ", original).strip()
        )
        assert max(len(l) for l in after.splitlines()) <= 80

    def test_fix_leaves_a_code_block_intact(self, tmp_path):
        original = '# T\n\nA sentence. Each:\n```json\n{ "a": 1 }\n```\n'
        p = write(tmp_path, "a.md", original)
        mod.process(p, fix=True)
        assert p.read_text() == original

    def test_check_reports_without_writing(self, tmp_path):
        original = "# T\n\n" + "word " * 40 + "\nend.\n"
        p = write(tmp_path, "a.md", original)
        problems, rewrapped = mod.process(p, fix=False)
        assert problems and rewrapped == 0
        assert p.read_text() == original

    def test_clean_file_reports_nothing(self, tmp_path):
        p = write(
            tmp_path, "a.md", "# T\n\nA short tidy paragraph that needs no help.\n"
        )
        problems, rewrapped = mod.process(p, fix=False)
        assert problems == [] and rewrapped == 0

    def test_fix_then_check_reports_clean(self, tmp_path):
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


class TestLinks:
    """A link split across lines is the defect this check exists for."""

    def test_a_line_ending_before_a_link_is_reported(self):
        para = ["some words and then —", "[" + "x" * 70 + "](t.md) tail"]
        assert any("should have stayed" in why for _, why in mod.defects(para, 80))

    def test_split_link_is_reported(self):
        para = ["text with [a link", "text](target.md) after"]
        assert any("link split" in why for _, why in mod.defects(para, 80))

    def test_wrap_never_splits_a_link(self):
        text = (
            "word " * 12
            + "[a fairly long link text](some/target.md) and more words after"
        )
        for line in mod.wrap_tokens(text, 80):
            assert line.count("[") == line.count("]")

    def test_a_link_with_trailing_punctuation_still_counts(self):
        # "[x](y)," is one token and must not be pushed onto its own line
        text = "short lead in " + "[" + "x" * 70 + "](t.md), tail words here"
        lines = mod.wrap_tokens(text, 80)
        assert lines[0].startswith("short lead in [")
        assert lines[0].rstrip().endswith("),")

    def test_link_stays_on_the_line_it_started(self):
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
        link = "[a very long link text indeed](some-target-file.md)"
        p = write(
            tmp_path,
            "a.md",
            f"# T\n\n- A bullet with plenty of words before {link} and after it.\n",
        )
        mod.process(p, fix=True)
        lines = p.read_text().splitlines()
        assert not any(l.lstrip().startswith("- -") for l in lines)
        assert sum(l.lstrip().startswith("- ") for l in lines) == 1

    def test_rewrap_preserves_the_words(self, tmp_path):
        import re

        original = "# T\n\n- " + "word " * 30 + "[link](t.md) tail.\n"
        p = write(tmp_path, "a.md", original)
        mod.process(p, fix=True)
        assert (
            re.sub(r"\s+", " ", p.read_text()).strip()
            == re.sub(r"\s+", " ", original).strip()
        )

    def test_continuation_lines_keep_their_indent(self, tmp_path):
        p = write(tmp_path, "a.md", "# T\n\n- " + "word " * 30 + "end.\n")
        mod.process(p, fix=True)
        body = [
            l for l in p.read_text().splitlines() if l.strip() and not l.startswith("#")
        ]
        assert body[0].startswith("- ")
        for line in body[1:]:
            assert line.startswith("  ") and not line.lstrip().startswith("-")

    def test_a_list_after_a_code_fence_is_still_a_list(self, tmp_path):
        # the pixaki case: list items directly after a closing fence
        original = "# T\n\n```\ncode\n```\n\n- " + "word " * 30 + "[l](t.md) end.\n"
        p = write(tmp_path, "a.md", original)
        mod.process(p, fix=True)
        assert not any(l.lstrip().startswith("- -") for l in p.read_text().splitlines())

    def test_check_mode_reports_an_overlong_list_item(self, tmp_path):
        # regression: check mode used to skip straight past the defect the
        # early-out any() had just found, so --fix rewrapped what check
        # reported clean
        original = "# T\n\n- " + "word " * 30 + "end of a genuinely long list item.\n"
        p = write(tmp_path, "a.md", original)
        problems, rewrapped = mod.process(p, fix=False)
        assert rewrapped == 0
        assert p.read_text() == original
        assert any("a.md:3" in why and "list item" in why for why in problems)

    def test_check_mode_is_silent_on_a_list_item_ending_on_a_link_and_a_full_stop(
        self, tmp_path
    ):
        # the list path exempted a long line via a trailing ")"; a link
        # followed by punctuation ends on "." instead, and prose already
        # exempts that shape via LINK_TOKEN — the list path has to match it
        link = (
            "["
            + "a fairly long link text for this exact case"
            + "](target-file-name.md)"
        )
        original = "# T\n\n- some lead-in words before the " + link + ".\n"
        p = write(tmp_path, "a.md", original)
        problems, rewrapped = mod.process(p, fix=False)
        assert problems == [] and rewrapped == 0


class TestVisibleWidth:
    """A link is far longer in source than on screen, and an editor that keeps
    the source line breaks renders the paragraph ragged because of it."""

    def test_a_link_counts_as_its_text(self):
        assert (
            mod.visible_len("[multiplayer and server](multiplayer-and-server.md)") == 22
        )

    def test_emphasis_and_code_are_not_discounted(self):
        # bold renders wider, code renders in another face — dropping their
        # markers would swap one wrong measure for another
        assert mod.visible_len("**bold**") == 8
        assert mod.visible_len("`code`") == 6

    def test_masking_round_trips(self):
        text = "see [a link](t.md) and [another one](u.md) here"
        masked, links = mod.mask_links(text)
        assert "](" not in masked
        assert mod.unmask_links(masked, links) == text

    def test_placeholder_has_the_visible_width(self):
        masked, _ = mod.mask_links(
            "[multiplayer and server](multiplayer-and-server.md)"
        )
        assert len(masked) == 22

    def test_wrapping_fills_the_visible_width(self):
        link = "[a link with text](a-considerably-longer-target-file-name.md)"
        text = f"Start here {link} and then some more words that follow it along."
        lines = mod.wrap_tokens(text, 80)
        # the source line may overshoot; what must not happen is a visible line
        # that stops far short of the target
        assert all(mod.visible_len(l) <= 80 for l in lines)
        assert mod.visible_len(lines[0]) > 60


class TestFixpoint:
    """What the fixer produces, the checker must accept.

    Otherwise the gate blocks on a state --fix cannot leave: pulling a link
    onto the previous line makes that line overshoot, which forces the next
    line to start short — and the short-line rule then reported it.
    """

    CASES = [
        "One mechanic solves two problems: **click-outside-to-close** and "
        "[mouse-wheel ownership](#mouse-wheel-ownership-is-decided-by-the-hover-flag). "
        "Note the direction: screen to world is fine and useful; the dead end "
        "that [prefabs and rendering](prefabs-and-rendering.md) warns about is "
        "the opposite projection.",
        "Short lead "
        + "["
        + "x" * 60
        + "](t.md)"
        + " and a tail of ordinary words here.",
        "word " * 40,
        "See [a](b.md) — for one thing, and for [another](c.md#anchor).",
    ]

    def test_wrapping_output_is_accepted_by_the_checker(self):
        for text in self.CASES:
            for width in (80, 88):
                wrapped = mod.wrap_tokens(text, width)
                assert mod.defects(wrapped, width) == [], (text[:40], width, wrapped)

    def test_wrapping_is_idempotent(self):
        for text in self.CASES:
            once = mod.wrap_tokens(text, 80)
            twice = mod.wrap_tokens(" ".join(l.strip() for l in once), 80)
            assert once == twice


class TestMarkdownFiles:
    """No test at all until now, unlike its sibling in check_docs_links —
    mirror the coverage that matters: the GIT_ strip and that ignored files
    stay out."""

    def test_strips_inherited_git_env_so_dash_c_is_honoured(
        self, tmp_path, monkeypatch
    ):
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
        repo = git_repo(tmp_path)
        write(repo, ".gitignore", "scratch/\n")
        write(repo, "scratch/notes.md", "# Ignored\n")
        assert mod.markdown_files(repo) == []


class TestMain:
    """main() and its exit code are what the pre-commit hook actually reads
    — a gate that finds a defect and exits 0 does not block anything."""

    def test_exits_zero_on_a_clean_file(self, tmp_path, capsys):
        p = write(
            tmp_path, "a.md", "# T\n\nA short tidy paragraph that needs no help.\n"
        )
        assert mod.main(["prog", str(p)]) == 0
        assert "OK" in capsys.readouterr().out

    def test_exits_nonzero_on_a_mis_wrapped_file(self, tmp_path, capsys):
        original = "# T\n\n" + "word " * 40 + "\nend.\n"
        p = write(tmp_path, "a.md", original)
        assert mod.main(["prog", str(p)]) == 1
        assert "mis-wrapped" in capsys.readouterr().out

    def test_fix_mode_exits_zero_and_rewrites(self, tmp_path, capsys):
        original = "# T\n\n" + "word " * 40 + "\nend.\n"
        p = write(tmp_path, "a.md", original)
        assert mod.main(["prog", "--fix", str(p)]) == 0
        assert p.read_text() != original
