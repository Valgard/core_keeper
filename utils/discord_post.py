"""Render a mod's `discord-post.md` into a ready-to-paste #available-mods post.

The Core Keeper Discord's mod forum asks for the compatible game versions in
one of the first lines of a post, and that is the one part of the text nobody
can keep current by hand: a new game build changes it in every mod at once.
So the prose is authored per mod and the version line is generated from
`CK_GAME_VERSION`.
"""

import functools
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
TAGS_FILENAME = "ck-discord-tags.json"

# Discord's own ceilings for a forum post. LIMIT is the non-Nitro message
# ceiling -- do not 'correct' it to 4000, since readers without Nitro are
# irrelevant here but the *author* posting it is not.
LIMIT = 2000
TITLE_LIMIT = 100
MAX_TAGS = 5
# Discord's own ceiling per message. The logo always holds slot one, so a mod
# may configure nine more.
MAX_ATTACHMENTS = 10
# Discord's non-Nitro upload ceiling. It has moved repeatedly (25 -> 8 -> 10 MB),
# which is why it is a constant here rather than a number in a message.
SIZE_LIMIT = 10 * 1024 * 1024


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
    unknown = sorted(set(tags) - forum_tags())
    if unknown:
        raise ValueError(f"not offered by #available-mods: {', '.join(unknown)}")
    if len(tags) > MAX_TAGS:
        raise ValueError(f"{len(tags)} tags — Discord accepts {MAX_TAGS} per post")

    body = re.sub(r"\A#[^\n]*\n+", "", markdown).strip()
    # Discord does not reflow: a newline in the source is a line break in the
    # post. mod.io never shows this because it receives HTML, where the browser
    # rewraps — same source format, two different consequences.
    blocks = [_unwrap(b) for b in body.split("\n\n")]
    body = "\n\n".join(b for b in blocks if b)
    # Both links bracketed, so neither adds an embed. The bare mod.io link used
    # to be deliberate -- it was meant to buy one preview card -- but mod.io
    # serves its own corporate card ("Cross Platform Mod Support for Games"),
    # which says nothing about the mod and lands after the images.
    links = (
        f"**Download:** <https://mod.io/g/corekeeper/m/{slug}>\n"
        f"**Source:** <https://github.com/Valgard/ck_{slug.replace('-', '_')}>"
    )
    post = version_line(supported, known) + "\n\n" + body + "\n\n" + links
    if len(post) > LIMIT:
        raise ValueError(f"post is {len(post)} characters — {LIMIT} is the limit")
    return post


def resolve_media(repo, env, mod_name):
    """Split CK_DISCORD_MEDIA into attachments and follow-up URLs.

    The logo always leads, so every thread carries the same kind of preview
    image in the channel list. An entry that parses as an http(s) URL becomes
    its own follow-up message -- Discord replaces a message consisting of
    nothing but a media URL with the medium itself, which is the only way a
    38 MB clip reaches a post at all.
    """
    repo = pathlib.Path(repo)
    logo = repo / "unity" / mod_name / "Editor" / "logo.png"
    if not logo.is_file():
        raise ValueError(f"no logo at {logo.relative_to(repo)} — is MOD_NAME right?")

    attachments, follow_ups = [logo], []
    for entry in (e.strip() for e in env.get("CK_DISCORD_MEDIA", "").split("|")):
        if not entry:
            continue
        if entry.startswith(("http://", "https://")):
            follow_ups.append(entry)
            continue
        path = repo / entry
        if not path.is_file():
            raise ValueError(f"CK_DISCORD_MEDIA names {entry}, which is not a file")
        attachments.append(path)

    if len(attachments) > MAX_ATTACHMENTS:
        raise ValueError(
            f"{len(attachments)} attachments including the logo — "
            f"Discord accepts {MAX_ATTACHMENTS}"
        )
    total = sum(p.stat().st_size for p in attachments)
    if total > SIZE_LIMIT:
        raise ValueError(
            f"attachments total {total // 1024} KB, which exceeds the "
            f"{SIZE_LIMIT // 1024} KB Discord accepts without Nitro"
        )
    return attachments, follow_ups


def _unwrap(block):
    """Join a block's lines into one paragraph, except where a break is meaning.

    List items and headings each own their line: Discord renders `##` as a
    heading, and folding one into the text under it would make it prose.
    """
    out, pending = [], []
    for line in (raw.strip() for raw in block.split("\n")):
        if not line:
            continue
        if line.startswith("#"):
            # A heading owns its line and takes nothing with it.
            if pending:
                out.append(" ".join(pending))
                pending = []
            out.append(line)
        elif line.startswith(("- ", "* ")):
            # A new item ends the previous one; a continuation line does not,
            # so a bullet wrapped across lines stays one bullet.
            if pending:
                out.append(" ".join(pending))
            pending = [line]
        else:
            pending.append(line)
    if pending:
        out.append(" ".join(pending))
    return "\n".join(out)


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


@functools.lru_cache(maxsize=1)
def forum_tags():
    """The tag set #available-mods offers, as read off the channel.

    A data file rather than a constant: the set belongs to a channel somebody
    else administers, and the browser step refreshes it from the live dropdown.
    """
    path = pathlib.Path(__file__).with_name(TAGS_FILENAME)
    try:
        doc = json.loads(path.read_text())
    except FileNotFoundError:
        sys.exit(f"discord_post: {path} is missing — restore it from git")
    except json.JSONDecodeError as err:
        sys.exit(f"discord_post: {path} is not valid JSON: {err}")
    if "tags" not in doc:
        sys.exit(f"discord_post: {path} has no 'tags' key")
    return frozenset(doc["tags"])


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
