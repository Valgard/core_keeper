# Core Keeper modding handbook

How Core Keeper works from a mod's point of view, and how to hook into it
without falling into the traps that make correct-looking code do nothing.

This is a reference work, not a tutorial. It is distilled from building and
shipping mods against Pugstorm's `CoreKeeperModSDK` — so it is **empirical**:
it records what the game was observed to do and what the decompiled assemblies
show, not what any specification promises. Where something was verified only
for a specific case, the text says so rather than generalising.

That also means it is **bound to a game version**: a fact read out of a
decompile is true for the build it was read from, and an update can quietly
retire it. Which version the text describes is stated at the top of the index.

It is also written to be **liftable**: no chapter depends on the repository it
happens to live in. Individual mods document their own architecture and their
own traps in their own repositories; what is collected here is what holds for
the game whoever is building against it.

**[index.md](index.md) is where you start reading.** It lists every chapter and
routes into them three ways: by **symptom** ("my patch never fires"), by
**task** ("add an options-menu entry"), and by **starting from nothing** if you
have never built a mod for this game.

## Licence note

Core Keeper modding under Pugstorm's EULA is personal-use and non-commercial.
