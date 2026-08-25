# Patching Harmony and ECS

Core Keeper is a DOTS game whose simulation systems are Burst-compiled, and mods
are Harmony patches compiled at load time inside a sandbox. That combination
produces failure modes that look nothing like a normal Harmony problem: a patch
that loads cleanly and never fires, a system whose body is not in the file you
are reading, and a fix that works in single-player and is inert on a dedicated
server. This chapter covers how to make a patch bind, how to make it fire, and
how to read and write the live ECS world once it does.

Line numbers quoted below (`Pug.Other:295735`) are offsets into the decompiled
game assemblies — see [reverse-engineering](reverse-engineering.md) for how to produce that decompile.

## Three failure modes, three different causes

Before changing anything, classify the symptom. They have nothing in common
except that your code does not run.

| Symptom | Cause | Fix |
|---|---|---|
| `ArgumentException: Undefined target method for patch method …` at load | Harmony cannot resolve the target signature — typically an `in`/`ref` parameter | `argumentVariations` (below) |
| Mod loads, `safetyCheck=True`, patch binds, prefix never fires | The target is Burst-compiled; the managed IL you patched is never executed | `BurstDisabler` (below) |
| Works when a player hosts, dead on a dedicated server | `BurstDisabler` registered too late on the dedicated server | manual `AddWorld` pass (below) |
| Mod does not compile at all (`CompileFailed`) | Sandbox rejection, not a patching problem | [sandbox rules](sandbox.md) |

## Why a Burst-compiled `OnUpdate` cannot be intercepted

Harmony rewrites managed IL. A Burst-compiled system never runs that IL, so
there is nothing for the patch to intercept — and Harmony has no way to tell you
that, because the bind itself succeeded.

The dispatch chain is worth knowing, because the fix only makes sense against
it. `WorldUnmanagedImpl.UpdateSystem` invokes `UnmanagedUpdate` as a
`$BurstDirectCall` (`Unity.Entities:67217`), which takes the Burst path whenever
`BurstCompiler.IsEnabled`. `CallForwardingFunction` then runs *inside* Burst,
where `CheckBurst` is `[BurstDiscard]` and therefore stripped — so its `status`
stays `true` and the system's Burst function is called unconditionally. The
per-system `BurstFunctionEnabledBits` flag is never even read on that path.

## `BurstDisabler` — moving a system off Burst

`BurstDisabler` ships in `PugMod.SDK.Runtime`, which the wizard-generated
runtime asmdef already references. Using it costs no dependency — in particular
not CoreLib.

```csharp
public void Init()
{
    BurstDisabler.DisableBurstForSystem<ChangeDurabilitySystem>();
}
```

### The call does two entirely different things, depending on the system

`DisableBurstForSystemInternal` (`PugMod.SDK.Runtime:798`) first calls
`TypeManager.IsSystemType` — the check that throws a `NullReferenceException`
when `TypeManager` is not yet initialised, which is why this cannot run in
`EarlyInit` — and then branches on `TypeManager.IsSystemManaged`, **returning
early** for a managed system. The two paths share nothing beyond the entry
point:

| System shape | What actually happens |
|---|---|
| **`ISystem` struct** (unmanaged) | the two-halves mechanism below |
| **`SystemBase` class** (managed) | `PatchManagedSystem` Harmony-patches the system's own `OnCreate`/`OnStartRunning`/`OnUpdate`/`OnStopRunning`/`OnDestroy` with prefixes and postfixes that toggle `BurstCompiler.Options.EnableBurstCompilation` around each call — immediately, globally, with no world registry involved |

**Everything that follows in this section — the two halves, the per-world
snapshot, and the dedicated-server trap built on it — applies to the `ISystem`
path only.** A managed `SystemBase` never reaches
`SystemTypesToDisableBurstFor`, so `AddWorld` has nothing to arm for it and the
server trap does not arise.

Which shape you are looking at is worth checking before reasoning about any of
it: in the decompile it is `public struct X : ISystem` versus `public class X :
SystemBase`. Every system this handbook cites as a worked example —
`ChangeDurabilitySystem`, `AddSkillValueSystem`, `PetHandlerSystem`,
`EquipmentUpdateSystem` — is an `ISystem` **struct**, which is also why the
managed path is the less-travelled one here and correspondingly less tested.

### The `ISystem` call has two halves, and only one of them is global

| Half | What it does | Scope |
|---|---|---|
| 1 | `SystemBaseRegistry.SetBurstEnabledForSystem(type, false)` → `BurstFunctionEnabledBits = 0` | global per system type, effective immediately |
| 2 | `SystemTypesToDisableBurstFor.Add(type)` | armed **per world**, only by `BurstDisabler.AddWorld(world)` |

Half 2 is the *gate* to half 1. `DisableBurstForSystemPatch.Prefix` — the SDK's
own Harmony patch on `UpdateSystem`, gated on
`SystemHandlesToDisableBurstFor.Contains(sh)` — flips `EnableBurstCompilation =
false`, which makes the managed path run; only then does half 1 select
`ManagedFunctionsUnBursted`, the `OnUpdate` you can patch. If half 2 never armed
for the world your system runs in, half 1 is dead weight.

The same patch's `Postfix` restores `EnableBurstCompilation` to whatever it was
before the `Prefix` ran. So the bypass is a **window around that one system's
`UpdateSystem` call, not a lasting state change** — it closes the moment
`OnUpdate` returns, and the next system to update runs Burst-compiled again
unless it is armed too.

### Nested jobs need the `AndJobs` variant

`DisableBurstForSystem<T>` is not enough when the system's real work lives in a
nested job. `EquipmentUpdateSystem` (`Pug.Other:419765`) does everything in
`UpdateJob`, which carries its own `[BurstCompile]` (`:419767`) and calls
`PlaceObjectSlot.UpdateEquipment` (`:419899`). With the plain variant, **no**
patch on that path fires; with `BurstDisabler.DisableBurstForSystemAndJobs<T>()`
(`PugMod.SDK.Runtime:783`) all of them do.

**The criterion is what you patch, not which system it belongs to.**
`DisableBurstForSystem<T>` calls `DisableBurstForSystemInternal(type,
burstEnabled, addCompleteDependencyPatch: false)` (`:780`);
`DisableBurstForSystemAndJobs<T>` passes `true` (`:785`). For an unmanaged
`ISystem`, `PatchSystem` (`:862-870`) does nothing with that flag off — it
builds an empty method list and stops. With the flag on, it adds exactly one
more thing: a postfix on `OnUpdate(ref SystemState)` that calls
`state.Dependency.Complete()`. That one postfix is the entire difference
between the two calls.

It is also why `EquipmentUpdateSystem` needs it. Its `OnUpdate`
(`Pug.Other:420556`) ends `state.Dependency =
__ScheduleViaJobChunkExtension_0(new UpdateJob { … })`, and that extension
returns a `.Schedule(...)` call — not `.Run(...)`. The job is *queued*, not
executed, before `OnUpdate` returns, so `UpdateJob` runs after the bypass
window above has already closed and Burst is back on. `Complete()` is what
pulls that execution back inside the window.

**Trap: the shortcut "does `OnUpdate` assign a `JobHandle` to
`state.Dependency`? then use `AndJobs`" is wrong.** `ChangeDurabilitySystem`,
`AddSkillValueSystem` and `PetHandlerSystem` all schedule a job from inside
their own `OnUpdate` the same way `EquipmentUpdateSystem` does, and all three
are correctly served by the plain variant — because what gets patched on them
is `OnUpdate` itself, which runs inside the window regardless of what it goes
on to schedule afterwards. `EquipmentUpdateSystem` differs only because its
actual patch target, `PlaceObjectSlot.UpdateEquipment`, sits inside the
scheduled job, not inside `OnUpdate`.

A system whose `OnUpdate` you patch directly, with no job in between, gets away
with the plain call.

**Trap:** the log line

```text
BurstDisabler: Patched OnUpdate on <System> for job burst disabling
```

is **not** evidence that your hooks are live. It comes from the `AndJobs`
variant's dependency patch, which is applied regardless of the per-world
snapshot — so it appears even while the bypass is inactive.

### What it costs is not established

Taking a system off Burst means its `OnUpdate` runs as managed code instead of
compiled native code, so there *is* a real cost. How large it is for a given
system is an open question, and this handbook cannot answer it.

What exists is a single anecdote, recorded here because the question comes up
immediately and because knowing the evidence is thin is better than guessing:
one mod Burst-disables `EquipmentUpdateSystem` and its author noticed no frame
drop while laying rails with bridges auto-placed beneath them, with several of
his own mods holding systems un-Bursted at the same time.

**Read that for exactly what it is.** One person, one mod, one system, one
activity, judged by eye with no profiler. It does not establish that
Burst-disabling is cheap in general — and there is reason to think this
particular case sits at the *favourable* end: the observation covers a burst of
player-driven activity, not a system grinding large entity sets every frame.

It also came with an attribution problem worth repeating: the one place that
did feel slower was a large base, which is also where an unrelated
inventory-scanning mod does its heaviest work. A cost that shows up only where
two mods overlap belongs to neither until it has been isolated.

**If the cost matters to your mod, measure it.** The variables that plausibly
dominate are how often the system ticks and how much work it does per tick, so
compare the same scene with your `DisableBurstForSystem*` call present and
removed, and look at frame time rather than at whether it "feels" the same. That
is a small experiment, and it beats both this anecdote and any assumption you
would otherwise make.

## The dedicated-server trap

**`DisableBurstForSystem<T>()` in `IMod.Init()` is a silent no-op on a dedicated
server.** No error, no log line; the prefix simply never fires. The mod works
whenever a player hosts and does nothing on a dedicated server.

**"Does nothing in multiplayer" is the wrong scope, and this file said it until
2026-08-24.** A hosting client is not affected: `StartEcs` creates the
ServerWorld in that same process (`Pug.Other:2654`, taken whenever the process
is not a pure client), adds it to `_allWorlds`, and arms both worlds at
`:2673-2675` — all of it after `Init()` on the client ordering. So host-based
multiplayer works, and the defect belongs to the dedicated-server binary alone.
The distinction matters when reading a bug report: "works for me in
multiplayer" from a host neither reproduces nor refutes it.

The cause is an inverted lifecycle. `BurstDisabler.AddWorld` is called from
exactly one place, `ECSManager.StartEcs` (`Pug.Other:2675` in the client build,
`:2656` in the server build), and it **snapshots** the types registered up to
that moment. Nothing back-fills that snapshot for a world already passed to
`AddWorld` — but the set itself is not permanent, and a later world load rebuilds
it correctly; see the bound on this below.

Note what this does *not* mean: the call is present and runs on both builds, at
the end of `ECSManager.StartEcs` once the worlds have been created. The server
does not skip it. So "`AddWorld` never runs server-side" is the wrong diagnosis —
it runs, it is simply reached before your `Init()` had a chance to register
anything.

The two builds *do* differ right beside that call, in a way worth knowing if you
read the code: the client kicks off authoring-data conversion as a coroutine and
falls straight through to `AddWorld`, so the conversion has not run yet; the
server drains the same enumerator synchronously first. That difference does not
affect the snapshot problem, but it does mean the surrounding state is not the
same on the two sides.

| Process | Order (measured in the logs) | Result |
|---|---|---|
| Client | `Init()` first, worlds built afterwards | registration precedes the snapshot → works |
| Dedicated server | worlds built first (`adding worlds to the update loop`), `Init()` afterwards | snapshot empty → patch dead |

**The decisive file is not in the decompile at all, which is why measurement is
the only route.** The server build's own guard names its real entry point —
`UnityEngine.Debug.LogError("Server should start from ServerMain!")`
(`Pug.Other:361103`, server build) — and `ServerMain` exists nowhere as a type:
that string is its single occurrence in either checkout, with zero `class`/`struct`
declarations. Anyone tracing the boot order follows the guard to a file that was
never decompiled. Check this before attempting a derivation; it is cheap and it
settles the question.

**That table is a measurement, and no derivation has replaced it — one was
tried and was wrong.** The tempting mechanism is: `StartEcs` is reached from
`SceneHandler.Awake` (`Pug.Other:361075`, calls at `:361114`/`:361119` in the
server build) while `IMod.Init()` comes from `Loader.Update`
(`PugMod.Loader:1157`, `:1159`), so Unity's rule that every `Awake` precedes
every `Update` fixes the order. **It does not.** `Loader.Update` has a second
caller: `Manager.EarlyInit` (`Pug.Other:263334`), which is a
`[RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterAssembliesLoaded)]`
(`:263245`) and therefore runs *before* any scene `Awake`. The lifecycle rule
never applies to that path, so it cannot settle the ordering. Nor is the hosting
side "menu-triggered" as a contrast: the client's own world-creating `StartEcs`
(`Pug.Other:365349`) sits in `SceneHandler` too, and the menu path
(`RadicalJoinGameMenu.Join`, `:337913`) passes `worldId: -1` and creates no
ServerWorld at all.

Written down because the wrong derivation was published into a pull request
before a review caught it: three earlier passes had flagged the flat "the order
is reversed" phrasing as unsupported, and the response was to invent a mechanism
rather than to mark the claim as observed. A false mechanism is worse than an
honest measurement — the measurement invites verification, the mechanism invites
trust. State the ordering as measured; it is.

### The fix

Follow every `DisableBurstForSystem*` call with a manual pass over the existing
worlds:

```csharp
using Unity.Entities;   // World

public void Init()
{
    BurstDisabler.DisableBurstForSystem<ChangeDurabilitySystem>();
    foreach (var world in World.All)
        BurstDisabler.AddWorld(world);
}
```

`World.All` is sandbox-legal (`safetyCheck=True` on both client and server), and
the registry behind `AddWorld` is a `HashSet`, so the pass is a harmless no-op in
the client ordering.

**Write it unconditionally, and note that the reason is stronger than "the extra
pass is harmless".** Nothing in the SDK pins the ordering down: `AddWorld` and
`DisableBurstForSystem*` carry no doc comment, attribute or contract of any kind
about call order, and the client/server split above is a log measurement, not an
API guarantee. Branching on the build would therefore rest on an ordering the
SDK never promised — the unconditional pass holds even if a future build changes
which one runs first. Prefer that argument over the no-op one; it survives the
thing the other depends on.

**The order in that snippet is mandatory, not stylistic.** `AddWorld` only
iterates `SystemTypesToDisableBurstFor` as it stands at the moment it runs —
call `DisableBurstForSystem*` for everything you want it to see *before* the
`World.All` pass, or the pass walks a set that is still empty and arms nothing.

**What the pass repairs is the *first* `StartEcs` of the process, not a
permanent defect.** Unloading the worlds calls `BurstDisabler.ResetWorlds`
(`PugMod.SDK.Runtime:841`) from `ECSManager.UnloadWorldsInternal`
(`Pug.Other:2938`, server `:2914`), which clears the handle set; the next
`StartEcs` then runs its own `AddWorld` pass with the registration already in
place, so a world reload arms correctly on its own. That is why the bug reads as
"dead from launch" rather than intermittent — and why a dedicated server, which
loads its world once at startup and keeps it, never gets the second chance a
world switch would hand it.

**`EarlyInit` is not the fix.** Moving the registration there fails on client
*and* server: `TypeManager` is not initialised that early, so
`TypeManager.IsSystemType` throws `NullReferenceException` out of
`DisableBurstForSystemInternal` and the registration never happens at all.

### The pass is load-bearing — measured, not assumed

A counter placed in `IMod.Init()`, reporting how many of the worlds `World.All`
saw at that point actually got armed by the manual pass above, read:

```text
Client            armed by this pass in  0/6  live world(s)
Dedicated Server  armed by this pass in  1/12 live world(s)
```

On the server, that one armed world is the manual pass's own doing: `StartEcs`'s
own call to `AddWorld` (above) had already taken its snapshot before `Init()`
ran, so without the `foreach` loop the count would read `0/12` instead. This
turns "the manual pass matters on the server" from a derivation into a
measurement.

**On the client, `0/N` with `N > 0` is the healthy result, not a fault.**
`Init()` runs before `ServerWorld` and the client's own simulation world are
created, so at the moment the counter above reads, none of the worlds the mod
actually cares about exist yet to arm — that is not the dedicated-server bug,
it is the client working as intended: `StartEcs` runs its own `AddWorld` pass
afterwards, once those worlds exist, and by then the registration from `Init()`
is already in place. A self-check written against this counter — warning
whenever `worlds > 0 && armed == 0` — fires on every healthy client. **No
unhealthy state is observable from inside `Init()`**, so do not build a
self-check there; check after the worlds you actually depend on exist, not at
registration time.

### How the breakage presents itself

The client's own patch still works and suppresses its *prediction* — a
durability system, for instance, sits in `EndPredictedSimulationSystemGroup` —
but the server stays authoritative and its ghost snapshot overwrites the value a
few ticks later. The player sees the effect flicker in and revert.

Mods usually look half-broken rather than broken, because patches on *managed*
methods (`SaveManager`, `PlayerController`, `PetExtensions`, …) are evaluated by
the client itself and keep working. Only the ECS half goes quiet.

Two variants worth recognising, both of which hide the problem further:

- The system runs in every world, but its input component is created only
  `if (isServer)` — so the client patched a system that never had any work to do.
- The system is declared `WorldSystemFilterFlags.ServerSimulation` only — so
  there is no client-side copy at all and the effect is completely dead.

**The SDK's own documented example is the second variant.** Pugstorm's
`BurstDisabler Example` page patches `SpawnEnvironmentObjectsInNewAreaSystem`,
which is a `struct : ISystem` carrying
`[WorldSystemFilter(WorldSystemFilterFlags.ServerSimulation, …)]`
(`WorldGen:2836-2839`) — so it is on the trap's `ISystem` path *and* has no
client-side copy. That example works when the player hosts (the hosting process
runs a server world of its own) and does nothing on a dedicated server. Useful
as the canonical instance, and as a reminder that the official docs are not a
counter-argument to any of this: they simply do not cover the case.

Anything server-authoritative is in the blast radius: XP and skill grants,
durability, pet levelling, world simulation.

### Proving a patch is live on the server

Put a `Debug.Log` in the **static constructor** of the `[HarmonyPatch]` class.
An explicit static ctor suppresses `beforefieldinit`, so it fires immediately
before the first `Prefix()` call — the line appearing in the *server* log is the
proof that the patch is live there.

Two caveats make an absent line meaningless:

- **An idle dedicated server sits at `timescale = 0` and does not simulate.** A
  player must be connected, or no system updates at all.
- The server log stops growing after world start, so read it *after* the
  session, not during.

See [multiplayer and server](multiplayer-and-server.md) — for version and protocol issues, and for [getting one running](multiplayer-and-server.md#getting-one-running).

## Harmony binding mechanics

### Look for a public event before you patch

Not every hook has to be a patch. Some extension points are plain public
multicast delegate **fields** — not `event`s — which any assembly can assign to
or combine onto. `Mods.OnModManagementEvent` is one: it is declared
`public static ModManagementEventDelegate` in `modio.UI` (`ModIOBrowser.Mods`), and the
game's own `RadicalMainMenuOption_OpenMods.Awake` combines its handler onto it
via `Delegate.Combine` at `Pug.Other:338594`. A field rather than an event
matters, because an `event` would only let you `+=` from inside its declaring
type.

**Untested: whether a mod's reference to it survives the sandbox.** The field
lives in `modio.UI`, and no load here has referenced that assembly from mod code
in either direction. Weigh that before reaching for it as the cheap alternative
— a rejected reference is not a compile warning but a `CompileFailed`, which [can take unrelated mods down with it](troubleshooting.md).
If you try it, verify the load before building anything on top.

Whether CK has further hooks of this kind has not been surveyed — but checking
the decompile for a public delegate field on the type you were about to patch is
cheap.

### `in`/`ref` parameters need `argumentVariations`

A patch whose target has an `in` parameter — by-ref, shown as `A&` in the
decompile — fails at load with `ArgumentException: Undefined target method for
patch method …`. The mod itself loads and sandbox-compiles fine
(`safetyCheck=True`); only the bind fails. That distinguishes it cleanly from
the Burst case, which binds and stays silent.

Add the variations array, `ArgumentType.Ref` for each `in`/`ref`/`out` parameter
and `ArgumentType.Normal` for each by-value one:

```csharp
[HarmonyPatch(
    typeof(PlaceObjectSlot),
    "PlaceItem",
    new[] { typeof(EquipmentUpdateAspect), typeof(EquipmentUpdateSharedData), typeof(LookupEquipmentUpdateData) },
    new[] { ArgumentType.Ref, ArgumentType.Normal, ArgumentType.Normal }
)]
```

`ArgumentType` lives in `HarmonyLib`. The usual alternative — a `TargetMethod()`
resolving the signature via `AccessTools.Method(t, "M", new[] {
typeof(A).MakeByRefType(), … })` — is **not available to a sandboxed mod**:
`HarmonyLib.AccessTools` is rejected outright ("Indirect illegal reference via
type exclusion"), as is `System.Reflection` member access. The
`[HarmonyPatch(typeof(X), nameof(X.Y))]` attribute form is fine, because that
reflection runs inside trusted `0Harmony.dll`. Details in [sandbox rules](sandbox.md).

### Not everything needs `BurstDisabler`

Managed methods bind without it — bake-time hooks such as
`PugDatabasePostConverter.PostConvert`, or `SaveManager`'s own methods, are
reached by a plain `[HarmonyPatch]`.

**`PlaceObjectSlot.PlaceItem` is not one of them, and the distinction matters.**
It *binds* without `BurstDisabler` — its declaring type is in the global
namespace while the aspect and lookup types live in namespace `PlayerEquipment`,
which is only a naming trap for the attribute. But its sole caller is
`PlaceObjectSlot.UpdateEquipment`, called only from
`EquipmentUpdateSystem.UpdateJob` — a `[BurstCompile]` job inside a
`[BurstCompile] struct EquipmentUpdateSystem : ISystem`. So in a vanilla game
the prefix binds and never fires: you need
`DisableBurstForSystemAndJobs<EquipmentUpdateSystem>()`. A patch that binds
without firing is the failure this chapter opens with.

**Trap when picking the overload:** `PlaceObjectSlot` (decompile lines
311283–311632) declares exactly *one* `PlaceItem`, the three-argument
`(in EquipmentUpdateAspect, EquipmentUpdateSharedData, LookupEquipmentUpdateData)`
at `:311319`. Identical-looking overloads at `:310177` and `:311118` belong to
**other classes** — patching by shape rather than by owning type binds the wrong
method.

**The audit question is what you patch, not what Burst touches.** `[BurstCompile]`
on the systems that *write* the components you read is irrelevant. `BurstDisabler`
is needed only when the **patch target itself** is executed by Burst. Read-only
access needs it not at all: an `EntityQuery.ToEntityArray` plus `GetComponentData`
out of a managed coroutine or `Update` requires nothing, even though Burst jobs —
`DropSelfJob` (`Pug.Other:88826`), for instance — match the very same components.
`BurstDisabler` is not a precondition for touching ECS from a mod, and a
needless `DisableBurstForSystemAndJobs` is not free.

### A postfix on an input-driven method fires per input tick

`PlaceItem`'s postfix runs after *every* call, including every early return — no
valid placement spot, cooldown, and so on. While the player merely holds a
placeable item, that is roughly one call per input tick.

The reason is that the method protects itself **internally**: the guards are
early returns inside the body, not conditions at the call site. A prefix runs
ahead of all five of them.

| Guard | Location |
|---|---|
| `if (!valueRW.canPlaceObject) return;` | `Pug.Other:311322` |
| `CanPlaceItem` → `tilePlacementTimer` (0.65 s in this build) | call `:311332`, declaration `:311533`, timer logic `:311538-311555` |
| `timeSincePlaced.isRunning && … < 1f && pos == positionLastPlacedAt` | `:311337` |
| `PlayerController.CanConsumeEntityInSlot` | `:311349` |
| Creative / `ObjectType.PlaceablePrefab` check | `:311353` |

The **first unconditional commit point past all five** is
`playerStateCD.ValueRW.PushState(PlayerStateEnum.PlaceObject)` (`:311368`),
immediately followed by `StartCooldownForItem` (`:311370`).

`EntityUtility.AddTile` (`:311379`) comes later and is **not universal**: it
sits inside `if (…tileLookup.HasComponent(equipmentPrefab))`, so it is reached
only for *tile* placements. Its `else` branch handles everything else — a chest,
a cattle box, a critter. Gating a mod on "AddTile was reached" silently misses
every non-tile placeable.

Any side effect gated only on item identity over-fires massively. Gate instead
on a signal that the placement actually **committed**: the `PlaceObject`
player-state push for any placeable, `AddTile` when you specifically mean tiles,
or the consume branch being taken. The postfix firing is not that signal.

This generalises to every equipment/input path in CK: assume the method is
polled, and find the commit point.

### Patch the convergence point to survive other mods

A prefix returning `false` in someone else's mod erases your patch target
wholesale. PlacementPlus (mod.io `3400322`) prefixes
`PlaceObjectSlot.UpdateEquipment` and conditionally returns `false`, so vanilla's method and
everything it calls — `PlaceItem` included — may be skipped for its users. It then
drives its own placement logic, calls `EntityUtility.AddTile` itself to queue
tiles, and consumes the item through a separate, batched call — not at the
point that looks like the consume.

**"Works on its own" is not a definition of "works".** Design against the mod
population your mod actually runs beside, and *measure* the interaction rather
than reasoning about it: with PlacementPlus active, a prefix on
`PlaceObjectSlot.PlaceItem` fired **zero** times while laying rails. To test a
suspected conflict, toggle the foreign mod through the loader's `disabledMods`
list in `state.json` ([the loader's two disable lists](troubleshooting.md#the-loaders-two-disable-lists-are-opposites)) and count your own patch's
invocations in both states.

**A log line's count is not an event count.** A client connected to a
dedicated server can log the same postfix more than once for a single release
— NetCode re-prediction re-runs client-side logic, and how many times follows
connection latency, not how many items actually arrived; a server, with no
re-prediction, logs once per item. The zero-versus-non-zero comparison above
still holds — an absence is an absence on either side — but do not read an
absolute count past that as if it counted events.

And do not design around a change in the other mod. Whatever you ship has to
work against the version players actually have installed, so a fix that depends
on someone else's release is not a fix you can ship.

Four strategies exist for a patch target another mod replaces, and three of them
lose:

| Strategy | Why it loses |
|---|---|
| Conflict detection — disable yourself when the other mod is present | Prevents the failure reliably, but removes the feature from exactly the users who have the conflict |
| A standalone ECS system that anticipates the action | Duplicates the decision: two systems now judge the same tile independently — it does not resolve the conflict so much as double it |
| Rely on the foreign mod's own exclude config | Hangs on a user configuration your mod cannot guarantee |
| **Patch the convergence point** | The one that survives |

The robust target is the point where all routes converge. Queuing a tile means
writing into the `TileUpdateBuffer`, and `EntityUtility.AddTile` is the
convergence point of **equipment-driven** placement; the foreign mod calls it
too. World generation, plant growth and the `SpawnTileOnDeathCD` handler write
the buffer directly, without passing through it at all. Patching there lets you
change *where* and *what* is placed without reimplementing the act of placing,
and per-tile decisions cover grid/multi-tile placement for free — but not
*whether* one happens: see [Never suppress an `AddTile` call to veto a placement](world-and-mechanics.md#never-suppress-an-addtile-call-to-veto-a-placement)
for why blocking the call costs the player their item for nothing.

`AddTile`'s parameters carry no player or inventory context. Get that from a
prefix on `UpdateEquipment` marked `[HarmonyPriority(Priority.First)]` — it runs
ahead of the foreign prefix, and the matching **postfix still runs even when a
prefix returned `false`** — then do the actual work in the `AddTile` prefix. One
code path then serves both the vanilla and the modded world.

Recorded as an observation, not a rule: **while a foreign prefix sat on the
method, our own prefix on it fired without `BurstDisabler`** — and went quiet
again when the foreign mod was removed, unless the `AndJobs` variant was used. A
patch that only works while another mod is installed is a real and confusing
outcome. The mechanism was not established: Burst selection is per *system*,
through the enable bits that `DisableBurstForSystemPatch` flips, not per patched
method, so a general "a patched method cannot be Burst-replaced" does not follow
from this one case.

The placement *rules* themselves — which tile accepts which object — are in [world and mechanics](world-and-mechanics.md).

### A half-working mod can be worse than none

A very common CK mod shape is two independent halves: a **bake-time**
entitlement (the database says this object may now go there — bake time being
the only mutable window, see [database and baking](database-and-baking.md)) and a **runtime** behaviour
that makes the placement sensible. Design for the state in which only one half
runs.

A rail-bridge mod is the worked example. Its bake half made rails placeable on
pits; its runtime half never fired under PlacementPlus. Rails were therefore laid
across chasms, found no substrate, and dropped to the floor as pickups — strictly
worse than not installing the mod at all. Wherever the halves can come apart — a
foreign prefix erasing the runtime hook, or the dedicated-server trap above
killing it silently — work out what the surviving half does on its own, and pick
the strategy that keeps the two together.

## Correlating private state across two methods

Sometimes the data you need is neither in the arguments of any hookable method
nor reachable directly, because the API that exposes it is sandbox-blocked and
the value itself lives in a private field written by one method and consumed by
another.

The pattern: **hook both methods and correlate them with a static flag.**

```csharp
[HarmonyPatch(typeof(SaveManager), nameof(SaveManager.SetCharacterId))]
internal static class SaveManagerActiveSelectHook
{
    public static string ActiveGuid { get; internal set; }
    internal static bool AwaitingActiveDeserialize;

    [HarmonyPostfix]
    static void After(int id)
    {
        if (id < 0) { ActiveGuid = null; AwaitingActiveDeserialize = false; return; }
        AwaitingActiveDeserialize = true;
    }
}

[HarmonyPatch(typeof(CharacterData), nameof(CharacterData.OnAfterDeserialize))]
internal static class CharacterDataDiscoverySnapshot
{
    [HarmonyPostfix]
    static void After(CharacterData __instance)
    {
        string guid = __instance.characterGuid;   // public string field, safe

        if (SaveManagerActiveSelectHook.AwaitingActiveDeserialize)
        {
            SaveManagerActiveSelectHook.ActiveGuid = guid;
            SaveManagerActiveSelectHook.AwaitingActiveDeserialize = false;
        }
    }
}
```

That example obtains the active character's GUID, for which every direct route is
closed: `PlayerController.characterGuid` does not exist, `Manager.saves.GetCharacterGuid()`
is out — `SaveManager` is on no deny list, but calls through `Manager.saves` have been
*observed* to fail verification anyway (see [what is banned](sandbox.md#what-is-banned)) —
`HarmonyLib.Traverse` is banned as a reflection wrapper, and
`EntityManager.HasComponent<CharacterGuidCD>` plus `GetComponentData` trips the
sandbox on namespace, type and member.

Nothing in the hook bodies violates the sandbox: only value-type parameters
(`int id`), a public `string` field on a class that appears on no deny list,
and the mod's own statics. The `[HarmonyPatch(typeof(SaveManager), …)]`
attribute is legal regardless — the reflection behind it runs in trusted
`0Harmony.dll`.

**Preconditions — verify all three in the decompile before committing to this:**

- The producer and the consumer are called in deterministic order.
- They run on the same thread with no re-entry in between (the mod/main thread
  qualifies).
- The consumer *always* follows the producer. If it is conditional, the flag
  leaks and pollutes the next legitimate producer call.

If any of these is uncertain, the flag will race or leak, and the bug will be
intermittent.

## Scaling a value that flows from a Burst producer into a Burst consumer

A very common shape: a managed-looking producer method computes an amount, an
ECS component carries it, and a Burst system applies it. **Do not patch the
producer** — its callers are themselves Burst-compiled sim code and bypass your
IL patch entirely.

Instead:

1. `BurstDisabler.DisableBurstForSystem<TConsumerSystem>()` in `IMod.Init()`
   (plus the `AddWorld` pass from above).
2. Harmony `Prefix` on the consumer's `OnUpdate(ref SystemState state)`. Via
   `state.GetEntityQuery(ComponentType.ReadWrite<T>())` and
   `state.EntityManager` (`GetComponentData` / `SetComponentData` /
   `GetBuffer`), **rewrite the pending value before returning `true`** so the
   original system applies your inflated number.

This is robust regardless of whether the consumer's inner *job* stays Burst: you
are mutating the shared component memory that job then reads. It also leaves the
system's own guards (max level, caps) intact, so the change becomes a natural
no-op at the cap. Querying and `SetComponentData`/`GetBuffer` from inside the
prefix are sandbox-safe.

### Worked example — XP grants

CK's XP grants have exactly two choke points, and both fit this shape.

| Track | Producer | Component | Burst consumer |
|---|---|---|---|
| Player skill XP | `PlayerController.AddSkill(Entity, SkillID, int amount, EntityCommandBuffer, bool isServer)` — the sole creator of the component, only `if (isServer)` | `AddSkillValueCD : IComponentData` | `AddSkillValueSystem` (`SkillBuffer.Value += amount`, guarded `levelFromSkill < maxSkillLevel`) |
| Pet XP | `PetExtensions.GetExperienceFromDamage(dmg) = clamp(dmg / 20, 1, 250)` — pets level only from dealt damage | `AddPetExperienceBuffer : IBufferElementData` | `PetHandlerSystem` (`pet.objectData.amount += amount`, guarded `!IsAtMaxLevel`) |

Every skill funnels through `AddSkill` — Mining, Melee and Range via the combat
`skillMultiplier`, Fishing, Crafting, Cooking, Gardening, Running, Vitality,
Summoning, Explosives. Its callers include `PlayerAttackAspect` and the inventory
handlers, all Burst-compiled, which is precisely why patching `AddSkill` itself
does not work.

Both component types are declared in `Pug.ECS.Components` but sit in the
**global namespace**; the systems live in `Pug.Other`. Neither needs a `using`
in mod code.

Scale with rounding that cannot silently zero a grant:

```csharp
int boosted = (int)(amount * mult + 0.5f);
if (boosted < 1) boosted = 1;
```

Because the grant is server-authoritative (`AddSkill` runs only `if (isServer)`),
the effect applies in single-player and as host, and the mod needs the server
side in its `requiredOn` — see [mod anatomy](mod-anatomy.md).

## Instrumenting generated DOTS code

**The `OnUpdate` body you are reading in a mod's `.cs` file is not the one that
executes.** For any system using `Entities.ForEach` or `SystemAPI.*`, the DOTS
source generator has moved the body into
`Scripts/Generated/<System>__System_<id>.g.cs` as `__OnUpdate_<hash>()`, marked
`[DOTSCompilerPatchedMethod("OnUpdate_T0")]`, and the mod loader splices that
body back into the original method **in the source, before compiling it** — so
the generated code goes through the same Roslyn pass and the same sandbox check
as everything else you ship. Player.log states it per mod:

```text
Replacing method <Ns>.<System>/OnUpdate_T0 with __OnUpdate_<hash>
```

Diagnostic code added to the source file therefore never runs. It has to go into
the `.g.cs`.

That file is also the better place to measure from: it is a `partial class` and
contains the system's **real** queries (`__query_<id>_0`, … with every filter and
`EntityQueryOptions` applied), so a measurement taken through them observes
exactly what the system observes instead of a hand-built replica. Fields and
helper methods can be added freely.

**Two hard limits:**

- **Do not touch the `Entities.ForEach` body or the Burst job.** Any change
  there would need a fresh source-generator run, which is not available without
  Unity — and `Debug.Log` is forbidden inside a Burst job anyway. Diagnostics go
  *beside* the job, never inside it.
- **Do not introduce new `SystemAPI.*` usage**; that also requires generation.
  `EntityManager.CreateEntityQuery(new EntityQueryDesc { … })` plus
  `ToComponentDataArray<T>(Allocator.TempJob)` plus `UnityEngine.Debug.Log` are
  generator-free and sandbox-legal.

**Procedure.** Edit the `.g.cs` inside the mod.io cache
(`…/Public/mod.io/5289/mods/<modId>_<modfileId>/Scripts/Generated/`), delete the
loader's extraction at `…/Temp/Pugstorm/Core Keeper/ModLoader/<ModName>/`, then
restart the game. Leave the ZIP under `…/Temp/Pugstorm/Core Keeper/5289/` alone —
mod.io tracks integrity and downloads through it.

**Syntax-check without Unity.** Copy the file into a scratch directory *without
`.g` in the name* and run `dotnet csharpier check` on it. CSharpier silently
skips `*.g.cs` ("Checked 0 files") but otherwise parses through Roslyn and
reports genuine syntax errors. The care is warranted: a `CompileFailed` can
cascade and desynchronise *other* mods, not only yours — see [troubleshooting](troubleshooting.md).

**Two traps when instrumenting a third-party mod:**

- **Do not open the in-game Mods menu.** The mod.io sync re-extracts the mod and
  your edit is gone.
- Every mod update replaces the cache folder outright. Keep a backup of the
  original file **outside** the `Scripts/` tree — a `.bak` left inside it would
  be compiled along with everything else.

## Reading the live ECS world from a mod

Live-world access needs no Harmony routing at all: plain mod `Scripts/*.cs` may
query the ECS world directly, and the surface below loads sandbox-clean
(`safetyCheck=True`) for the component types it has been verified against — with
the per-component caveat spelled out below.

**Pick the world by measurement, not by name.** Inventories live in the
**ServerWorld**, not the ClientWorld — including in single-player, where the
client is a local host. Iterate `World.All`, run
`CreateEntityQuery(...).CalculateEntityCount()` for a probe component, and take
the world with the most entities. Hardcoding a world name breaks the moment the
topology changes.

**Trap: the world you measure may not be populated yet.** The measurement is only
safe as a one-shot if the ECS entities are certain to be deserialised by then. An
early callback — `OnOccupied`, for example — can fire before that, and the probe
then pins an empty or simply wrong world for the rest of the session. A scanner
that caches its world therefore needs a re-probe path: after a run of consecutive
empty scans, measure again and re-pin. How many empty scans is per-mod tuning,
not a constant.

From there, `em.CreateEntityQuery(ComponentType.ReadOnly<…>())` →
`ToEntityArray(Allocator.TempJob)` → `GetComponentData<T>`, `HasComponent<T>`,
`GetBuffer<…>` all work.

**Trap: the sandbox verdict is per component type, not per method.** The block
is not on `GetComponentData` / `HasComponent` as such: `GetComponentData` over
`ObjectDataCD` and `LocalTransform`, and `HasBuffer` / `GetBuffer` over
`ContainedObjectsBuffer`, all load clean — which is what the scanning idiom
above rests on. But `HasComponent<CharacterGuidCD>` plus
`GetComponentData<CharacterGuidCD>` (with `Hash128`) fails verification, at one
illegal namespace, one type and one member reference, which is why the GUID
example [further up](#correlating-private-state-across-two-methods) goes through Harmony instead. Whether the ban sits on those
specific game-side types or on some narrower slice of the generic surface has
never been mapped. Treat the safe set as enumerated rather than general: if a
query trips the sandbox, bisect it by component rather than abandoning the
approach.

### Identifying an entity as a particular object

**Trap: there is no per-object-type component.** Hunting the decompile for a
`<Thing>CD` that marks one kind of object is the wrong search and will fail after
a long detour. `EntityMonoBehaviourDataConverter.Convert` (`Pug.ECS.Conversion:5808`) fills
`ObjectTypeCD` and `ObjectDataCD` on *every* object entity, and those two carry
the identity:

```csharp
// Pug.ECS.Components:3890-3893
public struct ObjectTypeCD : IComponentData, IQueryTypeParameter { public ObjectType Value; }
```

A name like `DiggingSpot` exists as a `LootTableID` value, as an `ObjectID`
value and as a MonoBehaviour — but not as an `ObjectType` and not as a
component. Recognise an entity by `ObjectDataCD.objectID` and
`ObjectTypeCD.Value`.

**A DOTS query selects archetypes, not values.** `EntityQueryBuilder` /
`CreateEntityQuery` cannot express "where `ObjectTypeCD.Value == X`". The
component goes into the query to pick the chunks; the `objectID` / `Value`
comparison belongs in the loop body, per entity. That is a general DOTS property,
but it bites harder in CK than elsewhere, because practically every world entity
carries the same component set — so the query is almost never the filter.

**Use an empty tag component as a chunk prefilter, never as an identity test.**
`DiggableCD` is a null-byte tag:

```csharp
// Pug.ECS.Components:4503-4507
[StructLayout(LayoutKind.Sequential, Size = 1)]
[GhostComponent(PrefabType = GhostPrefabType.All)]
public struct DiggableCD : IComponentData, IQueryTypeParameter { }
```

It sits on everything a shovel can turn over — floor tiles, plants, dig spots —
which makes it worthless as an identity test and valuable in the query, where it
excludes non-matching archetypes cheaply. The game disambiguates the same way,
with `objectID ==` checks (`Pug.Other:296438`, `:296842`, `:310904`). The pattern
generalises — tag narrows, `objectID` decides — while `DiggableCD`'s particular
breadth is just one data point.

### The performance rule

**For a recurring scan over many entities, never call `GetComponentData<T>(e)`
per entity.** Each call is a random chunk-plus-index lookup; done synchronously
on the main thread across a large query, it spikes the frame.

Bulk-copy instead: `q.ToComponentDataArray<T>(Allocator.TempJob)` is a
chunk-sequential memcpy, and the resulting arrays are **index-aligned** with the
entity array as long as they are captured back to back with no structural change
in between. Keep per-entity access (`HasComponent`, `GetBuffer`) for the gated
minority that actually needs it.

| Rule | Value |
|---|---|
| Frame budget for a synchronous main-thread scan | < 16.7 ms (60 fps) — above it, a frame drops and the stutter is visible |
| Measured effect of the bulk swap on a ~1300-entity scan | max 21.5 ms → 9.6 ms |

Diagnose before optimising: a throwaway probe splitting phases with
`Time.realtimeSinceStartup` (plus entity and anchor counts) identifies the
dominant phase. In the measured case, spatial hashing, caching the world
resolution and reusing allocation buffers were all unnecessary — only the
per-entity component reads mattered.

### Hooking the save

To persist mod state in lockstep with CK's own save, Harmony-postfix
**`SaveManager.WriteCharacter(int saveId)`**. It is patchable despite the
`Manager.saves` verification failure observed above, for the same reason: the
patch attribute never goes through `Manager.saves` at all.

What the hook fires on, its symmetric load point, the trap that loses a save
silently, and the cost of writing on that thread are all in [writing in lockstep with the game's save](persistence.md#writing-in-lockstep-with-the-games-save).
