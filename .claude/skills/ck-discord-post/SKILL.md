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

   **Read the failure before diagnosing it.** `direnv: … is blocked` is the
   likeliest one and says nothing about this skill's own state: an `.envrc`
   stays blocked until `direnv allow` runs in that directory, and the exit
   code looks like any other. Run it and retry.

   It follows **any** edit to the mod's `.envrc` — including the one step 6
   makes below, which is why `direnv allow` is part of that step. So it is not
   a first-run symptom: the run most likely to hit it is a later `--update`
   one, when step 6 was interrupted or the file was touched again afterwards.

   Otherwise: **exit 3** is a content problem — report it and stop, **unless**
   the error names a tag `#available-mods` does not offer, in which case
   `utils/ck-discord-tags.json` may be stale: do steps 2–3 first and re-run
   this one. **Any other exit** means the tooling is broken rather than the
   post — a missing or malformed data file. If you have already run step 3,
   suspect the edit it made there and check its JSON syntax first.

2. **Open the channel, then the composer.** The channel is
   `https://discord.com/channels/851842678340845600/1083718088526139443`;
   open it in a tab you created. If Discord offers "open in app", choose
   **"Im Browser fortfahren"** — the app hand-off breaks the session. Then
   click **"Neuer Post"**.

   **The composer must be open before step 3, not after.** Everything that
   follows depends on it: the tag list, the DOM read that verifies selections,
   and the `form` scope that read relies on. With the composer closed, the tag
   row belongs to the *channel filter* — labelled "Alle", not "Mehr Tags
   anzeigen" — and a page-wide `[aria-pressed]` read returns around fifty
   elements: twenty tags twice, because Discord renders both the bar and its
   popout, plus the reaction buttons of the posts behind it.

3. **Reconcile the tag list — unless it already happened today.**
   `utils/ck-discord-tags.json` carries a `verified` date. If it is today's
   date, skip this step and say so: the channel's vocabulary belongs to
   somebody else and changes over months, while this reconciliation costs
   several browser round-trips, and posting a run of mods in one sitting would
   otherwise repeat it for every single one.

   Otherwise reconcile, and **set `verified` to today afterwards even when
   nothing diverged** — the date records when the list was last confirmed, not
   when it last changed. Leaving it stale is what makes the next session repeat
   the work.

   To reconcile: in the open composer, click **"Mehr Tags anzeigen"** — its
   search field takes focus by itself — and read the whole list in one call:
   `read_page` with the list's `ref_id` and `filter="interactive"`. That
   returns all twenty in channel order regardless of scroll position. Compare
   against `utils/ck-discord-tags.json`; on divergence update the file and
   report exactly what changed.

   If you ever read the page without scoping to the composer, the labels are
   what tell the two lists apart: the composer's buttons are `Tag X
   hinzufügen`, the channel filter's are `Nach Tag X filtern`.

   **Do not scroll and read repeatedly.** The list is virtualised, and the
   mouse wheel skips: one run jumped from position 7 straight to the end, so
   `Mining` and `Misc / Other` were never rendered at all. That reconciliation
   would have reported itself complete while missing two tags.

4. **Fill the form.**
   - Title: type it.
   - Body: `printf '%s' "$body" | pbcopy`, **check the first line of
     `pbpaste`**, click the message field, `cmd+v`, then **verify the field
     starts with the expected first line**. The clipboard is shared with the
     user, who may copy something else mid-flight; this has already happened.
   - Tags: for **each** tag, click "Mehr Tags anzeigen", type the name, click
     the match. Typing the name is the only selection method independent of
     the view state — and **the picker closes after every selection**, so it
     has to be reopened per tag. Typing the second name without reopening it
     does not merely miss: the keystrokes land in the message body and damage
     the text already pasted there, which looks nothing like its cause. A mod
     with a single tag never shows this.

     Then **verify with the DOM read** from "Reading the form" below, once,
     after all of them. Do not click a tag twice because a check said it was
     unselected: every click toggles, and the checks that look authoritative
     here are wrong.
   - Media: `find` the `<input type="file">` behind "Medien hinzufügen", then
     `file_upload` **all attachments in one call, in the given order**. Repo
     paths are accepted directly. Never click the "+" button: it opens the
     native file dialog, which blocks the extension until a human dismisses it.
     `file_upload` caps a single call at 10 MB — its own limit, separate from
     Discord's — so **sum the list every time**, not when it looks large. The
     count tells you nothing: across this family the heaviest mod has four
     attachments at 8.9 MB, while the one with eight comes to 4.7 MB. Only the
     total matters. Then verify, with the read in "Checking the attachments"
     below.

5. **Hand over.** Report what is filled in and ask the user to review and
   submit. Do not click "Post".

6. **After the user confirms it is posted**, if `thread` was `null`: read the
   new thread URL from the tab and write it into the mod's `.envrc` **and**
   `.envrc.example` as `CK_DISCORD_THREAD`. Then run `direnv allow` — an
   edited `.envrc` is blocked until you do, and the next verification fails
   with "is blocked", which reads like a broken script.

   Verify with `discord_post.py --update --json`: it must now report the
   thread, and `tags` and `attachments` must be empty. That proves both
   halves in one call — the URL arrived, and update mode reads it.

7. **Clips.** For each entry in `follow_ups`, put the URL alone in the
   thread's message box — one URL per message, nothing else. Discord replaces
   such a message with the medium itself; the same URL amid prose stays a
   visible link. Again: the user sends.

## Reading the form

Establishing which tags are selected is the hard part of this task. **There is
exactly one reliable answer, and it is not visual.** Every signal that looks
authoritative here has produced a wrong conclusion in a real run — including a
premature "done", and a run that clicked the same tag three times because each
check reported it unselected. Three clicks toggle: off → on → off → on.

**Ask the DOM.** Discord's composer is a real `<form>`, and the channel's
filter list — which carries `aria-pressed` too — sits in a sibling branch, not
above it. So scoping to the form separates them without depending on any label
text:

```javascript
(() => {
  const all = document.querySelectorAll('form [aria-pressed]');
  if (all.length === 0) return 'composer not open — result would be meaningless';
  return Array.from(document.querySelectorAll('form [aria-pressed="true"]'))
    .map(b => b.getAttribute('aria-label').replace(/^Tag | hinzufügen$/g, ''));
})()
```

**This is a read, and the rule against `javascript_tool` above is about
writes.** Setting field values bypasses React's state and produces a form that
looks filled and submits empty; it also has nothing to do with the traffic
Discord acts on. Querying the DOM sends no request and changes nothing. Reading
is allowed; writing is not.

Expect twenty buttons inside the form. **Zero means the composer is not open**,
not that no tag is selected — the guard exists because `form` matches the
channel's search form when the composer is closed, and "nothing selected" and
"wrong question" would otherwise look identical.

Why nothing else works:

- **The button's label never changes.** Discord keeps
  `aria-label="Tag X hinzufügen"` whether or not the tag is selected —
  selection lives only in `aria-pressed` and a `selected_…` class, and neither
  `find` nor `read_page` surfaces either. The state is not unreliable through
  those tools; it is invisible to them. (An earlier version of this file called
  it a lag in the accessibility tree. It is not a lag, and that wording invited
  exactly the false conclusion above.)
- **The chip row answers nothing.** It is a horizontally scrollable overflow
  container showing whichever slice of the twenty currently fits and has been
  scrolled into place. Nor does the leading tag icon help: it sits *outside*
  that container and stays put while the row scrolls, so "the icon is still at
  the left" says nothing about the scroll position.
- **Do not use `scroll_to`.** It calls `scrollIntoView()` and moves that
  container to a position a human cannot reach with a mouse wheel. You then
  photograph a view you created yourself and mistake it for the normal state.
- **A blue border is not a blue fill.** A click sets selection *and* focus.
  Filled = selected; an outline alone may be focus only. Only relevant if you
  are reading pixels at all — prefer the DOM read.
- **Discord's red "at least one tag" warning proves nothing.** It has
  disappeared with no tag set and returned later. Neither its presence nor its
  absence is evidence.
- **Never put a screenshot and a `find` in the same `browser_batch`.** The
  batch stops at the first failure, and a `find` that matches nothing discards
  the screenshot taken before it — precisely when you need the picture.
- **Take coordinates only from the most recent screenshot.** The viewport
  changes size between calls — one run went from 1456×819 to 1105×1113 while
  Discord was still loading, and a single session has produced three different
  sizes. Coordinates read from an earlier picture then land somewhere else,
  and a click that misses looks like an element that does not respond.

One selector detail, if you ever need the title field: it is a
`textarea[placeholder="Titel"]`, not an `input`. The `input` form of that
selector returns `null` silently and looks like a closed composer.

## Checking the attachments

**Do not check the file input.** After `file_upload`, `form
input[type="file"].files` is **empty** — Discord moves the files into its own
state immediately and resets the input. It is the first thing anyone reaches
for, and it reports a successful upload as a failed one.

Read the previews instead. Each attachment gets one, labelled `Vergrößerte
Bildanzeigen für <filename> öffnen`:

```javascript
Array.from(document.querySelectorAll('form [aria-label^="Vergrößerte Bildanzeigen"]'))
  .map(b => b.getAttribute('aria-label'))
```

One entry per attachment, **in order**, so a single read confirms both that
everything arrived and that the sequence is the one you passed — the logo
first, then the configured media. Order matters because Discord's grid lays
the attachments out in it, and it cannot be corrected afterwards: see
"Corrections" below.

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
