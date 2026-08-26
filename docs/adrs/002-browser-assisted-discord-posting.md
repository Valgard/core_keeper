# Announce mods in Discord through the browser, not through its API

## Context and Problem Statement

Every mod here is announced in a forum thread in the Core Keeper Discord's
`#available-mods` channel, and updated there when a new version ships.
`utils/discord_post.py` already rendered that text, but everything after it was
manual: copy, open Discord, retype the title, tick the tags, drag in the
images. Mechanical work, and each step a place to get it wrong — a tag the
channel does not offer, an image forgotten, a compatibility line from the
previous game build.

Automating it runs into what Discord forbids: driving a user account from
outside the official client. How much of the work can be automated depends
entirely on what that rule actually covers.

## Decision Drivers

- What Discord detects and acts on is **API traffic carrying a user token** —
  requests without the official client's headers, in patterns no human
  produces. The prohibition is about how the traffic is generated, not about
  whether a human typed each character.
- The author publishes under their own account, in a community they do not
  administer. A wrong post is a social cost, not a revertible commit.
- The rendered text is already correct and tested; what was missing was
  transport.

## Considered Options

- **Browser automation of the user's own session**, with the human submitting
- **A REST client using the user's token**
- **A Discord bot**
- **Better manual preparation** — render, copy to the clipboard, open the right
  page, and stop there

## Decision Outcome

Chosen: **browser automation of the user's own session, with the human
submitting.**

An extension drives the logged-in session with real input events, so the
resulting traffic is the traffic that session produces anyway. Three rules
follow and are not negotiable:

- No calls to `discord.com/api`, for anything — including reading the
  channel's tag list.
- No writing into the page's state from injected JavaScript. The message box
  is a Slate editor; assigning to it leaves React's state untouched, so the
  field looks filled and submits empty. The working path and the safe path
  happen to be the same one.
- The action that publishes anything is performed by the person. The
  automation fills the form and stops.

Text arrives through the clipboard in a single paste rather than as a
thousand simulated keystrokes — faster, and closer to what a person does with
a finished text.

The work splits along the seam this creates. `utils/discord_post.py` keeps
everything deterministic — rendering, validation, path resolution, limits —
and emits it as JSON. A skill under `.claude/skills/ck-discord-post/` consumes
that and drives the UI. Selectors move, lists are virtualised, positions shift;
a script breaks on the first redesign, while a model reads the screen.
Conversely a model has no business counting characters.

### Consequences

- The channel's tag vocabulary becomes repository data
  (`utils/ck-discord-tags.json`), refreshed by reading the open dropdown —
  the substitute for the API call that would have needed a token.
- Three `.envrc` variables carry what only the author knows: the thread URL
  (empty means none exists yet), the media list, and the forum tags. `sources/`
  cannot be scanned to derive any of it — raw material, derived artefacts,
  published gallery images and rejected candidates sit there side by side and
  are indistinguishable by name, extension or size.
- Clips too large to attach are posted as their own follow-up messages, one
  URL each: Discord replaces a message containing nothing but a media URL with
  the medium itself, while the same URL amid prose stays a visible link.
- Nothing can post without a person, by construction. That is the point, and
  it also caps how much this can ever save.

## Pros and Cons of the Options

**Browser automation, human submits**

- Good: generates exactly the traffic the session generates anyway
- Good: the irreversible step stays with the person who owns the account
- Bad: UI-dependent, so it needs a model rather than a script
- Bad: the clipboard is shared with whatever else the user is doing — the
  handover has to be verified on both sides, before and after pasting

**REST client with a user token** — rejected. This is precisely the
self-bot pattern Discord acts on.

**A Discord bot** — rejected. Legitimate, but a bot must be a member of the
server, and the author does not administer that community.

**Better manual preparation** — rejected as insufficient. It leaves the entire
error-prone part, the form itself, exactly where it was.

## More Information

Discord's observable behaviour was measured in the live channel on 2026-08-26
rather than taken from documentation, and several results contradicted
reasonable expectations: a 38 MB GIF embeds from an external URL although it
is far past the attachment ceiling; the tag dropdown is not sorted
alphabetically, so only typing a name selects reliably; mod.io's link preview
advertises the platform rather than the mod, which is why both links are now
suppressed. Two failures during the work became rules of their own — an
unrelated copy silently replaced a post mid-paste, and attachments turned out
to be unreorderable once uploaded, so media is uploaded once in final order or
the draft is discarded and rebuilt.

The raw design document that preceded this decision, with the full measurement
table:

```
git show "$(git rev-list -1 HEAD -- docs/specs/2026-08-26-discord-post-automation-design.md)^:docs/specs/2026-08-26-discord-post-automation-design.md"
```
