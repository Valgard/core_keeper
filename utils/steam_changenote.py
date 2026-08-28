"""Turn one Markdown changelog entry into the BBCode a Workshop change note is.

A Steam change note is BBCode, exactly like an item's description — measured
against a live item with both dialects in one note, and written down in
`docs/ck/steam-workshop.md`. Markdown does not degrade gracefully there: `###`,
`**` and a bulleted list appear character for character, so a note sent in the
wrong dialect does not look plainer, it looks broken. Both publishing paths went
out that way — `utils/upload.sh` handed `CHANGELOG.md` straight to
`WithChangeLog`, and `utils/steam_backfill.py` inherited it — which is why the
conversion lives in `steam_bundle.build_bundle`, the one place both of them
reach.

Nothing here can be corrected afterwards. A history entry is append-only to
every API and editable only by hand in the browser, one web form at a time, so
the tests for this module are the corpus of real changelog entries rather than
invented ones.

Three decisions worth stating, because each looks like an oversight:

- **Inline `` `code` `` keeps its backticks.** `[code]` on Steam is *block*
  level: mapping an inline `identifier` onto it splits the sentence around every
  symbol name. Backticks render literally, and literal backticks still delimit
  the identifier — which is what they were there for. Do not "fix" this to
  `[code]`.
- **A `[` that is not a link is left exactly as written.** Steam's BBCode has no
  documented escape, so anything substituted for it would be a guess about an
  undocumented parser, and a wrong guess turns text that renders correctly into
  visible mangle. The measured behaviour is that an unrecognised construct
  renders character for character, which is the outcome a bare bracket wants.
  The one real exposure this leaves is a bracketed identifier inside a code span
  — `` `[HarmonyPatch]` `` — which Steam may read as an unknown tag; the corpus
  contains none, and a changelog is the cheap place to correct one.
- **Underscores are never emphasis.** `_x_` and `__x__` are Markdown, but they
  collide with the one thing these changelogs are full of outside code spans:
  identifiers. Asterisks carry all the emphasis here, so the underscore dialect
  buys nothing and can only misfire.

Hard-wrapped lines are joined. The Workshop renders every newline as a line
break, and these changelogs are wrapped at about eighty columns for the file's
own sake; kept, those breaks would ragged-edge the note in a browser column
several times that wide, and mod.io — rendering the same source as Markdown —
would show the same release differently. Joining first is also what makes a bold
or code span that wraps across two lines convertible at all, and the corpus has
sixteen of those.
"""

import re

# A block's opening line. Headings and list items are structural; everything
# else that is not blank starts a paragraph.
HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
BULLET = re.compile(r"^(\s*)[-*+]\s+(.*)$")
ORDERED = re.compile(r"^(\s*)\d+[.)]\s+(.*)$")
FENCE = re.compile(r"^\s*(```|~~~)")

# Inline code first, and greedy-free: the span is protected before any other
# rule runs, so nothing inside it can be read as markup.
CODE = re.compile(r"`[^`]+`")
LINK = re.compile(r"\[([^\]]*)\]\(([^)\s]+)\)")
BOLD = re.compile(r"\*\*(\S(?:.*?\S)?)\*\*")
# After BOLD, so a surviving single asterisk is genuinely a lone one. The
# lookarounds keep it off an asterisk used as a literal (`2 * 3`) and off the
# leftover half of an unbalanced `**`.
ITALIC = re.compile(r"(?<!\*)\*(?!\s)([^*\n]+?)(?<!\s)\*(?!\*)")

# Placeholder for a stashed code span. NUL cannot occur in a changelog, and a
# BBCode-looking marker would put the marker itself at risk of being converted.
STASH = re.compile(r"\x00(\d+)\x00")


def render(version: str, markdown: str) -> str:
    """The complete change note for one release: its version, then its notes.

    The `[h2]` line is the only way an entry can carry a version at all.
    `SubmitItemUpdate` takes the note and nothing else — there is no
    `SetItemVersion`, and `SetItemTitle` renames the item — so a published entry
    otherwise shows `Update: <date>` and its body, and several entries submitted
    in one session are indistinguishable by their headers. The backfill submits
    dozens in one run, which is where that stops being cosmetic.
    """
    body = to_bbcode(markdown)
    heading = f"[h2]{version}[/h2]"
    return f"{heading}\n\n{body}" if body else heading


def to_bbcode(markdown: str) -> str:
    """One changelog entry's body, in the dialect the Workshop renders."""
    lines = markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue
        if FENCE.match(line):
            block, index = _fenced(lines, index)
            blocks.append(block)
            continue
        heading = HEADING.match(line)
        if heading:
            # Every level flattens: the note's own [h2] is the version, and a
            # body heading is a section of that release however deep it was
            # written. An [h1] here would outrank the version it belongs to.
            blocks.append(f"[h3]{_inline(heading.group(2))}[/h3]")
            index += 1
            continue
        if BULLET.match(line) or ORDERED.match(line):
            items, index = _list_items(lines, index)
            blocks.append("\n".join(_render_list(_nest(items))))
            continue
        paragraph, index = _paragraph(lines, index)
        blocks.append(_inline(paragraph))
    return "\n\n".join(blocks)


def _fenced(lines: list[str], start: int) -> tuple[str, int]:
    """A ``` block as `[code]`, verbatim — the one place that tag is right.

    [code] is block-level, which is exactly what a fenced block is. Its lines
    keep their breaks and are not inline-converted: what is inside a code block
    is code, and `**` in it means two asterisks.
    """
    body = []
    index = start + 1
    while index < len(lines) and not FENCE.match(lines[index]):
        body.append(lines[index])
        index += 1
    return "[code]\n" + "\n".join(body) + "\n[/code]", min(index + 1, len(lines))


def _paragraph(lines: list[str], start: int) -> tuple[str, int]:
    """Consecutive prose lines, joined into one.

    Ends at a blank line or at anything structural — a heading directly under a
    paragraph needs no blank line to separate the two, and Markdown reads it
    that way as well.
    """
    out = []
    index = start
    while index < len(lines) and lines[index].strip():
        line = lines[index]
        if (
            HEADING.match(line)
            or BULLET.match(line)
            or ORDERED.match(line)
            or FENCE.match(line)
        ):
            break
        out.append(line.strip())
        index += 1
    return " ".join(out), index


def _list_items(lines: list[str], start: int) -> tuple[list[list], int]:
    """The [indent, ordered, text] items of one list, continuation lines folded in.

    Never empty: the caller only enters here on a line that is already an item,
    so `_nest` below can read the first one's indent without a guard.

    A blank line does not end the list when another item follows it: Markdown
    calls that one loose list, and splitting it would render two.

    A continuation line has to be indented. A flush-left line that is not an item
    ends the list instead of continuing it (Markdown's "lazy continuation" would
    absorb it) — the corpus indents every one of its 372 continuation lines, and
    the strict reading fails visibly, as a stray paragraph, rather than by
    swallowing a line into the wrong item.
    """
    items: list[list] = []
    index = start
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            after = index
            while after < len(lines) and not lines[after].strip():
                after += 1
            if after < len(lines) and (
                BULLET.match(lines[after]) or ORDERED.match(lines[after])
            ):
                index = after
                continue
            break
        bullet = BULLET.match(line)
        if bullet:
            items.append([len(bullet.group(1)), False, bullet.group(2).strip()])
            index += 1
            continue
        ordered = ORDERED.match(line)
        if ordered:
            items.append([len(ordered.group(1)), True, ordered.group(2).strip()])
            index += 1
            continue
        if items and line[:1].isspace():
            items[-1][2] += " " + line.strip()
            index += 1
            continue
        break
    return items, index


def _nest(items: list[list]) -> list[dict]:
    """Flat (indent, ordered, text) items as a tree, by indentation.

    The first item's indent is the list's base level, so a whole list written at
    a non-zero indent nests nothing. Deeper items attach to the item above them.
    """
    root: list[dict] = []
    stack: list[tuple[int, list[dict]]] = [(items[0][0], root)]
    for indent, ordered, text in items:
        while len(stack) > 1 and indent < stack[-1][0]:
            stack.pop()
        if indent > stack[-1][0] and stack[-1][1]:
            stack.append((indent, stack[-1][1][-1]["children"]))
        stack[-1][1].append({"text": text, "ordered": ordered, "children": []})
    return root


def _render_list(items: list[dict]) -> list[str]:
    """One list level as BBCode lines, `[*]` per item, nested lists inside.

    Ordered-ness comes from the level's first item: BBCode picks the marker per
    list, not per entry, so a level mixing the two has to resolve to one.
    """
    tag = "olist" if items[0]["ordered"] else "list"
    out = [f"[{tag}]"]
    for item in items:
        out.append(f"[*] {_inline(item['text'])}")
        if item["children"]:
            out.extend(_render_list(item["children"]))
    out.append(f"[/{tag}]")
    return out


def _inline(text: str) -> str:
    """Emphasis, links and code inside one already-unwrapped block of text.

    Order is the whole design. Code spans are stashed first so nothing inside
    one can be read as markup; links go next, before any tag exists that their
    own brackets could be confused with; bold precedes italic so a `**` is never
    seen as two lone asterisks.
    """
    stashed: list[str] = []

    def stash(match: re.Match) -> str:
        stashed.append(match.group(0))
        return f"\x00{len(stashed) - 1}\x00"

    text = CODE.sub(stash, text)
    text = LINK.sub(lambda m: f"[url={m.group(2)}]{m.group(1)}[/url]", text)
    text = BOLD.sub(r"[b]\1[/b]", text)
    text = ITALIC.sub(r"[i]\1[/i]", text)
    return STASH.sub(lambda m: stashed[int(m.group(1))], text)
