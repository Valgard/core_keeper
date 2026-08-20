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

# A distinct code for 'the post is wrong', so upload.sh can wave that through
# while still failing on a broken interpreter, a missing data file or a
# syntax error -- which a bare 1 made indistinguishable.
EXIT_CONTENT = 3
VERSIONS_FILENAME = "ck-game-versions.json"

# Discord's own ceilings for a forum post. LIMIT is the non-Nitro message
# ceiling -- do not 'correct' it to 4000, since readers without Nitro are
# irrelevant here but the *author* posting it is not.
LIMIT = 2000
TITLE_LIMIT = 100
MAX_TAGS = 5

# The forum's own tag set, read off the channel. Discord offers these as
# checkboxes when a thread is created, so a value outside the list cannot be
# set at all — catching it here means finding out before you are standing in
# the thread-creation dialog with the text already written.
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
    # `1.2.x` claims one whole minor, so it needs two things to be true: every
    # supported build sits in that minor -- otherwise the claim contradicts its
    # own span -- and no build of it is left out, or the mod would advertise
    # versions it starts above.
    minors = {v[:2] for v in sup}
    if len(minors) == 1:
        major, minor = minors.pop()
        in_minor = {v for v in (_norm(k) for k in known) if v[:2] == (major, minor)}
        if in_minor <= set(sup):
            return f"**Compatible with Core Keeper {major}.{minor}.x** — {span}."
    return f"**Compatible with Core Keeper {_fmt(sup[0])} – {_fmt(sup[-1])}**"


def render(markdown, *, supported, known, tags, slug):
    unknown = sorted(set(tags) - FORUM_TAGS)
    if unknown:
        raise ValueError(f"not offered by #available-mods: {', '.join(unknown)}")
    if len(tags) > MAX_TAGS:
        raise ValueError(f"{len(tags)} tags — Discord accepts {MAX_TAGS} per post")

    body = re.sub(r"\A#[^\n]*\n+", "", markdown).strip()
    # Discord *does* have headings (`#`, `##`, `###`); this is a style choice,
    # not a compatibility one. At forum-post length a `##` renders larger than
    # the paragraph it introduces and pulls the eye off the text.
    body = re.sub(r"^##+\s+(.*)$", r"**\1**", body, flags=re.MULTILINE)
    # Discord does not reflow: a newline in the source is a line break in the
    # post. mod.io never shows this because it receives HTML, where the browser
    # rewraps — same source format, two different consequences.
    blocks = [_unwrap(b) for b in body.split("\n\n")]
    body = "\n\n".join(b for b in blocks if b)
    # One bare link, so the post carries a single mod.io preview card. A bare
    # URL in the authored prose would add a competing one -- an invariant the
    # author keeps, not something this can enforce.
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

    A mod need not have a forum thread, so a missing file is skipped. That is
    the same decision CLIPublishHelper makes for a missing `modio-description.md`
    -- though that one logs a line, and this returns in silence, because
    `upload.sh` calls it for every mod including the ones that will never have a
    post.
    """
    source = pathlib.Path(repo) / POST_FILENAME
    if not source.is_file():
        # Tags filled in with no post file is not "no post yet" -- somebody wrote
        # one. The likely cause is the filename: this script is discord_post.py
        # with an underscore, the file is discord-post.md with a hyphen.
        if env.get("CK_DISCORD_TAGS", "").strip():
            near = sorted(q.name for q in pathlib.Path(repo).glob("*ost*.md"))
            raise ValueError(
                f"CK_DISCORD_TAGS is set but there is no {POST_FILENAME} in "
                f"{repo} — found instead: {', '.join(near) or 'nothing similar'}"
            )
        return None
    for name in ("CK_GAME_VERSION", "MOD_NAME_ID"):
        if not env.get(name, "").strip():
            raise ValueError(
                f"{name} is not set — it comes from the .envrc chain, so run "
                "this from the mod directory with direnv active"
            )

    # Empty is the scaffolded state, not a choice: new_mod.py cannot know a new
    # mod's forum tags, so it writes the variable blank. Both cases are the same
    # omission and get the same message.
    if not env.get("CK_DISCORD_TAGS", "").strip():
        raise ValueError(
            f"{source.name} exists but CK_DISCORD_TAGS is empty — add the "
            "forum tags to .envrc and .envrc.example, pipe-separated"
        )
    tags = [t.strip() for t in env["CK_DISCORD_TAGS"].split("|") if t.strip()]
    unknown = sorted(
        v
        for v in env["CK_GAME_VERSION"].split()
        if _norm(v) not in {_norm(k) for k in known}
    )
    if unknown:
        raise ValueError(
            f"CK_GAME_VERSION names {', '.join(unknown)}, which "
            f"{VERSIONS_FILENAME} does not list as a shipped build — a typo, or "
            "a build to add (utils/refresh_game_versions.py)"
        )

    markdown = source.read_text()
    # [^\S\n] rather than \s: the latter spans newlines, so a bare '#' line took
    # the first paragraph as the title while render() left it in the body.
    heading = re.match(r"#[^\S\n]+(\S.*)", markdown)
    if not heading:
        raise ValueError(f"{source.name} has no '# Title' heading to post under")
    post = render(
        markdown,
        supported=env["CK_GAME_VERSION"].split(),
        known=known,
        tags=tags,
        slug=env["MOD_NAME_ID"],
    )
    title = heading.group(1).strip()
    if len(title) > TITLE_LIMIT:
        raise ValueError(
            f"thread title is {len(title)} characters — Discord accepts {TITLE_LIMIT}"
        )
    return post, tags, title


def known_versions():
    path = pathlib.Path(__file__).with_name(VERSIONS_FILENAME)
    try:
        doc = json.loads(path.read_text())
    except FileNotFoundError:
        sys.exit(f"discord_post: {path} is missing — restore it from git")
    except json.JSONDecodeError as err:
        sys.exit(f"discord_post: {path} is not valid JSON: {err}")
    if "versions" not in doc:
        sys.exit(f"discord_post: {path} has no 'versions' key")
    return doc["versions"]


def main(argv=None):
    """Print one mod's post: the text on stdout, everything else on stderr.

    The split is what makes `python3 utils/discord_post.py | pbcopy` copy the
    post and nothing else, while the title and tags -- which are typed into Discord's UI,
    not pasted -- stay visible in the terminal.
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    check_only = "--check" in argv
    paths = [a for a in argv if a != "--check"]
    # Without this, `--chek` becomes a path, render_repo finds no post there and
    # the run succeeds in silence -- the same outcome as "all fine".
    unknown = [a for a in paths if a.startswith("-")]
    if unknown or len(paths) > 1:
        print(
            f"usage: discord_post.py [mod-repo-path] [--check]\n"
            f"       got: {' '.join(argv)}",
            file=sys.stderr,
        )
        return 2
    repo = pathlib.Path(paths[0]) if paths else pathlib.Path.cwd()

    known = known_versions()
    try:
        result = render_repo(repo, os.environ, known)
    except ValueError as err:
        print(f"discord_post: {repo.name or repo}: {err}", file=sys.stderr)
        return EXIT_CONTENT
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
