# Discord forum posting — browser-assisted, not automated

Announcing a mod in the Core Keeper Discord's `#available-mods` forum is
today a manual copy-and-paste job: run `utils/discord_post.py`, pipe it
through `pbcopy`, open Discord, create a thread, retype the title, tick the
tags, drag in the images. Every step is mechanical, and every step is a
place to get it wrong — a tag that does not exist, an image forgotten, a
compatibility line from the previous game build.

This design covers doing that work in the browser while keeping the one
action that publishes anything in human hands.

## The constraint that shapes everything

Discord forbids automating a user account. What it actually detects and
acts on is **API traffic carrying a user token** — requests that do not
originate from the official client, recognisable by missing or wrong
client headers and by request patterns no human produces.

A browser extension driving the user's own logged-in session generates the
same traffic a human does, because a human's own events are what produce
it. That is the whole basis of this approach, and it dictates three rules
that are not negotiable:

- **No calls to `discord.com/api`.** Not for reading the tag list, not for
  posting, not for anything.
- **No writing into Discord's React state via injected JavaScript.** The
  message box is a Slate editor; setting `innerText` does not reach the
  component state, so the field would look filled and submit empty. Real
  input events are both the working path and the safe one.
- **The human submits.** The assistant fills the form and stops. No click
  on "Post", no Return in a text field.

Text arrives via the clipboard and a single paste, never as 1400 simulated
keystrokes — that is faster *and* closer to what a person does with a
finished text.

## What was measured

Everything below was verified against the live channel and a private
self-DM on 2026-08-26, not derived from documentation.

| Question | Answer |
|---|---|
| Does a long paste survive? | Yes. 1358 characters landed as text; Discord only converts to `message.txt` past its own 2000-character ceiling, which the renderer already enforces. |
| Are the tag chips clickable? | Only the first nine. The full picker is a dropdown with a search field, and **its list is not alphabetical** (`Work In Progress` sits between `Gardening` and `Mining`). Typing the name is the only reliable selection. |
| Can images be attached? | Yes. There is a real `<input type="file">` behind the "add media" button, so the native file dialog is never opened — and it accepts absolute repository paths directly. |
| Do external image URLs embed? | Yes, including a 38 MB GIF served by GitHub as `application/octet-stream` — comfortably past any candidate attachment ceiling (the exact current value is unverified), which is enough to confirm the attachment ceiling does not apply to URLs at all. First render took ~18 s while Discord proxied the file; later viewers get it cached. |
| Does the URL stay visible? | Only when the message contains something else. A message consisting solely of a media URL is replaced by the medium itself. |
| Is the mod.io link preview useful? | No. It renders mod.io's own corporate card ("Cross Platform Mod Support for Games"), not the mod. |

Two failures are worth recording because they became design rules:

- **The clipboard is shared and volatile.** While a paste was in flight the
  user copied an unrelated string, and it silently replaced the post text.
  Nothing detected it; the mistake was visible only because the stray text
  happened to land at the start of the field.
- **Attachments cannot be reordered or removed reliably.** The thumbnail
  strip collapses after each deletion and does not reliably reopen, and a
  misplaced click lands on the "+" button, which opens the native file
  dialog — that blocks the extension entirely until a human dismisses it.

## Division of labour

**`utils/discord_post.py`** keeps everything deterministic: rendering,
validation, path resolution, limits. No network, no browser. It stays
callable as `--check` from `utils/upload.sh`, where a broken post surfaces
seconds into a release rather than ten minutes in.

**A skill at `.claude/skills/ck-discord-post/`** describes the browser sequence.
It sits beside `new-ck-mod` because it is Core Keeper specific, and takes the
mod name as an argument — the session runs from `core_keeper/`, as it does for
scaffolding.

The seam is Discord's UI. Selectors move, lists are virtualised, positions
shift with the surrounding layout; a shell script would break on the first
redesign, while a model reads the screen. Conversely a model has no
business counting characters.

`upload.sh` cannot trigger the browser step itself — it is a shell script.
It keeps printing the rendered post after a successful publish, which is
the existing reminder that the thread has gone stale.

## Configuration

Three additions to the per-mod `.envrc` (and its tracked `.envrc.example`),
alongside the existing `CK_DISCORD_TAGS`:

- **`CK_DISCORD_THREAD`** — the mod's thread URL. Empty means no thread
  exists, so a new post is created; set means a new version is announced as
  a comment in that thread. Written once, after the first post.
- **`CK_DISCORD_MEDIA`** — pipe-separated relative paths to the *additional*
  images, in attachment order. **The mod's logo is always prepended by the
  process itself**, so this variable holds at most nine entries and an empty
  value simply means "logo only" — a legitimate statement about a mod whose
  function has nothing to show, not an error. This is the opposite of
  `CK_DISCORD_TAGS`, where empty *is* an error, and the `.envrc.example`
  comments must say so.

`CK_DISCORD_MEDIA` takes two kinds of entry, and the value decides which:
a **relative path** becomes an attachment, an **`http(s)` URL** becomes its
own follow-up message. That covers the clips of `auto-rail-bridges`, which
exist only as 38 MB GitHub-hosted GIFs — far past the attachment ceiling,
but unrestricted as URLs. Order is preserved across both kinds:
attachments upload with the post, URLs follow one message at a time. A
separate variable would only force the reader to know in advance which of
two lists a given file belongs in, when the value already says it.

One data file, `utils/ck-discord-tags.json`, holds the twenty forum tags
that were previously hardcoded as `FORUM_TAGS` in `discord_post.py` and are
now read via `forum_tags()`.

`sources/` cannot be scanned to derive any of this. It is a working
directory holding raw material, derived artefacts, published gallery
images and rejected candidates side by side, indistinguishable by
extension, name or size — the same `.mp4` is source material in one mod and
would be the deliverable in another. Which file serves which purpose exists
only in the author's head, which is exactly why it belongs in a file.

## The flow

1. **Reconcile the tag list.** Open the picker, read the live list, update
   `ck-discord-tags.json` on divergence and report what changed. This
   replaces an API call that would need a token: the dropdown is open
   anyway, and reading it costs two clicks.
2. **New thread** — type the title, paste the body, select tags by typing
   their names, upload logo plus configured media in one call.
   **Existing thread** — navigate to `CK_DISCORD_THREAD` and paste the
   version comment rendered from the topmost `CHANGELOG.md` entry.
3. **Clips as separate follow-up messages**, one URL per message. Only a
   message containing nothing else gets its link replaced by the medium.
4. **Hand over.** The human reviews and submits.
5. After a first post, record the resulting thread URL in `CK_DISCORD_THREAD`.

Media are uploaded **once, complete, in final order**. Correcting an
attachment means discarding the draft and rebuilding it — four actions,
deterministic — rather than fighting the attachment widget.

Two verifications are mandatory, both from the clipboard failure: check the
first line of the clipboard *before* pasting, and compare the start of the
field against the expected first line *after*. "Text is in the field" is
not a statement about *which* text.

## Changes to the rendered post

The download link moves into angle brackets, like the source link already
is. The existing comment claims a bare link buys "a single mod.io preview
card" worth having; it buys mod.io's corporate advertisement as the last
thing a reader sees. Suppressing it lets the post end with the mod's own
images.

Version comments are rendered from `CHANGELOG.md` — the topmost entry,
with its `###` section headings dropped and bullets kept. That file is
already the canonical release source that `upload.sh` reads, so no second
place can drift out of step. Changelog prose is written for a technical
reader and occasionally long, so the rendered comment is reviewed before it
is pasted, and the character budget is checked as it is for posts.

## Rejected alternatives

- **Discord API with a user token** — the self-bot vector this design
  exists to avoid.
- **Discord API with a bot token** — legitimate, but the bot would have to
  be a member of the Core Keeper server, and the mod author is not an
  administrator there.
- **Deriving media from a filename convention** — the pattern holds in two
  of four repositories inspected, would force renames in grown repos, and
  would sort by name rather than by intent.
- **A dedicated `sources/discord/` directory** — a third location beside
  `sources/` and mod.io, with ordering forced through filename prefixes.
- **Image URLs inside the post body** — works, but leaves a 95-character
  raw address visible in the prose, and each one costs against the
  2000-character budget.

## Rollout

Threads are created in order of first publication, which the mod.io IDs
record unambiguously — they are assigned sequentially. `disable-durability`
was posted first on 2026-08-26; the remaining mods follow in that order.
