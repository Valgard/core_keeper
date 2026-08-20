"""Renders every `discord-post.md` that exists and holds it to Discord's limits.

`test_discord_post.py` tests the renderer on synthetic input; this suite tests
the actual posts. The split matters because the two fail for different reasons:
a red test there is a broken renderer, a red test here is a text that grew too
long or a forum tag nobody can select. Only the second is fixed by editing prose.

Everything is read from `.envrc.example` rather than `.envrc`, because the
latter is gitignored -- a check that depended on it would pass or fail
depending on whose machine ran it.
"""

import re

import discord_post as dp
import new_mod as nm
import pytest


def _export(text, name):
    match = re.search(rf'^export {name}="([^"]*)"', text or "", re.MULTILINE)
    return match.group(1) if match else None


def _posts():
    """(repo, env) for every mod repo that has a post, with the parent's
    CK_GAME_VERSION -- the canonical list a mod inherits and may override."""
    mods_dir = nm.resolve_mods_dir()
    parent = _export(_text(mods_dir / ".envrc.example"), "CK_GAME_VERSION")

    found = []
    for git_entry in sorted(mods_dir.glob("*/.git")):
        repo = git_entry.parent
        if not (repo / dp.POST_FILENAME).is_file():
            continue
        example = _text(repo / ".envrc.example")
        env = {
            "MOD_NAME_ID": _export(example, "MOD_NAME_ID"),
            "CK_GAME_VERSION": _export(example, "CK_GAME_VERSION") or parent,
        }
        tags = _export(example, "CK_DISCORD_TAGS")
        if tags is not None:
            env["CK_DISCORD_TAGS"] = tags
        found.append((repo, env))
    return found


def _text(path):
    return path.read_text() if path.is_file() else None


POSTS = _posts()

# Applied per test, not to the module: the version-list checks below hold
# whether or not anybody has written a post yet.
needs_posts = pytest.mark.skipif(
    not POSTS,
    reason=(
        f"no {dp.POST_FILENAME} beside {nm.resolve_mods_dir()} -- these checks "
        "did NOT run, so nothing here says the posts are within Discord's limits"
    ),
)


@needs_posts
@pytest.mark.parametrize("repo,env", POSTS, ids=lambda v: getattr(v, "name", ""))
def test_every_written_post_renders_within_discords_limits(repo, env):
    """render_repo raises on all four ceilings -- length, unknown tag, tag
    count, missing heading -- so rendering it *is* the assertion."""
    post, tags, title = dp.render_repo(repo, env, dp.known_versions())

    assert post and tags and title


@needs_posts
@pytest.mark.parametrize("repo,env", POSTS, ids=lambda v: getattr(v, "name", ""))
def test_a_posts_forum_tags_are_committed_not_only_local(repo, env):
    """`.envrc` is gitignored, so tags that live only there are lost on clone
    and the post cannot be rendered anywhere else."""
    assert "CK_DISCORD_TAGS" in env, (
        f"{repo.name} has a {dp.POST_FILENAME} but no CK_DISCORD_TAGS in "
        ".envrc.example -- the forum tags would not survive a fresh checkout"
    )


@needs_posts
def test_the_shipped_version_list_covers_every_supported_build():
    """A build in CK_GAME_VERSION that the list does not know is either a typo
    or a missing entry; both make the version line wrong."""
    known = {dp._norm(v) for v in dp.known_versions()}
    for repo, env in POSTS:
        unknown = sorted(
            dp._fmt(v)
            for v in (dp._norm(b) for b in env["CK_GAME_VERSION"].split())
            if v not in known
        )
        assert not unknown, (
            f"{repo.name}: {', '.join(unknown)} not in "
            f"{dp.VERSIONS_FILENAME} — a typo, or a build to add"
        )


def test_the_version_list_is_sorted_newest_first_without_duplicates():
    """It is hand-curated from two feeds that disagree, so ordering and
    duplicates are the failure modes a reader would not notice."""
    versions = [dp._norm(v) for v in dp.known_versions()]

    assert versions == sorted(set(versions), reverse=True)
