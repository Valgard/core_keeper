# Refill Ore Boulders — Design

- **Date:** 2026-08-08
- **Mod:** `refill-ore-boulders` (new repo)
- **Status:** design settled, pending implementation

## Problem

Ore boulders in Core Keeper have no separate "remaining ore" counter —
their remaining yield **is** their `HealthCD.health`. Every pickaxe swing
and every drill tick subtracts damage; at `0` the boulder is destroyed and
gone for good.

The third-party mod **Eternal Ore Boulders** normally prevents this, but it
moved to a new mod.io ID and was therefore not loading for a while. With
**Drill Faster** active (11× default drill speed), several boulders were
worn down close to zero in that window.

Eternal Ore Boulders would not fully recover them either: it heals only
below a 10 % threshold, so a boulder sitting at, say, 30 % stays damaged
until further mining pushes it under the threshold.

What is needed is a way to top up the already-damaged boulders on demand.

## Decisions

| Question | Decision |
|---|---|
| Trigger | **chat command** `/refillboulders` (CoreLib) |
| Scope in the world | **everything currently loaded** — no radius, `sender` position unused |
| Object selection | **`RequiresDrillCD`** — no ObjectID list |
| Amount | set `health = maxHealth` (full), skip boulders already full |
| Boulders at `health == 0` | skipped — they are mid-destruction |
| `requiredOn` | `0` (None) |
| Naming | repo `refill-ore-boulders` / namespace `RefillOreBoulders` / display name "Refill Ore Boulders" |
| Deferred | continuous top-up, radius parameter, per-boulder feedback |

### Why a command rather than a permanent system

Continuously holding every boulder at full health would subsume both the
repair and the protection, but it duplicates what Eternal Ore Boulders
already does once that mod loads again. This mod deliberately covers only
the one-off repair; permanent protection stays with the third-party mod.

Consequence to keep in mind: the command **does not stop further
consumption**. Boulders keep being worn down (11× faster than vanilla with
Drill Faster) until Eternal Ore Boulders is loading again.

## Object selection — `RequiresDrillCD` is exactly the ore boulders

Verified against the unpacked prefabs rather than assumed. `RequiresDrillCD`
is added by exactly one converter:

```csharp
// Pug.ECS.Conversion.decompiled.cs:1146-1156
public class DestructibleObjectConverter : SingleAuthoringComponentConverter<DestructibleObjectAuthoring>
{
    protected override void Convert(DestructibleObjectAuthoring authoring)
    {
        EnsureHasComponent<DestructibleObjectCD>();
        if (authoring.requiresDrill)
        {
            EnsureHasComponent<RequiresDrillCD>();
        }
    }
}
```

Of the 177 prefabs carrying `DestructibleObjectAuthoring`, exactly **12**
set `requiresDrill: 1` — the ten ore boulder types (Copper, Tin, Iron,
Gold, Scarlet, Octarine, Galaxite, Solarite, Pandorium, Relucite) plus two
scene variants of them.

Two consequences:

- **No ObjectID list is needed or wanted.** A hardcoded list of the ten IDs
  would be redundant today and would silently miss any ore tier a future
  game update adds.
- **Amber Boulder and Crystal Meteor Boulder are excluded** — both are
  `DestructibleObject` but not drill-required. The flag happens to draw
  exactly the line between "renewable ore source" and "one-off world
  object", so that distinction does not have to be modelled by hand.

## Architecture

Two source files, following the established bootstrap ↔ logic split:

- **`RefillOreBouldersMod.cs`** — the `IMod` bootstrap. In `EarlyInit()`:
  resolve the own `LoadedMod`, load CoreLib's `CommandModule`, call
  `CommandModule.AddCommands(modInfo.ModId, Name)`. Also holds the host
  predicate the command uses to guard itself.
- **`Commands/RefillBouldersCommand.cs`** — `IServerCommandHandler`,
  trigger name `refillboulders`, containing all the refill logic.

Dependency: **CoreLib**, declared as `required` in the ModBuilderSettings
`.asset`.

The pattern is taken from **Drill Faster**, which registers a server
command the same way (its shipped Roslyn sources are readable under
`mod.io/5289/mods/6037779_*/Scripts/`).

### Flow

1. Player types `/refillboulders`.
2. CoreLib dispatches to the server side and calls
   `Execute(parameters, sender)`.
3. Host gate — if this instance is neither host nor single-player, return
   an error instead of running to no effect.
4. Query `RequiresDrillCD` + `HealthCD` (read-write), with
   `EntityQueryOptions.IncludeDisabledEntities`.
5. Per hit: if `0 < health < maxHealth`, set `health = maxHealth` and count.
6. Report: `Refilled N ore boulder(s).` or `No damaged ore boulders loaded.`

`sender` is intentionally unread — with "everything loaded" chosen as the
scope, a position lookup would be dead code.

### Why `IncludeDisabledEntities` is mandatory

CK disables entities beyond `DISTANCE_FROM_PLAYER_TO_UPDATE_ENTITY = 40`
tiles while keeping them loaded out to 200–300
(`KeepAreaLoadedCD { ImmediateLoadRadius=200, StartLoadRadius=250,
KeepLoadedRadius=300 }`). Without the flag the command would reach only
40 tiles despite the much larger load bubble. Eternal Ore Boulders sets the
same option in its own query.

The load radii are also the hard ceiling on reach: what is not loaded does
not exist as an entity and cannot be touched by any command.

Eternal Ore Boulders additionally filters on `DontDropSelfCD`. That is not
adopted here: the prefab survey above shows `RequiresDrillCD` already
selects exactly the ore boulders, so the second component would only narrow
the query without excluding anything, at the cost of an unexplained
condition.

### Why direct `EntityManager` access is sound here

CoreLib's `CommandCommSystem` is itself a `PugSimulationSystemBase`, and
handlers run from its `OnUpdate()`. The command body therefore executes on
the ServerWorld main thread inside the ECS frame. Writing components is
fine there; creating or destroying entities would not be, and is not done.

## Error handling

Three cases, each with its own message rather than silent no-ops:

| Case | Response |
|---|---|
| Not host / not single-player | `CommandStatus.Error` |
| `ServerWorld` unavailable | `CommandStatus.Error` |
| Zero matches | informational — "all full" is a valid answer, not a failure |

## Manifest

Both fields are set in the ModBuilderSettings `.asset` (`metadata:` block),
not in a hand-written `ModManifest.json` — that file is build-generated.

- **`requiredOn: 0`** (None). The mod changes neither the item nor the
  recipe database, so it creates no client/server divergence. A `Server`
  flag would block joining unmodded servers; a `Client` flag would force
  the mod on anyone joining. Neither buys anything here. CoreLib itself
  ships `requiredOn: 0`.
- **`skipSafetyChecks: false`** initially — see risks.

## Risks

**Sandboxed component writes.** Reading the live ECS from mod scripts is
verified in this family of mods; `EntityManager.SetComponentData` is not.
If the Roslyn sandbox rejects it, this surfaces immediately at load time as
`CompileFailed`. Fallback: move the refill into a dedicated
`ServerSimulation` system that the command merely triggers — the pattern
Eternal Ore Boulders demonstrably runs sandbox-clean.

**Visual feedback.** `HealthCD` is a `[GhostField]`, so the change
replicates to the client. That the boulder's sprite stage and progress bar
follow has to be confirmed in-game. Eternal Ore Boulders writes the same
field, so the risk is small but not zero.

## Verification

In-game, since this repo family has no automated test harness:

1. Damage an ore boulder visibly with a pickaxe.
2. Run `/refillboulders`.
3. Confirm the reported count matches expectation and the boulder is
   visually full again.
4. Confirm the zero-match path reports cleanly when run twice in a row.
