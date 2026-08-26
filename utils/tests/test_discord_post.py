"""Unit tests for `discord_post.py` — the renderer, not the posts.

The written `discord-post.md` files are checked by `test_discord_post_content.py`;
everything here runs on synthetic input. That split is deliberate: a test that
reads the real posts fails when prose is edited, which says nothing about the
renderer, and it would only ever exercise the branches the current texts happen
to reach — the over-limit abort among them would never run at all.
"""

import os
import pathlib

import discord_post as dp
import pytest

_ENV = {
    "MOD_NAME_ID": "probe-mod",
    "MOD_NAME": "ProbeMod",
    "CK_GAME_VERSION": "1.2.1.5",
    "CK_DISCORD_TAGS": "Tweaks|Equipment",
}


def _run_main(repo, monkeypatched, args=None):
    """main() with a controlled environment, since it reads os.environ."""
    saved = dict(os.environ)
    os.environ.clear()
    os.environ.update(monkeypatched)
    try:
        return dp.main([*(args or []), str(repo)])
    finally:
        os.environ.clear()
        os.environ.update(saved)


def _render(markdown, **overrides):
    """render() with the parts under test spelled out and the rest boring."""
    args = {
        "supported": ["1.2.1.5"],
        "known": ["1.2.1.5"],
        "tags": ["Tweaks"],
        "slug": "probe-mod",
    }
    args.update(overrides)
    return dp.render(markdown, **args)


def _repo(tmp_path, body="# T\n\nBody.\n"):
    """A repo with a post and the logo every mod has.

    The logo is not optional: it always leads the attachments, so a repo
    without one is a mod name spelled wrong rather than a mod with no images.
    """
    (tmp_path / "discord-post.md").write_text(body)
    logo = tmp_path / "unity" / "ProbeMod" / "Editor" / "logo.png"
    logo.parent.mkdir(parents=True)
    logo.write_bytes(b"\x89PNG")
    return tmp_path


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


def test_render_suppresses_the_embed_on_both_links():
    """A bare mod.io link renders mod.io's own corporate card — the platform's
    advertisement, not the mod — as the last thing in the post. Verified in the
    live channel on 2026-08-26."""
    post = _render("# T\n\nBody.\n", slug="probe-mod")

    assert post.endswith(
        "**Download:** <https://mod.io/g/corekeeper/m/probe-mod>\n"
        "**Source:** <https://github.com/Valgard/ck_probe_mod>"
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


def test_section_headings_stay_headings():
    """Discord renders `##` as a heading, and a heading is visibly different
    from the bold runs the prose itself uses — which the earlier rewrite to
    bold was not, so a section title and an emphasised term looked alike."""
    post = _render("# T\n\n## Requirements\n\nCoreLib.\n")

    assert "## Requirements" in post


def test_a_heading_is_not_folded_into_the_paragraph_under_it():
    """Unwrapping joins the lines of a block, and a heading followed directly by
    prose is one block."""
    post = _render("# T\n\n## Requirements\nCoreLib.\n")

    assert "## Requirements\nCoreLib." in post


def test_a_repo_without_a_post_or_tags_is_skipped_not_an_error(tmp_path):
    """A mod need not have a forum thread — that is a permanent state, not a
    stage of some rollout. Neither file nor tags means nobody started one."""
    env = {k: v for k, v in _ENV.items() if k != "CK_DISCORD_TAGS"}

    assert dp.render_repo(tmp_path, env, ["1.2.1.5"]) is None


def test_render_repo_reads_the_post_beside_the_mod(tmp_path):
    result = dp.render_repo(_repo(tmp_path), _ENV, ["1.2.1.5"])

    assert "Body." in result["body"]
    assert result["tags"] == ["Tweaks", "Equipment"]


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
    result = dp.render_repo(
        _repo(tmp_path, "# Probe Mod\n\nBody.\n"), _ENV, ["1.2.1.5"]
    )

    assert result["title"] == "Probe Mod"


def test_an_empty_tag_list_is_as_wrong_as_a_missing_one(tmp_path):
    """new_mod.py scaffolds CK_DISCORD_TAGS empty — a new mod cannot know its
    forum tags yet. Writing the post is the moment they have to be filled in."""
    (tmp_path / "discord-post.md").write_text("# T\n\nBody.\n")
    env = dict(_ENV, CK_DISCORD_TAGS="")

    with pytest.raises(ValueError, match="CK_DISCORD_TAGS"):
        dp.render_repo(tmp_path, env, ["1.2.1.5"])


def test_a_missing_game_version_says_so_instead_of_naming_a_key(tmp_path):
    """Running outside direnv is the usual way to hit this, and a bare KeyError
    prints just the variable name — which reads like the value, not the fault."""
    (tmp_path / "discord-post.md").write_text("# T\n\nBody.\n")
    env = {k: v for k, v in _ENV.items() if k != "CK_GAME_VERSION"}

    with pytest.raises(ValueError, match="CK_GAME_VERSION is not set"):
        dp.render_repo(tmp_path, env, ["1.2.1.5"])


def test_version_line_never_claims_a_minor_the_span_leaves():
    """The collapse used to read the minor off the lowest build alone, so a mod
    spanning 1.1 and 1.2 advertised '1.1.x' next to a span ending in 1.2.1.5 —
    the claim and its own evidence contradicting each other."""
    supported = ["1.1.0.1", "1.2.1.5"]
    known = ["1.1.0.1", "1.2.1.5", "1.2.1.0"]

    assert dp.version_line(supported, known) == (
        "**Compatible with Core Keeper 1.1.0.1 – 1.2.1.5**"
    )


def test_forum_tags_without_a_post_file_are_a_misconfiguration(tmp_path):
    """Skipping a repo without a post is right while one is not written yet —
    but filled-in tags say one was. The likely cause is the filename: the script
    is discord_post.py with an underscore, the file is discord-post.md with a
    hyphen."""
    (tmp_path / "discord_post.md").write_text("# T\n\nBody.\n")

    with pytest.raises(ValueError, match="discord-post.md"):
        dp.render_repo(tmp_path, _ENV, ["1.2.1.5"])


def test_a_build_the_version_list_does_not_know_is_refused(tmp_path):
    """CK_GAME_VERSION reaching a build that never shipped means a typo, and a
    typo only ever widens the '1.2.x' claim — set arithmetic cannot notice an
    extra element."""
    (tmp_path / "discord-post.md").write_text("# T\n\nBody.\n")
    env = dict(_ENV, CK_GAME_VERSION="1.2.1.5 1.2.1.55")

    with pytest.raises(ValueError, match="1.2.1.55"):
        dp.render_repo(tmp_path, env, ["1.2.1.5"])


def test_a_heading_further_down_the_file_is_not_the_thread_title(tmp_path):
    """`#\\s+` spans newlines, so a file starting with a bare '#' took the first
    prose line as the title while render() left it in the body — the same words
    twice, once as the thread name."""
    (tmp_path / "discord-post.md").write_text("#\n\nActually the first paragraph.\n")

    with pytest.raises(ValueError, match="# Title"):
        dp.render_repo(tmp_path, _ENV, ["1.2.1.5"])


def test_a_thread_title_over_discords_limit_is_refused(tmp_path):
    """Length and tag count are both enforced; the title was the one ceiling
    that was not, and it is the field Discord rejects first."""
    (tmp_path / "discord-post.md").write_text("# " + "T" * 101 + "\n\nBody.\n")

    with pytest.raises(ValueError, match="100"):
        dp.render_repo(tmp_path, _ENV, ["1.2.1.5"])


def test_a_post_of_exactly_the_limit_is_accepted():
    """The abort was only ever exercised from 100 characters past the ceiling,
    so `>` and `>=` were indistinguishable — and so was measuring the body
    without the generated link block, which the author cannot shorten."""
    filler = "x" * 10
    overhead = len(_render(f"# T\n\n{filler}\n")) - len(filler)

    exact = _render("# T\n\n" + "x" * (dp.LIMIT - overhead) + "\n")

    assert len(exact) == dp.LIMIT
    with pytest.raises(ValueError, match=str(dp.LIMIT)):
        _render("# T\n\n" + "x" * (dp.LIMIT - overhead + 1) + "\n")


def test_the_largest_allowed_number_of_tags_is_accepted():
    post = _render(
        "# T\n\nBody.\n", tags=["Tweaks", "Mining", "Cheats", "Combat", "Food"]
    )

    assert post


def test_a_missing_mod_name_id_says_so(tmp_path):
    """It builds both URLs, and was the one env var with no test."""
    (tmp_path / "discord-post.md").write_text("# T\n\nBody.\n")
    env = {k: v for k, v in _ENV.items() if k != "MOD_NAME_ID"}

    with pytest.raises(ValueError, match="MOD_NAME_ID is not set"):
        dp.render_repo(tmp_path, env, ["1.2.1.5"])


def test_a_blank_game_version_is_as_wrong_as_a_missing_one(tmp_path):
    """direnv exporting an empty value is the realistic failure, not an absent
    key — and the sibling tag check already treats the two alike."""
    (tmp_path / "discord-post.md").write_text("# T\n\nBody.\n")

    with pytest.raises(ValueError, match="CK_GAME_VERSION is not set"):
        dp.render_repo(tmp_path, dict(_ENV, CK_GAME_VERSION="   "), ["1.2.1.5"])


def test_spaces_around_the_tag_separator_are_not_part_of_the_tag(tmp_path):
    """`Tweaks | Equipment` is how a person writes it into an .envrc by hand."""
    env = dict(_ENV, CK_DISCORD_TAGS="Tweaks | Equipment")

    result = dp.render_repo(_repo(tmp_path), env, ["1.2.1.5"])

    assert result["tags"] == ["Tweaks", "Equipment"]


def test_main_puts_the_post_on_stdout_and_everything_else_on_stderr(tmp_path, capsys):
    """The documented contract: `discord_post.py | pbcopy` must copy the post
    and not the title or the character count."""
    _run_main(_repo(tmp_path, "# Some Mod\n\nBody.\n"), monkeypatched=_ENV)

    out, err = capsys.readouterr()
    assert out.startswith("**Compatible with Core Keeper")
    assert "Some Mod" in err and "Some Mod" not in out


def test_main_check_prints_nothing_on_stdout(tmp_path, capsys):
    _run_main(
        _repo(tmp_path, "# Some Mod\n\nBody.\n"), monkeypatched=_ENV, args=["--check"]
    )

    out, err = capsys.readouterr()
    assert out == ""
    assert "Some Mod" in err


def test_main_reports_a_bad_post_with_the_content_exit_code(tmp_path, capsys):
    """upload.sh waves 3 through and aborts on anything else, so the code is the
    difference between 'your prose is long' and 'the tooling is broken'."""
    (tmp_path / "discord-post.md").write_text("# Some Mod\n\nBody.\n")

    code = _run_main(tmp_path, monkeypatched=dict(_ENV, CK_DISCORD_TAGS="Nope"))

    assert code == dp.EXIT_CONTENT
    assert "Nope" in capsys.readouterr().err


def test_prose_under_a_heading_is_still_unwrapped():
    """The heading owns its line; the wrapped lines beneath it are one
    paragraph and must be joined like any other."""
    post = _render("# T\n\n## Requirements\nCoreLib, and\nMod Settings Menu.\n")

    assert "## Requirements\nCoreLib, and Mod Settings Menu." in post


def test_a_wrapped_list_item_stays_one_item():
    """The source wraps at ~78 columns like modio-description.md, so a long
    bullet spans lines; its continuation belongs to the bullet, not to a
    paragraph of its own."""
    post = _render("# T\n\n- Craft one box and reuse it\n  indefinitely.\n- Second.\n")

    assert "- Craft one box and reuse it indefinitely.\n- Second." in post


def test_forum_tags_come_from_the_data_file_not_the_code():
    """The channel's tag set belongs to somebody else's channel, so it is data
    the browser step can refresh — not a constant only a code edit can fix.
    Asserts the property this test names, not a snapshot of the current file:
    the ck-discord-post skill updates ck-discord-tags.json whenever the live
    channel diverges, and pytest runs as a pre-commit hook, so pinning the
    exact count would make the first legitimate reconciliation a commit the
    repo's own gate rejects."""
    tags = dp.forum_tags()

    assert "Misc / Other" in tags
    assert len(tags) > 10


def _mod_tree(tmp_path, *, media=None, extra_files=()):
    """A repo with the logo every mod has, plus whatever the test needs."""
    logo = tmp_path / "unity" / "ProbeMod" / "Editor" / "logo.png"
    logo.parent.mkdir(parents=True)
    logo.write_bytes(b"\x89PNG" + b"0" * 100)
    for name, size in extra_files:
        f = tmp_path / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"0" * size)
    env = dict(_ENV)
    if media is not None:
        env["CK_DISCORD_MEDIA"] = media
    return env


def test_the_logo_leads_even_when_no_media_is_configured(tmp_path):
    """Empty is a legitimate statement about a mod with nothing to show --
    unlike CK_DISCORD_TAGS, where empty is an omission."""
    env = _mod_tree(tmp_path, media="")

    attachments, follow_ups = dp.resolve_media(tmp_path, env, "ProbeMod")

    assert [p.name for p in attachments] == ["logo.png"]
    assert follow_ups == []


def test_paths_become_attachments_and_urls_become_follow_ups(tmp_path):
    """The value says which kind it is, so one variable keeps the order across
    both -- a second variable would force the author to classify up front."""
    env = _mod_tree(
        tmp_path,
        media="sources/a.png|https://example.invalid/clip.gif|sources/b.png",
        extra_files=[("sources/a.png", 10), ("sources/b.png", 10)],
    )

    attachments, follow_ups = dp.resolve_media(tmp_path, env, "ProbeMod")

    assert [p.name for p in attachments] == ["logo.png", "a.png", "b.png"]
    assert follow_ups == ["https://example.invalid/clip.gif"]


def test_a_missing_media_file_is_refused_before_the_browser_opens(tmp_path):
    """Finding this out in the post dialog means the text is already typed."""
    env = _mod_tree(tmp_path, media="sources/gone.png")

    with pytest.raises(ValueError, match="gone.png"):
        dp.resolve_media(tmp_path, env, "ProbeMod")


def test_more_attachments_than_discord_accepts_are_refused(tmp_path):
    """Ten is Discord's ceiling and the logo holds slot one, so nine remain."""
    names = [f"sources/f{i}.png" for i in range(10)]
    env = _mod_tree(
        tmp_path, media="|".join(names), extra_files=[(n, 10) for n in names]
    )

    with pytest.raises(ValueError, match="11 attachments"):
        dp.resolve_media(tmp_path, env, "ProbeMod")


def test_media_over_the_size_ceiling_is_refused(tmp_path, monkeypatch):
    """auto-rail-bridges has 38 MB GIFs sitting in sources/; attaching one
    fails in the dialog after everything else is already filled in.

    The ceiling is patched down rather than writing a 10 MB file: the test is
    about the comparison, not about the constant's value.
    """
    monkeypatch.setattr(dp, "SIZE_LIMIT", 200)
    env = _mod_tree(
        tmp_path,
        media="sources/huge.png",
        extra_files=[("sources/huge.png", 500)],
    )

    with pytest.raises(ValueError, match="exceeds"):
        dp.resolve_media(tmp_path, env, "ProbeMod")


def test_a_missing_logo_is_refused_because_it_always_leads(tmp_path):
    """Every mod has one; its absence means the mod name is wrong."""
    (tmp_path / "sources").mkdir()

    with pytest.raises(ValueError, match="logo"):
        dp.resolve_media(tmp_path, dict(_ENV), "ProbeMod")


def test_json_mode_emits_everything_the_browser_step_needs(tmp_path, capsys):
    """The skill consumes this. Parsing the human-facing stderr lines instead
    would break the first time one of them is reworded."""
    import json as _json

    (tmp_path / "discord-post.md").write_text("# Probe Mod\n\nBody.\n")
    logo = tmp_path / "unity" / "ProbeMod" / "Editor" / "logo.png"
    logo.parent.mkdir(parents=True)
    logo.write_bytes(b"\x89PNG")
    env = dict(_ENV, MOD_NAME="ProbeMod", CK_DISCORD_THREAD="https://discord.com/x")

    code = _run_main(tmp_path, monkeypatched=env, args=["--json"])

    assert code == 0
    doc = _json.loads(capsys.readouterr().out)
    assert doc["title"] == "Probe Mod"
    assert doc["tags"] == ["Tweaks", "Equipment"]
    assert doc["thread"] == "https://discord.com/x"
    assert doc["attachments"] == [str(logo.resolve())]
    assert doc["follow_ups"] == []
    assert doc["body"].startswith("**Compatible with Core Keeper")


def test_attachment_paths_are_absolute_even_from_a_relative_repo_argument(
    tmp_path, monkeypatch, capsys
):
    """`file_upload`, the browser tool the skill hands these to, requires an
    absolute path -- and so does README.md. Without resolving, a relative
    repo argument (`python3 discord_post.py --json some-mod`) leaked a
    relative path into the JSON instead."""
    import json as _json

    (tmp_path / "discord-post.md").write_text("# Probe Mod\n\nBody.\n")
    logo = tmp_path / "unity" / "ProbeMod" / "Editor" / "logo.png"
    logo.parent.mkdir(parents=True)
    logo.write_bytes(b"\x89PNG")
    monkeypatch.chdir(tmp_path.parent)

    code = _run_main(
        tmp_path.name, monkeypatched=dict(_ENV, MOD_NAME="ProbeMod"), args=["--json"]
    )

    assert code == 0
    doc = _json.loads(capsys.readouterr().out)
    assert doc["attachments"] == [str(logo.resolve())]
    assert pathlib.Path(doc["attachments"][0]).is_absolute()


def test_json_mode_reports_no_thread_as_null_not_as_an_empty_string(tmp_path, capsys):
    """null is 'no thread yet, create a post'; the skill branches on it."""
    import json as _json

    (tmp_path / "discord-post.md").write_text("# Probe Mod\n\nBody.\n")
    logo = tmp_path / "unity" / "ProbeMod" / "Editor" / "logo.png"
    logo.parent.mkdir(parents=True)
    logo.write_bytes(b"\x89PNG")

    _run_main(tmp_path, monkeypatched=dict(_ENV, MOD_NAME="ProbeMod"), args=["--json"])

    assert _json.loads(capsys.readouterr().out)["thread"] is None


_CHANGELOG = """# Changelog

Preamble that is not part of any release.

## [1.4.0] - 2026-08-12

Tools stop wearing down twice as slowly.

### Changed

- The toggle now applies without a restart.
- Accented characters come from the font mod.

## [1.3.5] - 2026-08-06

### Fixed

- Declared as client-only.
"""


def test_update_takes_the_topmost_entry_and_nothing_below_it():
    version, comment = dp.render_update(
        _CHANGELOG, supported=["1.2.1.5"], known=["1.2.1.5"], slug="probe-mod"
    )

    assert version == "1.4.0"
    assert "applies without a restart" in comment
    assert "client-only" not in comment


def test_update_drops_the_section_headings_but_keeps_the_bullets():
    """'### Changed' is changelog scaffolding; in a chat message it reads as a
    heading with one line under it."""
    _, comment = dp.render_update(
        _CHANGELOG, supported=["1.2.1.5"], known=["1.2.1.5"], slug="probe-mod"
    )

    assert "### Changed" not in comment
    assert "- The toggle now applies without a restart." in comment


_CHANGELOG_TIGHT_HEADING = """# Changelog

## [1.0.0] - 2026-08-08

### Added
- Bullet one.
- Bullet two.
"""


def test_update_keeps_the_bullets_when_the_heading_has_no_blank_line_after_it():
    """refill-ore-boulders, rebalance-key-crafting and auto-rail-bridges write
    their changelogs this way: '### Added' immediately followed by its
    bullets, with no blank line between them. Blocks are split on blank
    lines, so heading and bullets are one block -- and the block-level filter
    used to drop the whole thing, silently deleting the entry."""
    _, comment = dp.render_update(
        _CHANGELOG_TIGHT_HEADING,
        supported=["1.2.1.5"],
        known=["1.2.1.5"],
        slug="probe-mod",
    )

    assert "### Added" not in comment
    assert "- Bullet one." in comment
    assert "- Bullet two." in comment


def test_update_opens_by_naming_the_version():
    """The compatibility line is what the channel's posting rules ask to see
    in the first lines -- so it must actually be there, on its own line, not
    just anywhere after the version literal `startswith` alone would allow."""
    _, comment = dp.render_update(
        _CHANGELOG, supported=["1.2.1.5"], known=["1.2.1.5"], slug="probe-mod"
    )

    assert comment.startswith("**Version 1.4.0**")
    assert comment.split("\n")[1] == dp.version_line(["1.2.1.5"], ["1.2.1.5"])


def test_update_refuses_an_over_long_comment_instead_of_trimming_it():
    long_entry = "## [2.0.0] - 2026-08-26\n\n" + ("word " * 500)

    with pytest.raises(ValueError, match="characters"):
        dp.render_update(
            long_entry, supported=["1.2.1.5"], known=["1.2.1.5"], slug="probe-mod"
        )


def test_a_changelog_without_a_release_entry_says_so():
    with pytest.raises(ValueError, match="no '## \\[x.y.z\\]' entry"):
        dp.render_update(
            "# Changelog\n\nNothing released yet.\n",
            supported=["1.2.1.5"],
            known=["1.2.1.5"],
            slug="probe-mod",
        )


def test_update_mode_announces_the_version_rather_than_the_whole_post(tmp_path, capsys):
    """An existing thread does not need the mod explained again."""
    (tmp_path / "discord-post.md").write_text("# Probe Mod\n\nBody.\n")
    (tmp_path / "CHANGELOG.md").write_text(_CHANGELOG)
    logo = tmp_path / "unity" / "ProbeMod" / "Editor" / "logo.png"
    logo.parent.mkdir(parents=True)
    logo.write_bytes(b"\x89PNG")
    env = dict(_ENV, MOD_NAME="ProbeMod", CK_DISCORD_THREAD="https://discord.com/x")

    code = _run_main(tmp_path, monkeypatched=env, args=["--update"])

    out = capsys.readouterr().out
    assert code == 0
    assert out.startswith("**Version 1.4.0**")
    assert "Body." not in out


def test_update_mode_does_not_repost_the_threads_opening_clips(tmp_path, capsys):
    """auto-rail-bridges' CK_DISCORD_MEDIA names 38 MB GIFs meant to open the
    thread once -- announcing v1.0.2 must not post them again as follow-ups,
    the same reasoning that already drops the logo from attachments."""
    import json as _json

    (tmp_path / "discord-post.md").write_text("# Probe Mod\n\nBody.\n")
    (tmp_path / "CHANGELOG.md").write_text(_CHANGELOG)
    logo = tmp_path / "unity" / "ProbeMod" / "Editor" / "logo.png"
    logo.parent.mkdir(parents=True)
    logo.write_bytes(b"\x89PNG")
    env = dict(
        _ENV,
        MOD_NAME="ProbeMod",
        CK_DISCORD_THREAD="https://discord.com/x",
        CK_DISCORD_MEDIA="https://example.invalid/clip.gif",
    )

    _run_main(tmp_path, monkeypatched=env, args=["--update", "--json"])

    doc = _json.loads(capsys.readouterr().out)
    assert doc["attachments"] == []
    assert doc["follow_ups"] == []


def test_update_without_a_thread_says_to_post_one_first(tmp_path):
    """CK_DISCORD_THREAD is scaffolded empty by new_mod.py, so this is the
    default state of every new mod -- --update must not read that as 'create
    a new post', which is what a null thread otherwise signals."""
    (tmp_path / "discord-post.md").write_text("# Probe Mod\n\nBody.\n")
    (tmp_path / "CHANGELOG.md").write_text(_CHANGELOG)
    logo = tmp_path / "unity" / "ProbeMod" / "Editor" / "logo.png"
    logo.parent.mkdir(parents=True)
    logo.write_bytes(b"\x89PNG")
    env = dict(_ENV, MOD_NAME="ProbeMod")

    with pytest.raises(ValueError, match="CK_DISCORD_THREAD"):
        dp.render_repo(tmp_path, env, ["1.2.1.5"], update=True)


def test_update_mode_diagnostics_do_not_call_the_version_a_thread_title(
    tmp_path, capsys
):
    """The update branch's title field holds 'version 1.4.0', not a thread
    title, and its thread is never 'none yet' -- CK_DISCORD_THREAD is
    required by then."""
    (tmp_path / "discord-post.md").write_text("# Probe Mod\n\nBody.\n")
    (tmp_path / "CHANGELOG.md").write_text(_CHANGELOG)
    logo = tmp_path / "unity" / "ProbeMod" / "Editor" / "logo.png"
    logo.parent.mkdir(parents=True)
    logo.write_bytes(b"\x89PNG")
    env = dict(_ENV, MOD_NAME="ProbeMod", CK_DISCORD_THREAD="https://discord.com/x")

    _run_main(tmp_path, monkeypatched=env, args=["--update"])

    err = capsys.readouterr().err
    assert "version      : version 1.4.0" in err
    assert "thread title" not in err
    assert "none yet" not in err
    assert "thread       : https://discord.com/x" in err


def test_update_suppresses_the_mod_io_link_preview():
    """Verified in the live channel on 2026-08-26, same as the announcement
    post's download link -- a bare mod.io link there renders the platform's
    own corporate card as the last thing in the comment."""
    _, comment = dp.render_update(
        _CHANGELOG, supported=["1.2.1.5"], known=["1.2.1.5"], slug="probe-mod"
    )

    assert comment.endswith("<https://mod.io/g/corekeeper/m/probe-mod>")


def test_update_mode_fails_when_configured_media_is_broken(tmp_path):
    """resolve_media's return value is discarded in update mode -- the
    thread's opening post already carries the attachments -- but the call
    itself must still run, or a broken CK_DISCORD_MEDIA would reach the
    browser step undetected."""
    (tmp_path / "discord-post.md").write_text("# Probe Mod\n\nBody.\n")
    (tmp_path / "CHANGELOG.md").write_text(_CHANGELOG)
    logo = tmp_path / "unity" / "ProbeMod" / "Editor" / "logo.png"
    logo.parent.mkdir(parents=True)
    logo.write_bytes(b"\x89PNG")
    env = dict(
        _ENV,
        MOD_NAME="ProbeMod",
        CK_DISCORD_THREAD="https://discord.com/x",
        CK_DISCORD_MEDIA="sources/gone.png",
    )

    with pytest.raises(ValueError, match="gone.png"):
        dp.render_repo(tmp_path, env, ["1.2.1.5"], update=True)


def test_update_mode_without_a_changelog_says_so(tmp_path):
    """The version comment has nothing else to render from -- upload.sh reads
    CHANGELOG.md for the mod.io release itself, so a missing file is already
    fatal there, but --update can run on its own outside a publish."""
    (tmp_path / "discord-post.md").write_text("# Probe Mod\n\nBody.\n")
    logo = tmp_path / "unity" / "ProbeMod" / "Editor" / "logo.png"
    logo.parent.mkdir(parents=True)
    logo.write_bytes(b"\x89PNG")
    env = dict(_ENV, MOD_NAME="ProbeMod", CK_DISCORD_THREAD="https://discord.com/x")

    with pytest.raises(ValueError, match="CHANGELOG.md"):
        dp.render_repo(tmp_path, env, ["1.2.1.5"], update=True)
