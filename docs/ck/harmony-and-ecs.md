# Patching Harmony and ECS

Core Keeper is a DOTS game whose simulation systems are Burst-compiled, and mods
are Harmony patches compiled at load time inside a sandbox. That combination
produces failure modes that look nothing like a normal Harmony problem: a patch
that loads cleanly and never fires, a system whose body is not in the file you
are reading, and — through 1.2 — a fix that works whenever a player hosts and is
inert on a dedicated server. This chapter covers how to make a patch bind, how
to make it fire, and how to read and write the live ECS world once it does.

Runtime observations below that name no build were made on 1.2.1.x, before the
1.3 update; the ones re-taken on 1.3 say so.

Line numbers quoted below (`Pug.Other:306184`) are offsets into the decompiled
game assemblies — see [reverse-engineering](reverse-engineering.md) for how to produce that decompile.
**Every citation names its assembly, and five assemblies differ between the two
builds** — `Pug.Other`, `WorldGen`, `Pug.Objects`, `Pug.Dev` and
`PugMod.Loader`; the rest are shared. Within those five the same code sits at
different offsets in each — the call to `BurstDisabler.AddWorld` is
`Pug.Other:2799` on the client and `DedicatedServer/Pug.Other:2777` on the
server — so the prefix is what decides which checkout resolves it, and reading
one in the wrong tree lands on unrelated code.

This used to be a convention about what an *unmarked* citation meant, because
most references were written without an assembly and inherited it from the
sentence before. That form was readable and unverifiable: no checker could
follow it, so a game update silently invalidated it. There is now a gate against
it — see [reverse-engineering](reverse-engineering.md#line-citations-carry-their-assembly).

## Three failure modes, three different causes

Before changing anything, classify the symptom. They have nothing in common
except that your code does not run.

| Symptom | Cause | Fix |
|---|---|---|
| `ArgumentException: Undefined target method for patch method …` at load | Harmony cannot resolve the target — typically an `in`/`ref` parameter, or a method the type no longer declares itself (only inherits) | `argumentVariations` (below); for an inherited target, patch the method the type does declare ([mod anatomy](mod-anatomy.md#harmony-patches-are-auto-discovered)) |
| Mod loads, `safetyCheck=True`, patch binds, prefix never fires | The target is Burst-compiled; the managed IL you patched is never executed | `BurstDisabler` (below) |
| Works when a player hosts, dead on a dedicated server | through 1.2: an `ISystem` registered with `BurstDisabler` after the server took its snapshot — measured ordering, gone on a fresh 1.3.0.5 server start, and it does not arise for a managed `SystemBase` | manual `AddWorld` pass (below) |
| Mod does not compile at all (`CompileFailed`) | Not a patching problem — an ordinary compile error, or a sandbox rejection | [sandbox rules](sandbox.md) tells the two apart |

## Why a Burst-compiled `OnUpdate` cannot be intercepted

Harmony rewrites managed IL. A Burst-compiled `OnUpdate` never runs that IL, so
there is nothing for the patch to intercept — and Harmony has no way to tell you
that, because the bind itself succeeded.

The dispatch chain is worth knowing, because the fix only makes sense against
it. `WorldUnmanagedImpl.UpdateSystem` invokes `UnmanagedUpdate` as a
`$BurstDirectCall` (`Unity.Entities:67217`), which takes the Burst path when
`BurstCompiler.IsEnabled` **and** the compiled function pointer is non-zero — a
failed `CompileFunctionPointer` falls through to the managed body.
`CallForwardingFunction` then runs *inside* Burst, where `CheckBurst` is
`[BurstDiscard]` and therefore stripped, so its `status` stays `true` and the
per-system `BurstFunctionEnabledBits` flag is never read on that path — called
from managed code instead, `status` becomes `false` and the bits decide, which
is the path [the two halves](#the-isystem-call-has-two-halves-and-only-one-of-them-is-global) turn on. The function then invoked is whatever
`SelectBurstFn` (`Unity.Entities:58169-58189`) stored — the Burst-compiled body
where one exists, and a managed forwarding thunk where the function was not
Burst-compiled. So "the Burst path" names the dispatch route, not a guarantee
that native code runs.

## `BurstDisabler` — moving a system off Burst

`BurstDisabler` ships in `PugMod.SDK.Runtime`, which the wizard-generated
runtime asmdef references — provided Update Game Files ran before Create Mod
([toolchain](toolchain.md)). Using it costs no dependency — in particular not CoreLib.

```csharp
public void Init()
{
    BurstDisabler.DisableBurstForSystem<ChangeDurabilitySystem>();
}
```

### The call does two entirely different things, depending on the system

`DisableBurstForSystemInternal` (`PugMod.SDK.Runtime:724`) first calls
`TypeManager.IsSystemType` — the check that throws a `NullReferenceException`
when `TypeManager` is not yet initialised, which is why this cannot run in
`EarlyInit` — and then branches on `TypeManager.IsSystemManaged`, **returning
early** for a managed system. Between those two checks it does work that belongs
to both paths: it creates the shared `_harmony` instance on first use and runs
`PatchAll(typeof(DisableBurstForSystemPatch))` (`PugMod.SDK.Runtime:731-735`).
What the branch selects is which system gets patched how:

| System shape | What actually happens |
|---|---|
| **`ISystem` struct** (unmanaged) | the two-halves mechanism below |
| **`SystemBase` class** (managed) | `PatchManagedSystem` Harmony-patches `OnCreate`/`OnStartRunning`/`OnUpdate`/`OnStopRunning`/`OnDestroy` with prefixes and postfixes that toggle `BurstCompiler.Options.EnableBurstCompilation` around each call — immediately, globally, with no world registry involved. It looks each one up with `GetMethod` and no `DeclaredOnly` (`PugMod.SDK.Runtime:817`), so a method the system does not override resolves to the `protected virtual` one on `ComponentSystemBase` (`Unity.Entities:10166-10186`) and **that shared base method** is patched — for every `SystemBase` that inherits it, not only yours. The `Could not find method` warning cannot fire for these five on a `SystemBase`; this is read off the reflection rules, not measured |

**The two halves below, the per-world snapshot, and the dedicated-server trap
built on it apply to the `ISystem` path only.** A managed `SystemBase` never
reaches `SystemTypesToDisableBurstFor`, so `AddWorld` has nothing to arm for it
and the server trap does not arise.

**The `AndJobs` variant is the exception — it is not `ISystem`-only.** Both
branches end in `CreateCompleteDependencyPatch` (`PugMod.SDK.Runtime:850`),
called from `PatchSystem` (`PugMod.SDK.Runtime:793`, `isManaged: false`) and
from `PatchManagedSystem` (`PugMod.SDK.Runtime:811`, `isManaged: true`). A
managed system therefore gets a dependency-completing postfix from the same flag
— `CompleteDependencyAfterUpdateManagedPatch` rather than the unmanaged one,
same effect (`PugMod.SDK.Runtime:876`); only the route to it differs.

Which shape you are looking at is worth checking before reasoning about any of
it: in the decompile it is `public struct X : ISystem` versus a class deriving
from `SystemBase` — directly, or through a game base such as
`PugSimulationSystemBase`, where `: SystemBase` does not appear on the line at
all. Every system this handbook cites as a worked example —
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
`ManagedFunctionsUnBursted`, the `OnUpdate` you can patch. It also saves the
previous setting into `out bool? __state` (`PugMod.SDK.Runtime:889-897`), which
is what the postfix restores — and leaves `__state` null on the unarmed path, so
that postfix restores nothing when the prefix did nothing. If half 2 never armed
for the world your system runs in, half 1 is dead weight **for the calls that go
through `UpdateSystem`** — `OnUpdate` and `OnStartRunning`. Lifecycle calls the
engine makes from managed code are a different path: there `CheckBurst` runs for
real, the enable bits are read, and half 1 alone selects
`ManagedFunctionsUnBursted` — `OnCreate` for a system created after the
registration (`Unity.Entities:67551`), `OnStopRunning` when a parent group stops
(`Unity.Entities:11024`), `OnDestroy` at teardown.

The same patch's `Postfix` restores `EnableBurstCompilation` to whatever it was
before the `Prefix` ran. So the bypass is a **window around that one system's
`UpdateSystem` call, not a lasting state change** — it closes the moment
`OnUpdate` returns, and the next system to update runs Burst-compiled again
unless it is armed too. `OnStartRunning` goes through the same forwarding table
inside that window, so it is patchable while a system is armed, and only then.
`OnStopRunning` is reached inside the window too, but also from the managed
paths above, where half 1 alone un-Bursts it.

### Nested jobs need the `AndJobs` variant

`DisableBurstForSystem<T>` is not enough when the system's real work lives in a
nested job. `EquipmentUpdateSystem` (`Pug.Other:438824`) does everything in
`UpdateJob`, which carries its own `[BurstCompile]` (`Pug.Other:438826`) and calls
`PlaceObjectSlot.UpdateEquipment` (`Pug.Other:438958`). Note the blast radius before
reaching for it: that call sits in a `switch` on `slotType` (`Pug.Other:438952`) covering
`ShovelSlot`, `EatableSlot`, `WaterCanSlot` and the rest, so un-Bursting this
one system takes the equipment path off Burst for **every** slot type, not only
the one you meant to patch. With the plain variant, **no** patch on that path
fires; with `BurstDisabler.DisableBurstForSystemAndJobs<T>()`
(`PugMod.SDK.Runtime:709`) they do — provided the world is armed, which the call
alone does not guarantee. On a 1.2 dedicated server it was not, and the same
patches stayed silent with the `AndJobs` variant in place; that trap is two
sections below, and its log line is the false shortcut described just after
this one.

**The criterion is what you patch, not which system it belongs to.**
`DisableBurstForSystem<T>` calls `DisableBurstForSystemInternal(type,
burstEnabled, addCompleteDependencyPatch: false)` (`PugMod.SDK.Runtime:706`);
`DisableBurstForSystemAndJobs<T>` passes `true` (`PugMod.SDK.Runtime:711`). For
an unmanaged `ISystem`, `PatchSystem` (`PugMod.SDK.Runtime:788-796`) installs
nothing with that flag off — it stores an empty method list for the type and
stops. With the flag on, it adds exactly one more thing: a postfix on
`OnUpdate(ref SystemState)` that calls `state.Dependency.Complete()`. There,
that one postfix is the entire difference between the two calls — a managed
system is patched either way, and the flag only adds the equivalent managed
postfix on top.

**Do not call both variants for the same system.** `PatchSystem` ends
`_patchedMethods[systemType] = list` (`PugMod.SDK.Runtime:795`), which
**overwrites** the existing entry, so an `AndJobs` call followed by a plain one
for the same type discards the record of the `Complete()` postfix while leaving
the postfix itself installed — patched behaviour the SDK no longer knows it
applied.

It is also why `EquipmentUpdateSystem` needs it. Its `OnUpdate`
(`Pug.Other:439628`) ends `state.Dependency =
__ScheduleViaJobChunkExtension_0(new UpdateJob { … })`, and that extension
returns a `.Schedule(...)` call — not `.Run(...)`. The job is *queued*, not
executed, before `OnUpdate` returns. What is measured is the outcome: with the
plain variant no patch inside `UpdateJob` fires, with `AndJobs` they do. The
explanation that fits it — `UpdateJob` runs after the bypass window above has
closed and Burst is back on, and `Complete()` pulls that execution back inside
the window — is inferred: when the job system picks the Burst or the managed
entry point of a scheduled job is native, and in neither tree.

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

Taking a system off Burst costs more than its `OnUpdate` running managed. The
bypass clears the **global** `BurstCompiler.Options.EnableBurstCompilation` for
the duration of that `UpdateSystem` call (`PugMod.SDK.Runtime:889-897`), so
everything *executed* inside the window runs un-Bursted — a job merely
scheduled there is the exception above —
`OnStartRunning`/`OnStopRunning` through the same forwarding table included. How
large that cost is for a given system is **unverified** — one anecdote exists,
below, and nothing else settles it either way.

What exists is a single anecdote, recorded here because the question comes up
immediately and because knowing the evidence is thin is better than guessing:
`auto-rail-bridges` Burst-disables `EquipmentUpdateSystem` and its author
noticed no frame drop while laying rails with bridges auto-placed beneath them
(observed 2026-08-11, never profiled). PlacementPlus — a foreign mod — un-Bursts
the same system with the same call, and running both at once was equally
unremarkable.

**Read that for exactly what it is.** One person, one system, one activity,
judged by eye with no profiler. It does not establish that Burst-disabling is
cheap in general — and the recorded note names two properties of *this* system
that keep it cheap, both of which have to be re-checked before assuming the same
anywhere else: the query iterates player entities only (`EquipmentUpdateAspect`
requires `ClientInput`, `PlayerStateCD`, `PlayerGhost` — `Pug.Other:438188`),
and the job is scheduled with `Schedule()`, not `ScheduleParallel()`
(`Pug.Other:439736`), so it was single-threaded anyway: `Complete()` makes the
main thread wait for it, and what that loses is the overlap with other
main-thread work — how much, nobody measured.

It also came with an attribution problem worth repeating: the one place that
did feel slower was a large base, which is also where an unrelated
inventory-scanning mod does its heaviest work. A cost that shows up only where
two mods overlap belongs to neither until it has been isolated.

**If the cost matters to your mod, measure it.** The variables that plausibly
dominate are how often the system ticks and how much work it does per tick, so
compare the same scene with your `DisableBurstForSystem*` call present and
removed, and look at frame time rather than at whether it "feels" the same.
**Removing the call is only a control if no other installed mod registers the
same system** — the registry is a process-wide `HashSet<Type>`
(`PugMod.SDK.Runtime:657`), so a sibling keeps your system un-Bursted with your
own call gone, and the two runs then differ in nothing. In this family
`auto-rail-bridges` and `reusable-cattle-box` both register
`EquipmentUpdateSystem`. Disable the others for the comparison, or
measure a system nothing else touches. That is a small experiment, and it beats
both this anecdote and any assumption you would otherwise make.

## The dedicated-server trap

**Through 1.2, `DisableBurstForSystem<T>()` in `IMod.Init()` had no effect on a
dedicated server.** The call itself did everything it always does — it
registered the type, cleared the enable bits, installed the SDK's patch — and
none of it armed the world's `OnUpdate` bypass, so the prefix simply never
fired. No error, no log line. The mod worked whenever a player hosted and did
nothing on a dedicated server.

**On 1.3.0.5 a freshly started dedicated server no longer shows it.** Measured
2026-10-08 from a local dedicated server's own log (`1.3.0.5-cb48`):
`IMod.Init()` logged before `ECSManager: converting authoring data`, and the
conversion's completion callback — the one that arms the worlds — came after
both, so the registration now precedes the snapshot there as it does on a
client. The decompile names the change: the call at
`DedicatedServer/Pug.Other:2785`, described below. What follows keeps the 1.2
account, because it is what a mod tagged for 1.2 still runs into, and because
the ordering it rests on is a log measurement the SDK never promised.

**"Does nothing in multiplayer" is the wrong scope, and this file said it until
2026-08-24.** A hosting client is not affected: `StartEcs` creates the
ServerWorld in that same process (`Pug.Other:2784`, guarded at `Pug.Other:2782`
by `worldId != -1 && requestedPlayType != PlayType.Client` — **both**
conditions, which is why the menu path below creates none despite not being a
pure client), adds it to `_allWorlds`, and arms both worlds at
`Pug.Other:2797-2799` — all of it after `Init()` on the client ordering. So
host-based multiplayer works, and on the builds observed through 1.2 the defect
appeared on the dedicated server alone. What it belongs to is the *ordering*,
not the binary: a mod that registers after its own `StartEcs` has run the
conversion callback — calling `DisableBurstForSystem*` from `Update` instead of
`Init` (not from `ModObjectLoaded`, which the loader calls right after
`EarlyInit` and before `Init`, `PugMod.Loader:1752`) — reaches the identical
dead patch on a hosting client. The distinction matters when reading a bug
report: "works for me in multiplayer" from a host neither reproduces nor refutes
it.

The cause is the lifecycle order — which is **measured**, not derived; the
paragraphs below say why no derivation replaces it, and one that was tried was
wrong. `BurstDisabler.AddWorld` is called from exactly one place,
`ECSManager.StartEcs` (`Pug.Other:2799` in the client build,
`DedicatedServer/Pug.Other:2777` in the server build), and it **snapshots** the
types registered up to that moment. Nothing back-fills that snapshot for a world
already passed to `AddWorld` — but neither set is permanent, and a later world
load rebuilds them correctly; see the bound on this below. Since 1.3 the same
callback calls `BurstDisabler.ResetWorlds()` immediately before its `AddWorld`
loop (`Pug.Other:2796`, server `DedicatedServer/Pug.Other:2774`; 1.2.1.5's
`StartEcs` has no such call), so every `StartEcs` first wipes the process-wide
handle set — including whatever a mod's own pass had armed — and re-arms
`_allWorlds` only. Two different resetters exist: `ResetWorlds` clears the
per-world handles, while `BurstDisabler.Init()` (`PugMod.SDK.Runtime:665-676`) —
a `[RuntimeInitializeOnLoadMethod(SubsystemRegistration)]`, so once per process
start rather than per world — additionally unpatches Harmony, clears
`_patchedMethods`, and clears the **type** registry itself.

Note what this does *not* mean: the call is present and runs on both builds, in
the callback `ECSManager.StartEcs` hands to authoring-data conversion, once the
worlds have been created and converted. The server does not skip it. So
"`AddWorld` never runs server-side" is the wrong diagnosis — through 1.2 it ran,
it was simply reached before your `Init()` had a chance to register anything.

The two builds differ three times inside that one method. The client's
`StartEcs` opens with a client-world creation block (`Pug.Other:2775-2781`) that
the server build does not have at all — so the worlds `AddWorld` is handed are
not the same set on the two sides. Both builds call `AddWorld` from the
conversion's completion callback (`Pug.Other:2797-2799`, invoked at
`Pug.Other:2859`), but the client runs that conversion as a coroutine
(`Pug.Other:2807`), so `StartEcs` returns first and the snapshot is taken frames
later, while the server drains the same enumerator synchronously and takes it
before `StartEcs` returns. Through 1.2 — per the 1.2.1.5 decompile — the client
called `AddWorld` straight after starting the coroutine, before any conversion
had run. The third difference bears on the snapshot most directly: since 1.3 the
server build calls `Integration.Instance.Update()` — the loader's `Update`, the
path from which `IMod.Init()` is called — inside `StartEcs` itself
(`DedicatedServer/Pug.Other:2785`), after the ServerWorld exists and immediately
before the drain whose callback runs `AddWorld`. 1.2.1.5's server `StartEcs` has
no such call, and the client build has none in 1.3 either.

| Process | Order (measured in the logs) | Result |
|---|---|---|
| Client (1.2.1.5, 1.3.0.2) | `Init()` first, worlds built afterwards | registration precedes the snapshot → works |
| Dedicated server (1.2) | worlds built first (`adding worlds to the update loop`), `Init()` afterwards | snapshot empty → patch dead |
| Dedicated server (1.3.0.5, fresh start) | ServerWorld created, `Init()`, then conversion and `adding worlds to the update loop` | registration precedes the snapshot → works |

The 1.3.0.5 row is one server start, read 2026-10-08 with thirty-six mods
loaded — an ordering of the process rather than an effect a mod could colour.
That it comes from the call at `DedicatedServer/Pug.Other:2785` is what the
decompile and the log agree on: `Init()` already sees the ServerWorld (the
counter [below](#the-pass-was-load-bearing-through-12--measured-not-assumed) reads `1/12`), and that call is the one path into
`Init()` that sits after `CreateServerWorld` and before the conversion.

**The server guard does not settle the boot route, and this file said it did.**
`UnityEngine.Debug.LogError("Server should start from ServerMain!")` followed by
`Application.Quit()` (`DedicatedServer/Pug.Other:378872-378873`) fires only when
a ServerWorld **already** exists; otherwise the same `SceneHandler.Awake` calls
`StartEcs` itself (`DedicatedServer/Pug.Other:378883`,
`DedicatedServer/Pug.Other:378888`), and those two are the only callers of
`StartEcs` in the server tree. So the guard rules out a *second* start through
`Awake`, not that route as such. `ServerMain` occurs nowhere else in either
checkout and names no type there — whether it is code that was never decompiled
or simply a scene name, nothing in the trees says. What the decompile cannot
show either way is when the loader's mods are ready relative to `StartEcs`,
which is why the ordering is measured.

**That table is a measurement, and no derivation has replaced it — one was tried
and was wrong.** The tempting mechanism is: `StartEcs` is reached from
`SceneHandler.Awake` (client `Pug.Other:383086`, calling it at
`Pug.Other:383123`; server build `DedicatedServer/Pug.Other:378844`, calling it
at `DedicatedServer/Pug.Other:378883` or `DedicatedServer/Pug.Other:378888`
depending on the configured world) while `IMod.Init()` comes from
`Loader.Update` (`PugMod.Loader:1214`, `PugMod.Loader:1216`), so Unity's rule
that every `Awake` precedes every `Update` fixes the order. **It does not.**
`Loader.Update` is reached from two places in the client build, not one, and
from three in the 1.3 server build — the third being the call inside `StartEcs`
described above. All go through `Integration.Instance.Update()` — an
`IIntegration` interface call that lands on `Loader` only because `Loader :
IIntegration` — and one of them sits in `Manager.EarlyInit` (`Pug.Other:272263`,
client build; server `DedicatedServer/Pug.Other:272197`), which is a
`[RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterAssembliesLoaded)]`
(`Pug.Other:272172` client, `DedicatedServer/Pug.Other:272115` server) and
therefore runs *before* any scene `Awake`. The other, the MonoBehaviour
`Update()` the derivation actually means, is at `Pug.Other:279330` (server
`DedicatedServer/Pug.Other:279172`). The lifecycle rule never applies to the
first path, so it cannot settle the ordering. Nor is the hosting side
"menu-triggered" as a contrast: the client's own world-creating `StartEcs`
(`Pug.Other:383123`) sits in `SceneHandler` too, and the menu path
(`RadicalJoinGameMenu.Join`, `Pug.Other:351545`) passes `worldId: -1` and
creates no ServerWorld at all.

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

`World.All` is sandbox-legal (`safetyCheck=True` on both client and server, on
1.2.1.5 and again in the 1.3.0.5 server log). The pass is harmless in the client
ordering, but not because of the `HashSet` behind `AddWorld`: at `Init()` time on
a client, `World.All` holds six leftover conversion worlds and neither world
`StartEcs` will later arm (`Pug.Other:2797-2799`), so the pass touches a
different set altogether. It is harmless because `AddWorld` inserts a handle
only for a world that actually contains the system, and an entry for a world
the system never updates in is never matched — while one for a world it does
update in un-Bursts it there too, which is the point. On 1.3 the question is
moot on both builds whenever the pass runs before the conversion callback: that
callback's `ResetWorlds` (above) wipes it and re-arms `_allWorlds` itself.

**Write it unconditionally, and note that the reason is stronger than "the extra
pass is harmless".** Nothing in the SDK pins the ordering down: `AddWorld` and
`DisableBurstForSystem*` carry no doc comment, attribute or contract of any kind
about call order, and the client/server split above is a log measurement, not an
API guarantee — one that has already changed once, between 1.2 and 1.3.
Branching on the build would therefore rest on an ordering the SDK never
promised — the unconditional pass holds whichever one runs first, and keeps a
mod that is still tagged for 1.2 working there. Prefer that argument over the
no-op one; it survives the thing the other depends on.

**The order in that snippet is mandatory, not stylistic.** `AddWorld` only
iterates `SystemTypesToDisableBurstFor` as it stands at the moment it runs —
call `DisableBurstForSystem*` for everything you want it to see *before* the
`World.All` pass, or the pass walks a set that is still empty and arms nothing.

**What the pass repaired through 1.2 is the *first* `StartEcs` of the process,
not a permanent defect.** Unloading the worlds calls `BurstDisabler.ResetWorlds`
(`PugMod.SDK.Runtime:767`) from `ECSManager.UnloadWorldsInternal`
(`Pug.Other:3069`, server `DedicatedServer/Pug.Other:3046`), which clears the
handle set; the next `StartEcs` then runs its own `AddWorld` pass with the
registration already in place, so a world reload arms correctly on its own. That
is why the bug reads as "dead from launch" rather than intermittent — and why a
dedicated server, whose world in an observed session was loaded once at startup
and kept, never got the second chance a world switch would hand it. Nothing in
either tree makes that a property of the binary: the server build carries a full
`UnloadWorldsInternal` (`DedicatedServer/Pug.Other:3022`), reachable from
`OnSceneUnload` and from `StartEcs`'s own "Trying to start new ECS instance
without unloading old" path (`DedicatedServer/Pug.Other:2752-2756`), so a second
`StartEcs` there is not forbidden — merely not something an ordinary server run
does.

**`EarlyInit` is not the fix.** Moving the registration there fails on client
*and* server: `TypeManager` is not initialised that early, so
`TypeManager.IsSystemType` throws `NullReferenceException` out of
`DisableBurstForSystemInternal` and the registration never happens at all.

### The pass was load-bearing through 1.2 — measured, not assumed

A counter placed in `IMod.Init()`, walking `World.All` and counting how many of
the worlds it hands to `AddWorld` actually contain the system whose bypass the
mod needs, read:

```text
Client            armed by this pass in  0/6  live world(s)
Dedicated Server  armed by this pass in  1/12 live world(s)
```

Both lines are **measured**, on game version `1.2.1.5-8be0`: the client one is
recorded beside the counter in `reusable-cattle-box` (and re-read on 1.3.0.2,
unchanged), the server one in that mod's notes from 2026-08-22. The 1.3.0.5
server log of 2026-10-08 reads `1/12` as well — the same number with a
different meaning, below. The mod count does not colour the result — the counter tests
`world.GetExistingSystem(typeof(EquipmentUpdateSystem)) != SystemHandle.Null`,
which is a property of the world rather than of anyone's Burst registration, so
another mod un-Bursting the same system cannot inflate it.

What the counter shows is that a world containing the system already existed
when `Init()` ran — not by itself who armed it. On the 1.2 server, together with
the ordering in the table above, that is the load-bearing case: `StartEcs`'s own
call to `AddWorld` had already taken its snapshot, so the manual pass was the
only thing that armed that world. On the 1.3.0.5 server the same `1/12` means
`Init()` now runs after `CreateServerWorld` but before the conversion, whose
callback then resets the set and arms the ServerWorld itself — the manual pass
still runs, and is overwritten.

**On the client, `0/N` with `N > 0` is the healthy result, not a fault.**
`Init()` runs before `ServerWorld` and the client's own simulation world are
created, so at the moment the counter above reads, none of the worlds the mod
actually cares about exist yet to arm — that is not the dedicated-server bug,
it is the client working as intended: `StartEcs` runs its own `AddWorld` pass
afterwards, once those worlds exist, and by then the registration from `Init()`
is already in place. A self-check written against this counter — warning
whenever `worlds > 0 && armed == 0` — fires on every healthy client. **The
world count says nothing about health at registration time**, so do not build a
self-check on it; check after the worlds you actually depend on exist. One thing
*is* worth reading from `Init()`, and it is not a count: `BurstDisabler` logs
`system X is already registered` (`PugMod.SDK.Runtime:761`) when a sibling mod
un-Bursted the same system before you — the interference that makes a
performance comparison meaningless a few sections above, and the one condition
this early that a mod can actually act on.

### How the breakage presents itself

As observed on 1.2 dedicated servers, and on any build where the ordering
breaks again: the client's own patch still works and suppresses its *prediction* — a
durability system, for instance, sits in `EndPredictedSimulationSystemGroup` —
but the server stays authoritative and its ghost snapshot overwrites the value a
few ticks later. The player sees the effect flicker in and revert.

Mods usually look half-broken rather than broken, because patches on methods the
client itself reaches from managed code — `SaveManager`'s save and load path,
the UI — keep working. Only the Burst-dispatched ECS half goes quiet.

**The property is per method, not per type, and picking the type is how this
goes wrong.** `PlayerController` and `PetExtensions` are ordinary managed
classes that host both kinds of member, and the two this chapter builds its XP
recipe around are the Burst-reached kind: `PlayerController.AddSkill` is the
case [scaling a value](#scaling-a-value-that-flows-from-a-burst-producer-into-a-burst-consumer) opens with ("do not patch the producer"), and
`PetExtensions.GetExperienceFromDamage` is called from
`AttemptToDealDamageToEnemy` (`Pug.Other:314789`) and from `AttackSystem`'s hit
check (`Pug.Other:12809`), both inside that same Burst sim path. What survives
the trap is a method managed code actually calls, which is not something the
declaring type can tell you.

Two variants worth recognising, both of which hide the problem further:

- The system runs in every world, but its input component is created only
  `if (isServer)` — so the client patched a system that never had any work to do.
- The system is declared `WorldSystemFilterFlags.ServerSimulation` only — so
  there is no client-side copy at all and the effect is completely dead.

**The SDK's own documented example is the second variant.** Pugstorm's
`BurstDisabler Example` page patches `SpawnEnvironmentObjectsInNewAreaSystem`,
which is a `struct : ISystem` carrying
`[WorldSystemFilter(WorldSystemFilterFlags.ServerSimulation, …)]`
(`WorldGen.EnvironmentalObjects:257-260`) — so it is on the trap's `ISystem`
path *and* has no client-side copy. That example works when the player hosts
(the hosting process runs a server world of its own) and, as written in that
example with no `AddWorld` pass, did nothing on a 1.2 dedicated server. Useful
as the canonical instance, and as a reminder that the official docs are not a
counter-argument to any of this: they simply do not cover the case.

Anything server-authoritative is in the blast radius: XP and skill grants,
durability, pet levelling, world simulation.

### Proving a patch is live on the server

Put a `Debug.Log` in the **static constructor** of the `[HarmonyPatch]` class.
An explicit static ctor suppresses `beforefieldinit`, so it fires on the class's
first use — which is the first `Prefix()` call **as long as nothing touches the
class earlier**. A `[HarmonyPatch]` class that also holds a static field another
patch reads, the shape [correlating private state](#correlating-private-state-across-two-methods) uses, runs its
initialiser at that access instead, and the line then proves the class loaded
rather than that the patch fired. Harmony's own `Prepare`, `TargetMethod(s)` and
`Cleanup` hooks touch the class the same way, while the patch is being applied.
Keep the probe class free of shared statics and of those hooks, and the line
appearing in the *server* log is the proof you want.

Two caveats make an absent line meaningless:

- **An idle dedicated server sits at `timescale = 0` and does not simulate.** A
  player must be connected, or nothing you patched in the simulation runs.
  `PauseWorld` (`DedicatedServer/Pug.Other:2690-2712`) disables the
  `SimulationSystemGroup` and nothing else — seven systems keep being updated
  every frame on the server, two of them groups (`NetworkReceiveSystemGroup`,
  `RpcCommandRequestSystemGroup`) that update their own members, networking and
  command buffers among them — so "no system updates at all" would be the wrong
  expectation to debug against.
- The server log stopped growing after world start on the CrossOver-hosted
  server this was observed on, so read it *after* the session, not during.

See [multiplayer and server](multiplayer-and-server.md) — for version and protocol issues, and for [getting one running](multiplayer-and-server.md#getting-one-running).

## Harmony binding mechanics

### Look for a public event before you patch

Not every hook has to be a patch. Some extension points are plain public
multicast delegate **fields** — not `event`s — which any assembly can assign to
or combine onto. `Mods.OnModManagementEvent` is one: it is declared `public
static ModManagementEventDelegate` in `modio.UI` (`ModIOBrowser.Mods`,
`modio.UI:2906`), and the game's own `RadicalMainMenuOption_OpenMods.Awake`
combines its handler onto it via `Delegate.Combine` at `Pug.Other:352265`.

**Correction: the field-versus-event distinction does not gate your access.**
This paragraph used to justify itself with "an `event` would only let you `+=`
from inside its declaring type", which inverts the C# rule: `+=` and `-=` from
outside are exactly what an `event` permits. What it withholds from outside is
assignment and invocation — and assignment is what the game itself does here
(`Mods.OnModManagementEvent = Delegate.Combine(…)`). So a `+=` would work
against either shape, and the thing a plain field additionally allows is
replacing or clearing the whole invocation list, which is a hazard rather than
a convenience: two mods that assign instead of combining can silently drop each
other's handler.

Whether a mod's reference to it survives the sandbox turned out not to be a
sandbox question at all. **Measured** 2026-09-03 against 1.2.1.5-8be0: a source
mod referencing a `modio.UI` type (`(int)default(UiViews)`) without [`accessesExtraAssemblies`](mod-anatomy.md#modmetadata-fields)
fails to compile at `CS0246: The type or namespace name 'UiViews' could not be
found` — the type is not visible to the compile at all, so the sandbox never
gets a say. With the flag set, the same source compiles **and** passes
verification. So the settings asset's assembly deny list was never the gate here
— the mod-anatomy chapter already had the mechanism: `accessesExtraAssemblies`
"adds every assembly loaded at game start as a metadata reference for the Roslyn
compile," which is the switch that decides whether `modio.UI` is reachable at
all. A rejected reference still is not a compile warning but a `CompileFailed`,
which [can take unrelated mods down with it](troubleshooting.md).

Whether CK has further hooks of this kind is **unverified** — no survey was made
— but checking the decompile for a public delegate field on the type you were
about to patch is cheap.

### `in`/`ref` parameters need `argumentVariations`

A patch that names its target's argument types, one of them an `in` parameter —
by-ref, written `in A` in the decompiled C# and rendered `A&` in Harmony's own
error text and anywhere else reflection names the type — fails at load with
`ArgumentException: Undefined target method for patch method …`. Searching the
`.cs` files for `A&` finds nothing; the parameter reads `in
EquipmentUpdateAspect equipmentUpdateAspect` (`Pug.Other:322943`). The mod
itself loads and sandbox-compiles fine (`safetyCheck=True`); only the bind
fails. That distinguishes it cleanly from the Burst case, which binds and stays
silent.

The bind is not the only casualty, though. That exception propagates out of the
loader's `PatchAll`, so the patch classes it had not reached yet are abandoned
with it — see [what a throw costs](mod-anatomy.md#harmony-patches-are-auto-discovered).

**And the mod goes on loading, which is what makes this expensive.**
`HarmonyPatchAssembly` wraps the call in `try/catch (Exception)`
(`PugMod.Loader:1471-1485`), logs `failed to patch mod <name>, got exception`
plus the exception, and returns normally; the load continues from there. So the
mod appears in the mod list, its assembly is registered, and an unknown number
of its patches simply are not there — a single logged line between a working
mod and a half-patched one.

Add the variations array, `ArgumentType.Ref` for each `in`/`ref` parameter
(`ArgumentType.Out` for `out`) and `ArgumentType.Normal` for each by-value one:

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
type exclusion"), as is `System.Reflection` member access. **`AccessTools` is
not the only one**, so do not read this as "use a different `HarmonyLib` helper
instead": the deny list names fifteen `HarmonyLib.*` types, `Harmony` itself,
`Traverse`, `PatchProcessor`, `Transpilers` and `ReversePatcher` among them, so
a manual `new Harmony(...).Patch(...)` hits the next wall rather than a way
round. The `[HarmonyPatch(typeof(X), nameof(X.Y))]` attribute form is fine,
because that reflection runs inside trusted `0Harmony.dll`. Details in [sandbox rules](sandbox.md).

Two ways round exist, and neither solves this problem. A mod built with
`skipSafetyChecks: true` has no sandbox and can call `AccessTools` and `new
Harmony` directly — `AutoTarget` does both — at the cost described in [sandbox rules](sandbox.md).
And CoreLib, itself sandboxed, applies patch classes on demand through the
loader's `API.ModLoader.ApplyHarmonyPatch` — which hands one `[HarmonyPatch]`
class to the same sandbox-checked patcher the auto-discovery uses
(`PugMod.Loader`'s `HarmonyPatchType`), so the target is still named by the
attribute and a by-ref one still needs `argumentVariations`.

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

**Trap when picking the overload:** `PlaceObjectSlot` (`Pug.Other:322907-323257`)
declares exactly *one* `PlaceItem`, the three-argument `(in EquipmentUpdateAspect,
EquipmentUpdateSharedData, LookupEquipmentUpdateData)` at `Pug.Other:322943`.
Five other slot classes declare a `PlaceItem` of their own. `BucketSlot`'s
(`Pug.Other:321777`) has the very same parameter list, and `FishingRodSlot`'s
(`Pug.Other:322331`) differs only in taking the last two by `in` as well;
`PaintToolSlot`, `SeederSlot` and `WaterCanSlot` add a leading `ref
NativeList<PlacementHandler.EntityAndInfoFromPlacement>` (`Pug.Other:322723`,
`Pug.Other:323801`, `Pug.Other:324307`). A patch that picks its target by method
name rather than by owning type can therefore bind any of the six, and one that
picks by parameter shape can still bind `BucketSlot`'s.

**Three of them are subclasses of `PlaceObjectSlot`, and that costs you coverage
rather than merely risking a mis-bind.** `BucketSlot`, `PaintToolSlot` and
`WaterCanSlot` (`Pug.Other:321753`, `Pug.Other:322701`, `Pug.Other:324277`) all
derive from `PlaceObjectSlot` and declare both `UpdateEquipment` and `PlaceItem`
of their own: `UpdateEquipment` as `public new static`, shadowing the base's
(`Pug.Other:321761`, `Pug.Other:322705`, `Pug.Other:324285`), and `PlaceItem` as
`private static`, as the base's own is (`Pug.Other:321777`, `Pug.Other:322723`,
`Pug.Other:324307`). Because these are statics there is no virtual dispatch to
carry a patch across — the caller names the class outright, one branch per slot
type (`Pug.Other:438964`, `Pug.Other:438976`, `Pug.Other:438985`) — so the "sole
caller" relation above holds for each class separately. A patch on
`PlaceObjectSlot.PlaceItem` therefore covers neither bucket, paint-tool nor
watering-can placement. Patch each class you actually mean to cover.

**The audit question is what you patch, not what Burst touches.** `[BurstCompile]`
on the systems that *write* the components you read is irrelevant. `BurstDisabler`
is needed only when the **patch target itself** is executed by Burst. Read-only
access needs it not at all: an `EntityQuery.ToEntityArray` plus `GetComponentData`
out of a managed coroutine or `Update` requires nothing, even though Burst jobs —
`DropSelfJob` (`Pug.Other:90696`), for instance — match the very same components.
`BurstDisabler` is not a precondition for touching ECS from a mod, and a
needless `DisableBurstForSystemAndJobs` is not free.

### A postfix on an input-driven method fires per input tick

`PlaceItem`'s postfix runs after *every* call, including every early return — no
valid placement spot, cooldown, and so on. While the player **holds the place
button down** on a placeable item, that is roughly one call per input tick.

**Correction: it is not called while the item is merely equipped.** The call
site guards it twice before entering (`Pug.Other:322931`, `Pug.Other:322935`):

```csharp
if (!secondInteractHeld) return false;
if (hasItemInMouse)      return false;
```

so the button, not the equipped item, is what drives the rate. What the method
does protect **internally** is everything past that: five further guards are
early returns inside the body rather than conditions at the call site, and a
prefix runs ahead of all five.

| Guard | Location |
|---|---|
| `if (!valueRW.canPlaceObject) return;` | `Pug.Other:322946` |
| `CanPlaceItem` → `tilePlacementTimer` (0.65 s in this build) — **not a pure guard**: it stops the timer for a non-tile prefab (`Pug.Other:323163`) and starts it on the success path (`Pug.Other:323180`), so a prefix returning `false` suppresses those writes too | call `Pug.Other:322956`, declaration `Pug.Other:323158`, timer logic `Pug.Other:323163-323180` |
| `timeSincePlaced.isRunning && … < 1f && pos == positionLastPlacedAt` | `Pug.Other:322961` |
| `PlayerController.CanConsumeEntityInSlot` | `Pug.Other:322973` |
| Creative / `ObjectType.PlaceablePrefab` check | `Pug.Other:322977` |

The second guard is not the only impure one in that sequence. Between the third
and the fourth the body may restart `timeSincePlaced` (`Pug.Other:322968`,
behind a condition of its own) and always writes `positionLastPlacedAt`
(`Pug.Other:322972`), so a placement rejected by guard 4 or 5 can still have
touched the state guard 3 reads.

The first point past all five that commits the placement **as player state** is
`playerStateCD.ValueRW.PushState(PlayerStateEnum.PlaceObject)` (`Pug.Other:322992`),
immediately followed by `StartCooldownForItem` (`Pug.Other:322994`). That is a semantic
choice rather than the literally first unconditional statement: `Pug.Other:322991`
already writes `placeObjectStateCD.positionToPlaceAt` unconditionally. It is the
better signal because it is what the rest of the game reads as "a placement is
happening".

`EntityUtility.AddTile` (`Pug.Other:323003`) comes later and is **not universal**: it
sits inside `if (…tileLookup.HasComponent(equipmentPrefab))`, so it is reached
only for *tile* placements. Its `else` branch handles everything else — a chest,
a cattle box, a critter. Gating a mod on "AddTile was reached" silently misses
every non-tile placeable.

Any side effect gated only on item identity over-fires massively. Gate instead
on a signal that the placement actually **committed**: the `PlaceObject`
player-state push for any placeable, a *completed* `AddTile` when you
specifically mean tiles, or the consume branch being taken. The postfix firing
is not that signal — and neither is entering `AddTile`, which outside creative
mode queues nothing for tileset 2 anywhere, and nothing for any other tileset at
the four positions `(0,0)`, `(0,1)`, `(-1,1)` and `(1,1)` unless the tile is a
`roofHole` (`Pug.Other:265210`). Through 1.2 it also returned early, with an
error, for a `tileSet` outside `0..74`; 1.3 dropped that check.

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
suspected conflict, toggle the foreign mod through the `disabledMods` set in
`state.json` — which belongs to the mod.io plugin's `Registry`
(`modio.UnityPlugin:34712`), not to `PugMod.Loader`, whose own list is
`unsupportedModsToLoad` and does the opposite ([the two disable lists](troubleshooting.md#the-loaders-two-disable-lists-are-opposites)) — and
count your own patch's invocations in both states.

**A log line's count is not an event count.** A client connected to a dedicated
server can log the same postfix more than once for a single release — NetCode
re-prediction re-runs client-side logic, and how many times follows connection
latency, not how many items actually arrived. A server logged once per item in
the same sessions (1.2.1.5, 2026-08-22), which fits a process that does no
re-prediction; that this is the reason is **unverified**, since the
re-prediction count is a NetCode runtime property that neither decompile states.
The zero-versus-non-zero comparison above still holds — an absence is an absence
on either side — but do not read an absolute count past that as if it counted
events.

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
too. One call is not one buffer entry, though: placing a wall appends a second,
a `Command.Remove` for `roofHole` at the same position (`Pug.Other:265218-265228`),
and placing ground appends two, removing `pit` and `water`
(`Pug.Other:265230-265249`), so a prefix that counts or rewrites entries
one-for-one is wrong for every wall and every ground tile. Many
other things write the buffer directly, without passing through it at all —
world generation, plant growth and the `SpawnTileOnDeathCD` handler among them,
but `new TileUpdateBuffer` appears at more than thirty distinct sites in
`Pug.Other` alone, so treat those three as examples rather than as the list to
plan around. Patching there lets you change *where* and *what* is placed without
reimplementing the act of placing, and per-tile decisions cover grid/multi-tile
placement for free — but not *whether* one happens: see [Never suppress an `AddTile` call to veto a placement](world-and-mechanics.md#never-suppress-an-addtile-call-to-veto-a-placement)
for why blocking the call costs the player their item for nothing.

`AddTile`'s parameters carry no player or inventory context. Get that from a
prefix on `UpdateEquipment` marked `[HarmonyPriority(Priority.First)]` — then do
the actual work in the `AddTile` prefix. **The priority orders your prefix, it
does not rescue it:** a foreign prefix returning `false` does not suppress
later prefixes at all. `WritePrefixes` iterates every prefix and ANDs each
result into `__runOriginal`, emitting the skip only after the loop
(`0Harmony:10287-10323`), so yours runs whatever its priority. What the priority
buys is seeing the state *before* the foreign prefix has altered it, and the
matching **postfix runs even when a prefix returned `false`**. One
code path then serves both the vanilla and the modded world.

Recorded as an observation, not a rule: **while a foreign prefix sat on the
method, our own prefix on it fired without `BurstDisabler`** — and went quiet
again when the foreign mod was removed, unless the `AndJobs` variant was used. A
patch that only works while another mod is installed is a real and confusing
outcome.

**The mechanism is a registry shared by the whole process, gating one global
flag.** `DisableBurstForSystemPatch.Prefix(SystemHandle sh, out bool? __state)`
(`PugMod.SDK.Runtime:889-897`) patches `WorldUnmanagedImpl.UpdateSystem` and
tests `BurstDisabler.SystemHandlesToDisableBurstFor.Contains(sh)`; on a hit it
sets the static `BurstCompiler.Options.EnableBurstCompilation = false` for the
duration of that system's update, restored in the postfix. That set is one
`HashSet<SystemHandle>` for the entire process, and `AddWorld` fills it from
every mod's `DisableBurstForSystem`/`DisableBurstForSystemAndJobs` registrations
without recording which mod added which handle — so once *any* mod has
registered a system for the running world, the flag it flips during that
system's update is not scoped to that mod's own code. The installed
PlacementPlus (mod.io `3400322`) calls
`BurstDisabler.DisableBurstForSystemAndJobs<EquipmentUpdateSystem>()`, and
`auto-rail-bridges` in this workspace registers the same system the same way.
While PlacementPlus was installed, `EquipmentUpdateSystem` and the jobs it
schedules ran un-Bursted for every mod in the process — in a client or hosting
process, where the observation was made; PlacementPlus carries no `AddWorld`
pass of its own, so on a 1.2 dedicated server its registration armed nothing —
which is why a prefix on a method inside that window fired without its own
registration, and why removing PlacementPlus made it go quiet again unless the
mod registered the system itself, which is what the `AndJobs` variant did.

The general claim still does not follow from this case: Burst selection is
per *system*, not per patched method, so "a patched method cannot be
Burst-replaced" stays false in general — this only explains why *this*
particular patch worked.

**This is the isolation hazard, stated from the other side.** A measurement of
your own mod, taken while a foreign mod has registered the same system,
proves nothing about your own registration — the shared handle set is exactly
why a foreign mod's `DisableBurstForSystem*` call can carry your patch target
un-Bursted without your mod ever registering it.

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

That example obtains the active character's GUID — in a process that hosts its
own world; see below.
`PlayerController.characterGuid` does not exist,
`Manager.saves.GetCharacterGuid()` is out — `SaveManager` is on no deny list,
but calls through `Manager.saves` have been *observed* to fail verification
anyway (see [what is banned](sandbox.md#what-is-banned)) — and `HarmonyLib.Traverse` is banned as a
reflection wrapper.

**Correction: `EntityManager.HasComponent<CharacterGuidCD>` plus
`GetComponentData` does not trip the sandbox.** This passage used to list that
expression as a fourth closed route, "trips the sandbox on namespace, type and
member." **Measured** 2026-09-03 against 1.2.1.5-8be0: eight side-loaded probes
(`skipSafetyChecks: false`, every mod.io mod off, one expression isolated per
assembly) all passed verification — including the full expression, reading
`.Value` into a `Hash128` and calling `.ToString()`. The sandbox's verdict is
per assembly and its message reports counts, not names (see [what is banned](sandbox.md#what-is-banned)), so
attributing a count to one expression only holds when that expression was
isolated the way this measurement isolated it; the original claim was not, and
the real failure it recorded was misattributed. Whether a direct `EntityManager`
read is now the better route for this particular lookup is a separate question
this measurement does not answer: the worked example below still solves the
correlation problem it was written for — knowing *which* character just
deserialised is not the same question as whether `CharacterGuidCD` can be read
at all.

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

**The example above does not satisfy the third precondition from the source
alone.** `SaveManager.SetCharacterId(int)` (`Pug.Other:380762-380770`) warns on
an incompatible version and sets `_characterDead` and `_characterId` — it
triggers no deserialize, and nothing in either tree links it to
`CharacterData.OnAfterDeserialize`.

**Nothing couples them at the producer — the pairing is the caller's ordering.**
`OnAfterDeserialize` is Unity's `ISerializationCallbackReceiver` hook, which
`CharacterData` implements (`Pug.Other:380208`). Since 1.3 nothing in the game
calls it explicitly: every invocation comes from Unity itself, through
`SaveManager.DecodeJson<T>` (`Pug.Other:380732-380736`), which runs
`JsonUtility.FromJsonOverwrite` over a character's JSON. Its body is empty
(`Pug.Other:380294-380296`). Through 1.2 it carried the save-version upgrade and
had one explicit caller as well — `_ClearCharacter(int i)`, the routine that
resets a character slot — so a postfix on it also fired on every slot reset. 1.3
moved that work into `CharacterData.UpgradeIfOutdated()` (`Pug.Other:380318`),
which the game calls explicitly after each character decode (`Pug.Other:380758`,
`Pug.Other:380781`, `Pug.Other:381705`) and at the end of `_ClearCharacter`
(`Pug.Other:381608`); a postfix on `OnAfterDeserialize` now sees the deserialize
callbacks and nothing else. It also sees them **before** the upgrade: the record
is as stored, and state the upgrade derives — `nonSerialized.discoveredObjects`
is rebuilt at its end (`Pug.Other:380416-380420`) — is not there yet. The
example reads only `characterGuid`, a serialized field, so it is unaffected.

Which decode follows the producer matters more. Of the three, the one at
`Pug.Other:381705` is `SaveManager.Init` reading every existing character file
once at startup, and the one at `Pug.Other:380781` serves a benchmark data
provider — the benchmark scene sets character 60 and decodes it straight away
(`Pug.Other:383117-383118`), a case of its own that also hosts its world.
Outside it, the only decode that comes *after* a character is chosen is the
network one —
`GetCharacterDataFromSerialized` (`Pug.Other:380751-380759`), whose sole caller
is `StartGameRPCSystem` (`Pug.Other:133051`), a `ServerSimulation` system
(`Pug.Other:132644`) decoding the character data a joining player sent.
`SetCharacterId` has four call sites in the client tree. The one the worked
example is about, `StartGame(int characterID)` (`Pug.Other:360562-360574`), sets
the id and then immediately triggers the scene load —
`Manager.load.LoadIntroScene()` or `LoadMainScene()`. When that process also
hosts the world, its server world later decodes the player's character data,
and that decode fires the callback. When it joins someone else's server or a
dedicated one, the decode happens in the other process, nothing in this one
clears the flag, and the example leaks it — the third precondition failing
exactly as described above. `GoToCharacterTypeSelection`
(`Pug.Other:360576-360580`) is the plain contrast: it sets the id and pushes a
menu, with no load and so no deserialize.

So the two methods are coupled by nothing except the order the caller puts
them in, and the deserialize that pairs with `StartGame` is a server-world
decode, not a file read. The pattern is sound; the pairing now rests on a named
mechanism rather than an unknown, but that mechanism holds only for a hosting
process — treat it as the part you still verify for your own two methods
rather than as one demonstrated here.

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
   `GetBuffer`), **rewrite the pending value and let the original run** so it
   applies your inflated number. A `void` prefix is the shape both XP mods here
   use (`faster-talents`, `faster-pet-talents`); a `bool` one returning `true`
   behaves identically.

This is robust regardless of whether the consumer's inner *job* stays Burst: you
are mutating the shared component memory that job then reads. It also leaves the
system's own guards (max level, caps) intact, so the change becomes a natural
no-op at the cap. Querying and `SetComponentData`/`GetBuffer` from inside the
prefix are sandbox-safe.

### Worked example — XP grants

Two XP choke points fit this shape:

| Track | Producer | Component | Burst consumer |
|---|---|---|---|
| Player skill XP | `PlayerController.AddSkill(Entity, SkillID, float amount, EntityCommandBuffer, bool isServer)` (`Pug.Other:312996`) — the sole creator of the component, only `if (isServer)` | `AddSkillValueCD : IComponentData` (`float amount`; `int` until 1.2) | `AddSkillValueSystem` (adds `amount` to `SkillProgressBuffer.progressValue`, moves the whole part into `SkillBuffer.Value`, keeps the remainder; only that transfer is guarded `levelFromSkill < maxSkillLevel`) |
| Pet XP, when the **pet** lands the hit | `PetExtensions.GetExperienceFromDamage(dmg) = clamp(dmg / 20, 1, 250)`, appended by `AttackSystem.CheckForHit` (`Pug.Other:12807`) | `AddPetExperienceBuffer : IBufferElementData` | `PetHandlerSystem` (`pet.objectData.amount += amount`, guarded `!IsAtMaxLevel`) |

**Skill XP is fractional since 1.3, so scale it as a float.** Until 1.2 the
amount was an `int`; 1.3 made it a `float` and added the `SkillProgressBuffer`
accumulator. A projectile grants `weaponCooldown * 2.5` per hit, and one with
no weapon cooldown grants `0.25` (`Pug.Other:312962`); a damage source scales
the same product by its `inheritedSkillFraction` (`Pug.Other:312966`), so
many grants are below one point. A prefix that computes an `int` and writes it
back still compiles — the assignment to the `float` field is implicit — and
silently rounds each grant: `faster-talents` 1.3.1 rounded to the nearest
integer with a floor of 1, which turns a `0.25` grant at 3× into `1` instead of
`0.75`. Multiply the field and leave the remainder to the system.

**The fix for 1.3 does not compile on 1.2, and a mod tagged for both must
compile on both.** A mod is compiled at load time against the installed game, so
`cd.amount *= mult` is error CS0266 against 1.2's `int` field — `faster-talents`
1.4.0 shipped that way while still tagged for 1.2. Overload resolution solves it
without reflection, which the sandbox forbids: pass `ref cd.amount` to two
methods, `Scale(ref int, float)` and `Scale(ref float, float)`, and the compiler
picks the one matching the field it finds.

**Correction: pet XP has a second route, and "pets level only from dealt damage"
is wrong.** This section said there were exactly two choke points and that pets
gain XP from damage alone; both statements survived into `faster-pet-talents`,
which scales the buffer above and therefore reaches only the row in that table.
`PlayerController.IncreasePetXp` (`Pug.Other:313010`) raises the pet's `amount` by
writing an `InventoryChangeBuffer` entry directly (`Create.AddAmount`),
bypassing `AddPetExperienceBuffer` and `PetHandlerSystem` entirely. It has two
callers, and neither is covered by a prefix on `PetHandlerSystem`:

- `PlayerController.AttemptToDealDamageToEnemy` (`Pug.Other:314790`) — XP for damage the
  **player** deals, using the same `GetExperienceFromDamage` formula.
- `Pug.Other:94944` — **pet candy**, `xpIncrease = petCandyGivesMuchXp ? 100000 :
  componentData.xp`, which is XP with no damage anywhere in it.

Whether a mod wants that second route depends on what it is scaling; the point
is that patching the Burst consumer is not the whole surface.

**Measured in play, and the bypassed XP arrives unscaled.** On 2026-09-02, game
version `1.2.1.5-8be0`, a probe logged every buffer element
`faster-pet-talents`' prefix touched while a fresh pet fought with the
multiplier at 50×. The prefix accounted for eleven grants totalling 3500 XP; the
pet's own total, read back through `GetTotalTalentPoints`, was **3550**. The
missing 50 never passed the prefix — and had they, the same multiplier would
have made them 2500. So the second route is not a theoretical branch: it
delivers XP that a consumer-side patch neither sees nor scales.

The session mixed player damage and pet candy, and the amount itself tells the
two callers apart. The common `PetCandyEntity` is authored at `xp: 50`
(`Resources/Assets/GameObject/PetCandyEntity.prefab:125`; the rare and epic
tiers carry 500 and 5000), so candy produces that number by design. The damage
caller would have needed a single player hit of 1000-1019 after reduction to
reach exactly 50 through `clamp(dmg / 20, 1, 250)`. How hard the player hit in
that session was not recorded — the pet's own grants, about six raw XP each,
describe the pet's hits, not the player's — so the case for candy rests on the
exact match with its authored amount, not on a log line that named the caller.

**Neither of those two callers fires a plain prefix either, for the same reason
a prefix on `PetHandlerSystem` needs `BurstDisabler`:** both run inside Burst.
The pet-candy path (`Pug.Other:94944`) sits inside a Bursted `IJobEntity`, and
`AttemptToDealDamageToEnemy` (`Pug.Other:314658`) is reached from the Burst sim
path [above](#how-the-breakage-presents-itself). Un-Bursting the enclosing system or job is the route that reaches
`PetHandlerSystem` in the consumer recipe; whether it reaches these two is
**unverified**, since nobody has tried; binding the latter additionally needs
`argumentVariations`, being a `private static bool` that takes `in` aspects and
`NativeArray`s. When a value is written by several paths and some of them are
Burst, a prefix on the managed ones sees only those, and its silence looks like
absence.

**Poll the result instead of intercepting the write.** [`IMod.Update()`](mod-anatomy.md#the-imod-lifecycle)
runs every frame as the mod's own managed code and is not a patch, so no
producer — Bursted or not — can bypass it. Reading the pet's total there and
logging it on change observes every route into it, including the ones no
prefix can see; `GetTotalTalentPoints` is what the measurement above already
read it back through.

The trade is real: polling sees *that* the value changed, not *what changed
it*, so it answers "which routes exist and what do they deliver", not "who
called". Attribution has to come from separating the activities between reads
— fight with no candy given, then feed candy with nothing to fight — not from
the instrument itself. This is derived from the code above and from what the
2026-09-02 session's own read-back already did, not from a probe run for this
purpose: whether it separates the two callers above in practice is
**unverified**.

Every skill funnels through `AddSkill` — Mining (a fixed `1f` per hit since
1.3), Melee, Range and Magic via `AddCombatSkillByCooldown` (`Pug.Other:312952`;
until 1.2 combat passed the attack's `skillMultiplier` instead), Fishing,
Crafting, Cooking, Gardening, Running, Vitality, Summoning, Explosives. Its
callers include `PlayerAttackAspect` and the inventory handlers, which are
Burst-compiled, and that is precisely why patching `AddSkill` itself does not
work. Not every caller is: a managed `ServerSystem` command path calls it too
(`Pug.Other:415489`), so a prefix there fires for that path alone.

Both component types are declared in `Pug.ECS.Components` but sit in the
**global namespace**; the systems live in `Pug.Other`. Neither needs a `using`
in mod code.

Scaling differs between the two tracks. Skill XP is a `float` whose remainder
the system keeps, so multiply it and nothing else:

```csharp
cd.amount *= mult;   // AddSkillValueCD, since 1.3
```

Pet XP is still an `int`, so there round in a way that cannot silently zero a
grant:

```csharp
int boosted = (int)(amount * mult + 0.5f);
if (boosted < 1) boosted = 1;
```

Because the grant is server-authoritative (`AddSkill` runs only `if (isServer)`),
the effect applies wherever the server world runs — single-player, a host, and a
dedicated server as long as the consumer is armed there (the `AddWorld` pass
above, which both XP mods here carry) — and the mod needs the server side in its
`requiredOn` — see [mod anatomy](mod-anatomy.md).

## Instrumenting generated DOTS code

**The `OnUpdate` body you are reading in a mod's `.cs` file is not the one that
executes.** For any system using `Entities.ForEach` or `SystemAPI.*`, the DOTS
source generator has moved the body into
`Scripts/Generated/<System>__System_<id>.g.cs` as `__OnUpdate_<hash>()`, marked
`[DOTSCompilerPatchedMethod("OnUpdate_T0")]`, and the mod loader splices that
body back into the original method **in the source, before compiling it** — so
the generated code goes through the same Roslyn pass and the same sandbox check
as everything else you ship. The same routine does it for properties, collected
as `[DOTSCompilerPatchedProperty]` and logged as `Replacing property … with …`:
the original property takes over the generated one's accessors
(`PugMod.Loader:2532`), so code in the *source* property body is equally dead.
Player.log states it per mod:

```text
Replacing method <Ns>.<System>/OnUpdate_T0 with __OnUpdate_<hash>
```

Diagnostic code added to the replaced body in the source file therefore never
runs. It has to go into the `.g.cs`.

**A build can ship without that file, and say nothing.** `ModBuilder` collects
the generated code from `Temp/GeneratedCode/<ModName>/` (and
`Temp/NetCodeGenerated/<ModName>/`), but `Temp` starts empty in every batchmode
session, and Unity runs the source generators only when it recompiles the mod's
assembly — which it does not when no source changed since the last compile. The
build then succeeds with the original `OnUpdate` stub alone, Player.log has no
`Replacing method` line for the system, and its first update throws `This method
should have been replaced by codegen`. The settings asset's `forceReimport` does
not prevent it: it was set on the mod this was measured on (2026-10-06, Unity
6000.0.59f2), and the second of two builds with unchanged sources still shipped
no `.g.cs`. Bumping a source file's timestamp before the build makes Unity
recompile and the file returns. Two tells, both cheap: the build log names every
file it collects as `Adding generated file …`, and the compiled assembly under
`Library/ScriptAssemblies/` contains the string `DOTSCompilerGenerated`
whenever the mod has such code. That assembly is the last compile's output, so
it still carries the string after a build that did not recompile — the string
together with a build that has no `.g.cs` is the failure. This repository's guard for
both build paths is described in [the build environment](../build-environment.md#a-mod-with-dots-systems-must-recompile-on-every-build).

That file is also the better place to measure from: it is a `partial class` and
contains the system's **real** queries (`__query_<id>_0`, … with every filter and
`EntityQueryOptions` applied), so a measurement taken through them observes
exactly what the system observes instead of a hand-built replica. Fields and
helper methods can be added freely.

**Two limits:**

- **Leave the job alone.** The `Entities.ForEach` lambda in the source file is
  dead like the rest of the original body, so editing it does nothing. The job
  the generator built from it sits in the `.g.cs` as an ordinary struct, and
  whether instrumenting it there works is **unverified**: the procedure that was
  actually used put diagnostics *beside* the job, never inside it.
- **Do not introduce new `SystemAPI.*` usage**; that also requires generation.
  `EntityManager.CreateEntityQuery(new EntityQueryDesc { … })` plus
  `ToComponentDataArray<T>(Allocator.TempJob)` plus `UnityEngine.Debug.Log` are
  generator-free and sandbox-legal.

**Procedure — client.** Edit the `.g.cs` inside the mod.io cache
(`…/Public/mod.io/5289/mods/<modId>_<modfileId>/Scripts/Generated/`), then
restart the game. The loader reads every `.cs` from the mod's own directory
(`PugMod.Loader:1358`), not from its extraction under `…/Temp/Pugstorm/Core
Keeper/ModLoader/<ModName>/`, and deletes that extraction itself on each load
(`PugMod.Loader:1804-1806`) — so deleting it by hand, which this procedure used
to require, matters only where that `Directory.Delete` fails, as it does on an
unpatched Wine host ([platforms](platforms.md)). On a dedicated server there is nothing stale
either way: the same line (`PugMod.Loader:1803` in both builds) extracts to
`ModLoader/DedicatedServer/<fresh GUID>` there, a new directory per start. Leave
the ZIP under `…/Temp/Pugstorm/Core Keeper/5289/` alone — mod.io tracks
integrity and downloads through it.

**Syntax-check without Unity.** Copy the file into a scratch directory *without
`.g` in the name* and run `dotnet csharpier check` on it. CSharpier silently
skips `*.g.cs` ("Checked 0 files") but otherwise parses through Roslyn and
reports genuine syntax errors. The care is warranted: a `CompileFailed` can
cascade and desynchronise *other* mods, not only yours — see [troubleshooting](troubleshooting.md).

**Two traps when instrumenting a third-party mod:**

- **Do not press Mod.io in the in-game Mods screen while a newer release of that
  mod exists.** The mod-management pass it enables installs the new modfile over
  your edit; an up-to-date mod is left alone ([when that pass runs](mod-anatomy.md#the-in-game-mod-menu-and-when-modio-is-contacted)).
- Every mod update installs a new `<modId>_<modfileId>` folder and your edit
  stays behind in the old one, so keep a backup of the original file **outside**
  the cache. A `.bak` inside would not be compiled — the loader compiles
  `mod.Metadata.files` filtered to names ending in `.cs` (`PugMod.Loader:1798`,
  read at `PugMod.Loader:1358`) — but it would not move to the new folder
  either.

## Reading the live ECS world from a mod

Live-world access needs no Harmony routing at all: plain mod `Scripts/*.cs` may
query the ECS world directly, and the surface below loads sandbox-clean
(`safetyCheck=True`) for the component types it has been verified against — with
the per-component caveat spelled out below.

**Pick the world by measurement, not by name.** In a process that hosts —
single-player included — the authoritative inventories live in the
**ServerWorld**; a client joined to a remote server has only replicated copies
in its ClientWorld. Iterate `World.All`, run
`CreateEntityQuery(...).CalculateEntityCount()` for a probe component, and take
the world with the most entities. Hardcoding a world name breaks the moment the
topology changes.

**Trap: the world you measure may not be populated yet.** The measurement is
only safe as a one-shot if the ECS entities are certain to be deserialised by
then. An early callback — the player's spawn (`OnSpawn`; `OnOccupied` through
1.2), for example — can fire before that (observed on 1.2's `OnOccupied`;
whether 1.3's `OnSpawn` does too is **unverified**), and the probe then pins an
empty or simply wrong world for the rest of the session. A scanner that caches
its world therefore needs a re-probe path: after a run of consecutive empty
scans, measure again and re-pin. How many empty scans is per-mod tuning, not a
constant.

From there, `em.CreateEntityQuery(ComponentType.ReadOnly<…>())` →
`ToEntityArray(Allocator.TempJob)` → `GetComponentData<T>`, `HasComponent<T>`,
`GetBuffer<…>` all work.

**Correction: an isolated `CharacterGuidCD` read passes verification too.** This
section used to claim `HasComponent<CharacterGuidCD>` plus
`GetComponentData<CharacterGuidCD>` (with `Hash128`) fails verification at one
illegal namespace, one type and one member reference, and left open whether the
ban sits on those specific game-side types or on some narrower slice of the
generic surface. **Measured** 2026-09-03 against 1.2.1.5-8be0: the same
eight-probe round cited [further up](#correlating-private-state-across-two-methods) isolated that exact
`HasComponent`/`GetComponentData<CharacterGuidCD>` pair, and the full expression
with `Hash128`, each in an assembly of its own — both passed.

The premise behind the "same method, different type" framing does not
survive that: `GetComponentData` over `ObjectDataCD` and `LocalTransform`, and
`HasBuffer` / `GetBuffer` over `ContainedObjectsBuffer`, still load clean,
which is what the scanning idiom above rests on — that part is untouched. But
the count once attributed to `CharacterGuidCD` was not isolated the way this
measurement isolated it, so it cannot stand as a case of the same method
failing for that type specifically. What is settled is the isolation method
itself: the sandbox's verdict is per assembly and its message reports counts,
not names, so if a query trips the sandbox, bisect it by isolating the
expression in an assembly of its own rather than reading the count against
the deny lists.

### Identifying an entity as a particular object

**Trap: there is no per-object-type component.** Hunting the decompile for a
`<Thing>CD` that marks one kind of object is the wrong search and will fail after
a long detour. `EntityMonoBehaviourDataConverter.Convert` (`Pug.ECS.Conversion:5813`) fills
`ObjectTypeCD` and `ObjectDataCD` on *every* object entity, and those two carry
the identity. Another goes on unconditionally beside them and is worth knowing
before hand-rolling a category test: `ObjectCategoryTagsCD` (`Pug.ECS.Conversion:5838`), a
`ulong tagsBitMask` with a `HasAnyMatches` helper, which is how the game asks
"is this any of these kinds of thing" without an `objectID` list.

```csharp
// Pug.ECS.Components:4065-4068
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
carries the same identity components — so the query is almost never the filter.

**Use an empty tag component as a chunk prefilter, never as an identity test.**
`DiggableCD` is a null-byte tag:

```csharp
// Pug.ECS.Components:4687-4691
[StructLayout(LayoutKind.Sequential, Size = 1)]
[GhostComponent(PrefabType = GhostPrefabType.All)]
public struct DiggableCD : IComponentData, IQueryTypeParameter { }
```

It sits on everything a shovel can turn over — floor tiles, plants, dig spots —
which makes it worthless as an identity test and valuable in the query, where it
excludes non-matching archetypes cheaply. The game disambiguates the same way,
with `objectID ==` checks (`Pug.Other:306891`, `Pug.Other:307309`,
`Pug.Other:322506`). The pattern generalises — tag narrows, `objectID` decides —
while `DiggableCD`'s particular breadth is just one data point.

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

**Name the overload — `nameof` alone is ambiguous here.** `SaveManager` declares
both `WriteCharacter()` (`Pug.Other:381631`) and `WriteCharacter(int)`
(`Pug.Other:381636`), so the attribute needs the argument-type array; the parameterless
one delegates to the `int` overload, which is why patching that one covers both
call paths:

```csharp
[HarmonyPatch(typeof(SaveManager), nameof(SaveManager.WriteCharacter), new[] { typeof(int) })]
```

What the hook fires on, its symmetric load point, the trap that loses a save
silently, and the cost of writing on that thread are all in [writing in lockstep with the game's save](persistence.md#writing-in-lockstep-with-the-games-save).
