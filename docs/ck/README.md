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

## What is not here

This handbook covers the game and the SDK. The surrounding workflow lives
elsewhere in this repository:

| Topic | Document |
|---|---|
| This repository's own scripts, variables and commands — the concrete form of [Toolchain](toolchain.md) | [`../../README.md`](../../README.md) |
| Publishing to mod.io | [`../publishing.md`](../publishing.md) |
| Running a dedicated server locally | [`../dedicated-server.md`](../dedicated-server.md) |
| macOS/CrossOver loader specifics and the game-DLL patches | [`../macos-crossover-loader.md`](../macos-crossover-loader.md) |
| One pixel-art authoring workflow — the one used in this repo, not a requirement | [`../pixaki-format.md`](../pixaki-format.md) |

Individual mods document their own architecture, iteration history and
mod-specific traps in their own repositories. Nothing about a particular mod
belongs here — this handbook only records what holds for the game itself.

## Licence note

Core Keeper modding under Pugstorm's EULA is personal-use and non-commercial.
