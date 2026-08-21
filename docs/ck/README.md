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
retire it. Which version the text describes is stated at the top of the index,
below.

> **→ [index.md](index.md) is where you start reading.** It lists every
> chapter and routes into them three ways: by **symptom** ("my patch never
> fires"), by **task** ("add an options-menu entry"), and by **starting from
> nothing** if you have never built a mod for this game.

## Scope

This handbook covers the game and the SDK. Individual mods document their own
architecture, iteration history and mod-specific traps in their own
repositories — nothing about a particular mod belongs here, only what holds
for the game itself. The workflow around modding — building, publishing,
running a server, the host this machine plays on — is this repository's
business rather than the game's, and no chapter here depends on it: the
handbook is meant to be useful lifted out of this repository entirely.

## Licence note

Core Keeper modding under Pugstorm's EULA is personal-use and non-commercial.
