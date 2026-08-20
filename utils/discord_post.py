"""Render a mod's `discord-post.md` into a ready-to-paste #available-mods post.

The Core Keeper Discord's mod forum asks for the compatible game versions in
one of the first lines of a post, and that is the one part of the text nobody
can keep current by hand: a new game build changes it in every mod at once.
So the prose is authored per mod and the version line is generated from
`CK_GAME_VERSION`.
"""

import json
import os
import pathlib
import re
import sys

POST_FILENAME = "discord-post.md"
VERSIONS_FILENAME = "ck-game-versions.json"

# Discord's own ceilings for a forum post.
LIMIT = 2000
MAX_TAGS = 5

# The forum's own tag set, read off the channel. Discord offers these as
# checkboxes when a thread is created, so a value outside the list cannot be
# set at all — catching it here means finding out before the text is written.
FORUM_TAGS = frozenset(
    {
        "Automation",
        "Cheats",
        "Combat",
        "Content",
        "Decoration",
        "Difficulty",
        "Enemies",
        "Environment",
        "Equipment",
        "Fishing",
        "Food",
        "Gardening",
        "Mining",
        "Misc / Other",
        "NPCs",
        "Overhaul",
        "Transportation",
        "Tweaks",
        "Utilities",
        "Work In Progress",
    }
)


def _norm(version):
    """Canonical form: at least four segments, compared as integers.

    Steam and mod.io spell the same build differently (`0.7.4` vs `0.7.4.0`),
    and string order puts `1.2.1.10` before `1.2.1.5`.
    """
    parts = [int(x) for x in version.split(".")]
    while len(parts) < 4:
        parts.append(0)
    return tuple(parts)


def _fmt(parts):
    return ".".join(str(x) for x in parts)


def version_line(supported, known):
    """The post's first line, from the builds this mod supports."""
    sup = sorted(_norm(v) for v in supported)
    span = f"tested on {_fmt(sup[0])} through {_fmt(sup[-1])}"
    major, minor = sup[0][:2]

    # `1.2.x` claims the entire minor, so it is only printed once that claim is
    # checked against the builds that exist. Unverified, it would overstate for
    # any mod that starts partway into a release series.
    in_minor = {v for v in (_norm(k) for k in known) if v[:2] == (major, minor)}
    if in_minor <= set(sup):
        return f"**Compatible with Core Keeper {major}.{minor}.x** — {span}."
    return f"**Compatible with Core Keeper {_fmt(sup[0])} – {_fmt(sup[-1])}**"


def render(markdown, *, supported, known, tags, slug):
    """The finished post body, ready to paste into a forum thread."""
    unknown = sorted(set(tags) - FORUM_TAGS)
    if unknown:
        raise ValueError(f"not offered by #available-mods: {', '.join(unknown)}")
    if len(tags) > MAX_TAGS:
        raise ValueError(f"{len(tags)} tags — Discord accepts {MAX_TAGS} per post")

    body = re.sub(r"\A#[^\n]*\n+", "", markdown).strip()
    body = re.sub(r"^##+\s+(.*)$", r"**\1**", body, flags=re.MULTILINE)
    # Discord does not reflow: a newline in the source is a line break in the
    # post. mod.io never shows this because it receives HTML, where the browser
    # rewraps — same source format, two different consequences.
    blocks = [_unwrap(b) for b in body.split("\n\n")]
    body = "\n\n".join(b for b in blocks if b)
    # Exactly one bare link, so the post carries a single mod.io preview card.
    # The source link is bracketed to keep a second card from competing with it.
    links = (
        f"**Download:** https://mod.io/g/corekeeper/m/{slug}\n"
        f"**Source:** <https://github.com/Valgard/ck_{slug.replace('-', '_')}>"
    )
    post = version_line(supported, known) + "\n\n" + body + "\n\n" + links
    if len(post) > LIMIT:
        raise ValueError(f"post is {len(post)} characters — {LIMIT} is the limit")
    return post


def _unwrap(block):
    lines = [line.strip() for line in block.split("\n") if line.strip()]
    if any(line.startswith(("- ", "* ")) for line in lines):
        return "\n".join(lines)
    return " ".join(lines)


def render_repo(repo, env, known):
    """Render the post for one mod repo, or None when it has no `discord-post.md`.

    A missing file is the normal state for a mod nobody has written a post for
    yet, so it is skipped rather than reported -- the same call CLIPublishHelper
    makes for a missing `modio-description.md`.
    """
    source = pathlib.Path(repo) / POST_FILENAME
    if not source.is_file():
        return None
    # Empty is the scaffolded state, not a choice: new_mod.py cannot know a new
    # mod's forum tags, so it writes the variable blank. Both cases are the same
    # omission and get the same message.
    if not env.get("CK_DISCORD_TAGS", "").strip():
        raise ValueError(
            f"{source.name} exists but CK_DISCORD_TAGS is empty — add the "
            "forum tags to .envrc and .envrc.example, pipe-separated"
        )
    tags = [t.strip() for t in env["CK_DISCORD_TAGS"].split("|") if t.strip()]
    markdown = source.read_text()
    heading = re.match(r"#\s+(.*)", markdown)
    if not heading:
        raise ValueError(f"{source.name} has no '# Title' heading to post under")
    post = render(
        markdown,
        supported=env["CK_GAME_VERSION"].split(),
        known=known,
        tags=tags,
        slug=env["MOD_NAME_ID"],
    )
    return post, tags, heading.group(1).strip()


def known_versions():
    """The builds that shipped, from the data file beside this script."""
    path = pathlib.Path(__file__).with_name(VERSIONS_FILENAME)
    return json.loads(path.read_text())["versions"]


def main(argv=None):
    """Print one mod's post: the text on stdout, everything else on stderr.

    The split is what makes `utils/discord_post.py | pbcopy` copy the post and
    nothing else, while the title and tags -- which are typed into Discord's UI,
    not pasted -- stay visible in the terminal.
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    check_only = "--check" in argv
    paths = [a for a in argv if a != "--check"]
    repo = pathlib.Path(paths[0]) if paths else pathlib.Path.cwd()

    try:
        result = render_repo(repo, os.environ, known_versions())
    except (ValueError, KeyError) as err:
        print(f"discord_post: {repo.name}: {err}", file=sys.stderr)
        return 1
    if result is None:
        return 0

    post, tags, title = result
    print(f"thread title : {title}", file=sys.stderr)
    print(f"forum tags   : {', '.join(tags)}", file=sys.stderr)
    print(f"length       : {len(post)} / {LIMIT}", file=sys.stderr)
    if not check_only:
        print(post)
    return 0


if __name__ == "__main__":
    sys.exit(main())
