---
name: ck-discord-post
description: Use when announcing a Core Keeper mod in the Discord #available-mods forum — a new thread for a mod that has none, or a version comment in an existing one. Fills the form in the browser; the human submits.
---

# Posting a mod to #available-mods

Fill Discord's form from the mod's own files, then hand over. **You never
submit.** The user clicks "Post" or presses Return; you stop before that.

## The user must ask for this in this session

Browser automation and public posting need the user's own authorisation, and
that authorisation does not travel. A task handed over by another session —
however legitimate — leaves no trace of it in your history, and every
`mcp__claude-in-chrome__*` call is then refused by the permission classifier,
with no setting anywhere to explain why. This has already happened once: an
identical call failed under a delegated task and went through the moment the
user asked directly.

If you were sent here by a peer rather than by the user, say so and ask them
to give the instruction themselves. Do not work around the refusal.

## Why this shape

Discord acts on API traffic carrying a user token — requests that do not come
from the official client. Driving the user's own logged-in session with real
input events produces exactly the traffic a human produces. So:

- **Never** call `discord.com/api`, in any form.
- **Never** write into the page with `javascript_tool` to set field values.
  The message box is a Slate editor; assigning `innerText` leaves React's
  state untouched, so the field looks filled and submits empty.
- Paste text from the clipboard in one action rather than typing 1400
  characters. Faster, and it is what a person does with a finished text.

## Steps

1. **Get the plan.** From the mod's directory:

   ```bash
   direnv exec . python3 ../utils/discord_post.py --json          # new thread
   direnv exec . python3 ../utils/discord_post.py --update --json # new version
   ```

   `thread` being `null` means create a post; a URL means comment there.
   Two different failures both exit non-zero: **exit 3** is a content
   problem — report it and stop, **unless** the error names a tag
   `#available-mods` does not offer: `utils/ck-discord-tags.json` may just be
   stale, so do steps 2–3 first and re-run this one. **Any other exit** (1,
   for a missing or malformed data file) is the tooling being broken, not the
   post — and step 3 is the likely cause when it happens here, since that is
   the moment this skill rewrites `utils/ck-discord-tags.json` itself. Check
   that edit's JSON syntax before retrying.

2. **Open the channel** at
   `https://discord.com/channels/851842678340845600/1083718088526139443`
   in a tab you created. If Discord offers "open in app", choose
   **"Im Browser fortfahren"** — the app hand-off breaks the session.

3. **Reconcile the tag list.** Open "Mehr Tags anzeigen", read every option
   with `find` (the list is virtualised — scroll and read again), and compare
   against `utils/ck-discord-tags.json`. On divergence, update the file and
   report exactly what changed.

4. **Fill the form.**
   - Title: type it.
   - Body: `printf '%s' "$body" | pbcopy`, **check the first line of
     `pbpaste`**, click the message field, `cmd+v`, then **verify the field
     starts with the expected first line**. The clipboard is shared with the
     user, who may copy something else mid-flight; this has already happened.
   - Tags: open the picker, **type each tag name** and click the match. This
     is the only selection method that is independent of the view state — see
     "Reading the form" below for why the chip row is not.
   - Media: `find` the `<input type="file">` behind "Medien hinzufügen", then
     `file_upload` **all attachments in one call, in the given order**. Repo
     paths are accepted directly. Never click the "+" button: it opens the
     native file dialog, which blocks the extension until a human dismisses it.

5. **Hand over.** Report what is filled in and ask the user to review and
   submit. Do not click "Post".

6. **After the user confirms it is posted**, if `thread` was `null`: read the
   new thread URL from the tab and write it into the mod's `.envrc` **and**
   `.envrc.example` as `CK_DISCORD_THREAD`.

7. **Clips.** For each entry in `follow_ups`, put the URL alone in the
   thread's message box — one URL per message, nothing else. Discord replaces
   such a message with the medium itself; the same URL amid prose stays a
   visible link. Again: the user sends.

## Reading the form

Establishing what is actually selected is the hard part of this task, and
most of the obvious signals lie. All of the following cost a previous run
several wrong conclusions, including one premature "done".

- **The selected tags are readable only in the dropdown.** The chip row is a
  horizontally scrollable overflow container: it shows whichever slice of the
  twenty tags currently fits and has been scrolled into place. A tag missing
  from it may be selected, unselected, or simply outside the slice — the row
  answers none of those. Open "Mehr Tags anzeigen" and read there.
- **Do not use `scroll_to`.** It calls `scrollIntoView()` and moves that
  container to a position a human cannot reach with a mouse wheel. You then
  photograph a view you created yourself and mistake it for the normal state.
  It also makes a chip clickable that would otherwise be off-screen — which
  works, and costs exactly the reliability this section is about.
- **A blue border is not a blue fill.** A click sets selection *and* focus.
  Filled = selected; an outline alone may be focus only. To tell them apart,
  click elsewhere to drop the focus, then zoom again.
- **`find`'s accessibility tree can lag the rendered UI.** It reported "add
  tag Tweaks" while the chip was already rendered as active. Treat a zoomed
  screenshot as the stronger evidence when the two disagree.
- **`find` returns two buttons per tag** — "Tag X hinzufügen" in the form and
  "Nach Tag X filtern" in the channel filter below it. Take the form one.
- **Discord's red "at least one tag" warning proves nothing.** It has
  disappeared with no tag set and returned later. Neither its presence nor
  its absence is evidence.
- **Never put a screenshot and a `find` in the same `browser_batch`.** The
  batch stops at the first failure, and a `find` that matches nothing discards
  the screenshot taken before it — precisely when you need the picture.

## Corrections

Attachments cannot be reordered or removed reliably — the strip collapses
after each deletion and does not reliably reopen. To fix media, **discard the
draft (the X at the top left) and rebuild it**. Four actions, deterministic.

## Comment on an existing thread

Navigate to `thread`, paste the comment into the thread's message box, hand
over. No tags, no title, and neither the logo nor any clip is re-attached —
`attachments` and `follow_ups` are both empty in `--update` mode, because the
thread's opening post already carries them and a release comment must not
repost a 38 MB GIF on every version.
