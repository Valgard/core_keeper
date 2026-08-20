# Core Keeper modding handbook

How Core Keeper works from a mod's point of view, and how to hook into it
without falling into the traps that make correct-looking code do nothing.

This is a reference work, not a tutorial. It is distilled from building and
shipping mods against Pugstorm's `CoreKeeperModSDK` — so it is **empirical**:
it records what the game was observed to do and what the decompiled assemblies
show, not what any specification promises. Where something was verified only
for a specific case, the text says so rather than generalising.

Knowledge is against Core Keeper **1.2.1.5** unless a passage names a different
version. Facts read out of a decompile are true for the build they were read
from; game updates can and do invalidate them.

> **→ [index.md](index.md) is where you start reading.** It lists every
> chapter and routes into them three ways: by **symptom** ("my patch never
> fires"), by **task** ("add an options-menu entry"), and by **starting from
> nothing** if you have never built a mod for this game.

## Scope

This handbook covers the game and the SDK. Individual mods document their own
architecture, iteration history and mod-specific traps in their own
repositories — nothing about a particular mod belongs here, only what holds
for the game itself. The workflow around modding, from building to publishing,
is this repository's business rather than the game's; [index.md](index.md)
lists where each part of it is written down.

## Licence note

Core Keeper modding under Pugstorm's EULA is personal-use and non-commercial.
