"""Unit tests for `discord_post.py` — the renderer, not the posts.

The 13 `discord-post.md` files are checked by `test_discord_post_content.py`;
everything here runs on synthetic input. That split is deliberate: a test that
reads the real posts fails when prose is edited, which says nothing about the
renderer, and it would only ever exercise the branches the current texts happen
to reach — the over-limit abort among them would never run at all.
"""

import pytest

import discord_post as dp


_ENV = {
    "MOD_NAME_ID": "reusable-cattle-box",
    "CK_GAME_VERSION": "1.2.1.5",
    "CK_DISCORD_TAGS": "Tweaks|Equipment",
}


def _render(markdown, **overrides):
    """render() with the parts under test spelled out and the rest boring."""
    args = dict(
        supported=["1.2.1.5"],
        known=["1.2.1.5"],
        tags=["Tweaks"],
        slug="reusable-cattle-box",
    )
    args.update(overrides)
    return dp.render(markdown, **args)


def test_version_line_collapses_to_minor_when_every_known_build_is_supported():
    supported = ["1.2.1.5", "1.2.1.0", "1.2.0.3"]
    known = ["1.2.1.5", "1.2.1.0", "1.2.0.3"]

    assert dp.version_line(supported, known) == (
        "**Compatible with Core Keeper 1.2.x** — tested on 1.2.0.3 through 1.2.1.5."
    )


def test_version_line_falls_back_to_a_span_when_a_known_build_is_unsupported():
    """`1.2.x` claims the whole minor, so it may only be printed once that is
    checked against the known builds — otherwise a mod that needs 1.2.1.3+
    would advertise compatibility with 1.2.0.3."""
    supported = ["1.2.1.5", "1.2.1.3"]
    known = ["1.2.1.5", "1.2.1.3", "1.2.0.3"]

    assert dp.version_line(supported, known) == (
        "**Compatible with Core Keeper 1.2.1.3 – 1.2.1.5**"
    )


# The two normalisation properties below were already implemented when their
# tests were written, so they are regression guards rather than test-driven
# behaviour. They stay because both are one edit away from breaking silently.


def test_builds_are_ordered_numerically_not_as_strings():
    supported = known = ["1.2.1.5", "1.2.1.10"]

    assert "tested on 1.2.1.5 through 1.2.1.10." in dp.version_line(supported, known)


def test_a_three_segment_build_is_the_same_build_as_its_padded_spelling():
    """Steam writes `0.7.4.0` where mod.io writes `0.7.4`."""
    assert dp._norm("0.7.4") == dp._norm("0.7.4.0")
    assert dp._norm("1.0.0") != dp._norm("1.0.0.1")


def test_render_drops_the_h1_because_it_is_the_thread_title():
    post = _render("# Some Heading\n\nBody text.\n")

    assert "Some Heading" not in post
    assert "Body text." in post


def test_render_unwraps_paragraphs_because_discord_does_not_reflow():
    """Every newline in the source would be a line break in the post: the
    prose is wrapped at ~78 columns like `modio-description.md`, and pasted
    verbatim it would arrive ragged."""
    post = _render("# T\n\nA sentence that the\nsource file wrapped.\n")

    assert "A sentence that the source file wrapped." in post


def test_render_keeps_list_items_on_their_own_lines():
    post = _render("# T\n\n- first\n- second\n")

    assert "- first\n- second" in post


def test_render_opens_with_the_version_line_the_channel_rules_ask_for():
    post = _render("# T\n\nBody.\n")

    assert post.startswith("**Compatible with Core Keeper 1.2.x**")


def test_render_suppresses_the_embed_on_source_but_not_on_download():
    """One link without angle brackets gives the post a single mod.io preview
    card; a second bare link would add a competing one."""
    post = _render("# T\n\nBody.\n", slug="reusable-cattle-box")

    assert post.endswith(
        "**Download:** https://mod.io/g/corekeeper/m/reusable-cattle-box\n"
        "**Source:** <https://github.com/Valgard/ck_reusable_cattle_box>"
    )


def test_render_rejects_a_tag_the_channel_does_not_offer():
    """A misspelled tag cannot be set in Discord's UI, so it would be noticed
    only while posting — after the text is already written."""
    with pytest.raises(ValueError, match="Tweak"):
        _render("# T\n\nBody.\n", tags=["Tweak"])


def test_render_refuses_an_over_long_post_instead_of_trimming_it():
    """Trimming automatically is what an earlier draft of this tool did, and it
    silently dropped a mod's Requirements section. Deciding what goes is the
    author's job."""
    with pytest.raises(ValueError, match="2000"):
        _render("# T\n\n" + "x" * 2100 + "\n")


def test_render_rejects_more_tags_than_discord_accepts():
    with pytest.raises(ValueError, match="5"):
        _render(
            "# T\n\nBody.\n",
            tags=["Tweaks", "Mining", "Cheats", "Combat", "Content", "Food"],
        )


def test_render_turns_h2_into_bold_because_discord_has_no_heading_levels():
    post = _render("# T\n\n## Requirements\n\nCoreLib.\n")

    assert "**Requirements**" in post
    assert "## Requirements" not in post


def test_a_repo_without_a_discord_post_is_skipped_not_an_error(tmp_path):
    """Most mods have no `discord-post.md` while this is being rolled out, and
    `CLIPublishHelper` treats a missing `modio-description.md` the same way."""
    assert dp.render_repo(tmp_path, _ENV, ["1.2.1.5"]) is None


def test_render_repo_reads_the_post_beside_the_mod(tmp_path):
    (tmp_path / "discord-post.md").write_text("# T\n\nBody.\n")

    post, tags, title = dp.render_repo(tmp_path, _ENV, ["1.2.1.5"])

    assert "Body." in post
    assert tags == ["Tweaks", "Equipment"]


def test_a_post_without_forum_tags_names_the_variable_it_wants(tmp_path):
    """Only mods that have a post need the tags, so the check cannot sit at
    start-up -- and a bare KeyError would not say where to put them."""
    (tmp_path / "discord-post.md").write_text("# T\n\nBody.\n")
    env = {k: v for k, v in _ENV.items() if k != "CK_DISCORD_TAGS"}

    with pytest.raises(ValueError, match="CK_DISCORD_TAGS"):
        dp.render_repo(tmp_path, env, ["1.2.1.5"])


def test_the_h1_becomes_the_thread_title_rather_than_being_discarded(tmp_path):
    """The heading is dropped from the body because Discord shows it as the
    thread title -- so it is authored, not derived from a directory name."""
    (tmp_path / "discord-post.md").write_text("# Reusable Cattle Box\n\nBody.\n")

    _, _, title = dp.render_repo(tmp_path, _ENV, ["1.2.1.5"])

    assert title == "Reusable Cattle Box"


def test_an_empty_tag_list_is_as_wrong_as_a_missing_one(tmp_path):
    """new_mod.py scaffolds CK_DISCORD_TAGS empty — a new mod cannot know its
    forum tags yet. Writing the post is the moment they have to be filled in."""
    (tmp_path / "discord-post.md").write_text("# T\n\nBody.\n")
    env = dict(_ENV, CK_DISCORD_TAGS="")

    with pytest.raises(ValueError, match="CK_DISCORD_TAGS"):
        dp.render_repo(tmp_path, env, ["1.2.1.5"])
