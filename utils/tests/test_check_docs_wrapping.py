"""Tests for check_docs_wrapping.

The cases are the mistakes this check was built after: a pattern substitution
that left a 142-column line, a first version that compared everything against a
flat 80 and reported hundreds of non-findings, and a paragraph running into a
fenced block that the rewrapper would have swallowed.
"""

import check_docs_wrapping as mod


def write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text)
    return p


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
