---
name: ck-discord-post
description: Use when announcing a Core Keeper mod in the Discord #available-mods forum — a new thread for a mod that has none, or a version comment in an existing one. Fills the form in the browser; the human submits.
---

# Posting a mod to #available-mods

Fill Discord's form from the mod's own files, then hand over. **You never
submit.** The user clicks "Post" or presses Return; you stop before that.

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
   - Tags: open the picker, **type each tag name** and click the match. Never
     click chip positions — only the first nine are shown and the dropdown is
     not alphabetical.
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
