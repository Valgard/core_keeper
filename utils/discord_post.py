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

import steam_identity

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
# Discord's non-Nitro upload ceiling -- a conservative, UNVERIFIED bound. The
# value has moved over time and may have moved again since this was last
# checked, which is why it lives here as a constant rather than as a number
# quoted in a message: only one place needs updating. To check the current
# value, attach a file of the size in question in Discord's own message
# composer -- it refuses before anything is sent, so nothing real is uploaded
# in the process.
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


def download_links(slug, steam_id, *, source=True):
    """The platform lines both renderers end with, in one place.

    Labelled by platform rather than by action: "Download" was right while
    mod.io was the only place to get a mod, but beside a "Steam Workshop" line
    it labels the two destinations inconsistently -- one naming what you do,
    the other where you are. The update comment carries the labels too, where
    it used to end in a bare URL: one unlabelled link was self-evident from its
    position, two would not be.

    `source` is off for that comment, and NOT because the repository does not
    change from one release to the next -- neither does the mod.io slug, and a
    Workshop id never changes at all, so that test would drop every link. What
    separates them is what the message is for: a release comment says "there is
    a new version", so a way to go and get it is the next thing its reader
    wants. Browsing the source is not, and the thread's opening post links it
    for anyone who does.

    A mod with no Workshop item simply has no Steam line. That is not a
    fallback for a broken state: it is what a mod published to mod.io only
    looks like, and what every mod looked like before Steam publishing existed.
    `read_file_id` returns None for the scaffolded `fileId: 0` as well as for a
    missing asset, so both arrive here as the same absence.
    """
    lines = [f"**mod.io:** <https://mod.io/g/corekeeper/m/{slug}>"]
    if steam_id:
        lines.append(f"**Steam Workshop:** <{steam_identity.item_url(steam_id)}>")
    if source:
        repo = slug.replace("-", "_")
        lines.append(f"**Source:** <https://github.com/Valgard/ck_{repo}>")
    return "\n".join(lines)


def render(markdown, *, supported, known, tags, slug, steam_id=None):
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
    # Every link bracketed, so none adds an embed. The bare mod.io link used
    # to be deliberate -- it was meant to buy one preview card -- but mod.io
    # serves its own corporate card ("Cross Platform Mod Support for Games"),
    # which says nothing about the mod and lands after the images. A Steam link
    # would produce a card about the actual item, which is the more tempting
    # case and the same answer: it would still land after the images, unasked.
    links = download_links(slug, steam_id)
    post = version_line(supported, known) + "\n\n" + body + "\n\n" + links
    if len(post) > LIMIT:
        raise ValueError(f"post is {len(post)} characters — {LIMIT} is the limit")
    return post


def render_update(changelog, *, supported, known, slug, steam_id=None):
    """The comment announcing a new version in an existing thread.

    CHANGELOG.md is already the canonical release source -- CLIPublishHelper
    publishes the same topmost entry -- so a separate file would be a second
    place to keep in step, and the version line would drift the way it did
    before it was generated.
    """
    entries = re.split(r"^## \[([0-9.]+)\][^\n]*\n", changelog, flags=re.M)
    if len(entries) < 3:
        raise ValueError("no '## [x.y.z]' entry in the changelog")
    version, body = entries[1], entries[2]

    # '### Changed' is changelog scaffolding. In a chat message it renders as a
    # heading owning its bullets, which reads as emphasis nobody intended. The
    # heading is dropped line by line rather than block by block: some mods
    # write it with no blank line before its bullets, so heading and bullets
    # split into one block together, and a block-level filter took the
    # bullets with it.
    blocks = []
    for b in body.strip().split("\n\n"):
        kept = "\n".join(l for l in _unwrap(b).split("\n") if not l.startswith("###"))
        if kept.strip():
            blocks.append(kept)
    # The version line keeps its own bold markers, so it gets its own line
    # rather than being spliced into one -- concatenating two bold runs with a
    # dash between them produces stray asterisks mid-sentence.
    comment = (
        f"**Version {version}**\n{version_line(supported, known)}\n\n"
        + "\n\n".join(blocks)
        + "\n\n"
        + download_links(slug, steam_id, source=False)
    )
    if len(comment) > LIMIT:
        raise ValueError(f"comment is {len(comment)} characters — {LIMIT} is the limit")
    return version, comment


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


def workshop_id(repo, mod_name):
    """This mod's Workshop item id, or None when it has none.

    Read from the identity asset rather than configured in the .envrc, for the
    same reason a publish reads it there: the asset is the authority on which
    item a mod is, and a second copy in a second file is a second thing to keep
    in step. MOD_NAME rather than MOD_NAME_ID -- the asset path is built from
    the PascalCase name, while the mod.io slug above is the kebab one.
    """
    return steam_identity.read_file_id(
        steam_identity.asset_path(pathlib.Path(repo), mod_name)
    )


def render_repo(repo, env, known, *, update=False):
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
    for name in ("CK_GAME_VERSION", "MOD_NAME_ID", "MOD_NAME"):
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

    if update:
        thread = env.get("CK_DISCORD_THREAD", "").strip()
        if not thread:
            raise ValueError(
                "--update announces a version in an existing thread, but "
                "CK_DISCORD_THREAD is empty -- post the mod's thread first "
                "(without --update), then record its URL in CK_DISCORD_THREAD "
                "and .envrc.example"
            )
        changelog = pathlib.Path(repo) / "CHANGELOG.md"
        if not changelog.is_file():
            raise ValueError("no CHANGELOG.md to take the version comment from")
        version, comment = render_update(
            changelog.read_text(),
            supported=env["CK_GAME_VERSION"].split(),
            known=known,
            slug=env["MOD_NAME_ID"],
            steam_id=workshop_id(repo, env["MOD_NAME"]),
        )
        # Validated but discarded, attachments and follow_ups alike: the
        # thread's opening images already carry the logo and every clip, and
        # a release comment must not repost them.
        resolve_media(repo, env, env["MOD_NAME"])
        return {
            "title": f"version {version}",
            "body": comment,
            "tags": [],
            "attachments": [],
            "follow_ups": [],
            "thread": thread,
            "length": len(comment),
        }

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
        steam_id=workshop_id(repo, env["MOD_NAME"]),
    )
    title = heading.group(1).strip()
    if len(title) > TITLE_LIMIT:
        raise ValueError(
            f"thread title is {len(title)} characters — Discord accepts {TITLE_LIMIT}"
        )
    attachments, follow_ups = resolve_media(repo, env, env["MOD_NAME"])
    return {
        "title": title,
        "body": post,
        "tags": tags,
        # Resolved, not just str()'d: the repo argument may be relative, and
        # the browser tool this reaches (mcp__claude-in-chrome__file_upload)
        # requires an absolute path.
        "attachments": [str(p.resolve()) for p in attachments],
        "follow_ups": follow_ups,
        "thread": env.get("CK_DISCORD_THREAD", "").strip() or None,
        "length": len(post),
    }


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
    as_json = "--json" in argv
    update = "--update" in argv
    paths = [a for a in argv if a not in ("--check", "--json", "--update")]
    # Without this, `--chek` becomes a path, render_repo finds no post there and
    # the run succeeds in silence -- the same outcome as "all fine".
    unknown = [a for a in paths if a.startswith("-")]
    if unknown or len(paths) > 1:
        print(
            f"usage: discord_post.py [mod-repo-path] [--check] [--json] [--update]\n"
            f"       got: {' '.join(argv)}",
            file=sys.stderr,
        )
        return 2
    repo = pathlib.Path(paths[0]) if paths else pathlib.Path.cwd()

    known = known_versions()
    try:
        result = render_repo(repo, os.environ, known, update=update)
    except ValueError as err:
        print(f"discord_post: {repo.name or repo}: {err}", file=sys.stderr)
        return EXIT_CONTENT
    if result is None:
        return 0

    if update:
        # No title, no tags, no attachments in this mode -- the thread
        # already carries all three, and CK_DISCORD_THREAD is required by
        # render_repo's update branch, so 'none yet' cannot apply here.
        print(f"version      : {result['title']}", file=sys.stderr)
        print(f"length       : {result['length']} / {LIMIT}", file=sys.stderr)
        print(f"thread       : {result['thread']}", file=sys.stderr)
    else:
        print(f"thread title : {result['title']}", file=sys.stderr)
        print(f"forum tags   : {', '.join(result['tags'])}", file=sys.stderr)
        print(f"length       : {result['length']} / {LIMIT}", file=sys.stderr)
        print(f"attachments  : {len(result['attachments'])}", file=sys.stderr)
        if result["follow_ups"]:
            print(f"follow-ups   : {len(result['follow_ups'])}", file=sys.stderr)
        print(
            f"thread       : {result['thread'] or 'none yet — a new post'}",
            file=sys.stderr,
        )
    if as_json:
        print(json.dumps(result, indent=2))
    elif not check_only:
        print(result["body"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
