# Announcing a mod in the community Discord

mod.io and the Steam Workshop distribute a mod; neither announces it. Where
players actually come across new mods is the official Core Keeper Discord's
`#available-mods` channel — a forum channel with written rules that decide how a
post has to be shaped, and with one property of its own that is easy to read
backwards.

This chapter is not about a workflow. Posting is done by hand in Discord's own
client, and how you get the text there is your business. What is worth writing
down is what the channel demands of a post and what happens to it afterwards.

Everything below was read out of the channel on 2026-08-19: the pinned
**"Rules & Guidelines"** post by Bridie (posted 10 March 2023, last edited
2 September 2024) and the thread list beside it. These are somebody else's rules
in somebody else's space — re-read the pin before relying on any of it, because
nothing announces a change to it.

## It is a forum, so one thread per mod

Each mod gets its own thread: a title, a body, and tags drawn from a fixed
vocabulary the moderators maintain. The vocabulary is not free text and not
per-post — it is the channel's own list, it is what readers filter by, and it
changes over months, so read it from the composer rather than from memory.

Two consequences follow from the format alone, before any rule does. A single
post announcing several mods does not fit the channel, and a new version of an
already-announced mod belongs as a comment in that mod's existing thread — a
second thread for the same mod is the kind of thing moderators clean up.

## What the rules require of the post

The pin is six bullets plus a link-sharing disclaimer. Four of them shape what
a post has to contain:

| The rule | What it means for the post |
|---|---|
| *"please make one of the **first lines** of your post information on which versions of the game this mod is compatible with"* | A game-version line at the very top, not a footnote at the bottom |
| *"Please describe what your mod does **in detail** so that users can make an informed decision"* | A one-line blurb is explicitly not enough |
| *"Please try and share a **picture** of what your mod does when applicable"* | A screenshot or clip per mod |
| *"This space is for sharing links for available mods only, please do not create posts asking questions, offering opinions, or requesting mods"* | The channel takes announcements only; questions about a mod go into that mod's own thread, where they are welcome |

The remaining two are about safety rather than format: external links are
expressly allowed but at the reader's own risk — the admins disclaim
responsibility for anything downloaded through them — and malicious links are to
be reported to a moderator rather than argued with.

## What Discord makes of the post

The rules say what a post must contain; what follows is what the client does
with it. Everything here was measured by posting into the channel between
2026-08-26 and 2026-08-28, not read anywhere.

**Discord's Markdown is not mod.io's.** Bold, italics, `##` headings and lists
render as expected. Image syntax does not: an `![alt]` followed by a
parenthesised URL stays on screen as exactly those characters. A description
written for mod.io therefore cannot be carried across unchanged, which is the
reason a mod keeps two of them.

**A message consisting of nothing but a media URL is replaced by the medium.**
Discord drops the link text and shows the image or clip in its place. The same
URL sitting between prose stays a visible link, with the medium rendered
beneath it — so a 95-character raw address ends up in the middle of the
paragraph. Where a clip should appear without its address, it needs a message
of its own.

**An external URL is not subject to the attachment ceiling.** A 38 MB GIF
embeds from a URL although it is far past what can be uploaded as a file. The
first viewer waits while Discord fetches and proxies it — around 18 seconds
for that file — and everyone after that gets it from the proxy cache. The
bytes still travel to every reader, so this buys reach past the limit, not
cheapness.

**A bare mod.io link renders mod.io's own card, not the mod's.** The preview
carries the platform's logo and the strapline *"Cross Platform Mod Support for
Games"* — mod.io serves no mod-specific OpenGraph data for a mod page. A link
wrapped in `<…>` produces no preview at all, which is usually the better
outcome: the post then ends with the author's own images.

**The ceilings**, all of them per message: 2000 characters without Nitro, ten
attachments, five embeds. The mod.io preview counts against the last of those.

**The tag vocabulary is not sorted alphabetically.** In the composer's picker
`Work In Progress` sits between `Gardening` and `Mining`. Its order looks like
the sequence the moderators created the tags in, so a tag cannot be found by
guessing where it should be — which is the concrete reason to read the list
rather than recall it.

## Inactivity hides a post from the default view; it does not remove it

The pin's last line before the guide link is the one that gets misread, and it
is misread by being quoted only up to the comma:

> *"Discord will automatically hide posts with no activity in them after one
> week, but you can still find these posts by navigating to the appropriate tag
> and scrolling down."*

The second half is the substance. What Discord does after the inactivity timer
is **archive** the thread: it drops out of the active listing into the older
posts further down, stays reachable by scrolling or by filtering on a tag, and
comes back up when somebody comments on it. Nothing is deleted, and the timer is
a per-channel setting the moderators chose — one week here, against Discord's
own default of three days.

The channel's own thread list shows this plainly: threads whose last activity
Discord dates as *more than 30 days* ago sit in it, and scrolling to the far end
of it reaches threads from 2023 — as old as the pinned rules themselves. Read
the first half of that sentence alone and you get a deadline — a post that is
gone after a week unless it is kept alive. That reading has been made here, and
it is wrong in a way that changes decisions: it argues for spacing announcements
out so they do not "expire together", when the actual cost of posting several at
once is only that they compete with each other for the top of one list, for as
long as anything else is being posted.
