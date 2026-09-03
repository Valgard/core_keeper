# Patching Harmony and ECS

Core Keeper is a DOTS game whose simulation systems are Burst-compiled, and mods
are Harmony patches compiled at load time inside a sandbox. That combination
produces failure modes that look nothing like a normal Harmony problem: a patch
that loads cleanly and never fires, a system whose body is not in the file you
are reading, and a fix that works whenever a player hosts and is inert on a
dedicated server. This chapter covers how to make a patch bind, how to make it
fire, and how to read and write the live ECS world once it does.

Line numbers quoted below (`Pug.Other:295735`) are offsets into the decompiled
game assemblies — see [reverse-engineering](reverse-engineering.md) for how to produce that decompile.
**An unmarked citation is the client build.** The two builds' offsets differ for
the same code — `BurstDisabler.AddWorld` is `Pug.Other:2675` on the client and
`:2656` on the server — so a server citation says so, and resolving an unmarked
one in the server checkout lands on unrelated code.

## Three failure modes, three different causes

Before changing anything, classify the symptom. They have nothing in common
except that your code does not run.

| Symptom | Cause | Fix |
|---|---|---|
| `ArgumentException: Undefined target method for patch method …` at load | Harmony cannot resolve the target signature — typically an `in`/`ref` parameter | `argumentVariations` (below) |
| Mod loads, `safetyCheck=True`, patch binds, prefix never fires | The target is Burst-compiled; the managed IL you patched is never executed | `BurstDisabler` (below) |
| Works when a player hosts, dead on a dedicated server | an `ISystem` registered with `BurstDisabler` after the server took its snapshot — measured ordering, and it does not arise for a managed `SystemBase` | manual `AddWorld` pass (below) |
| Mod does not compile at all (`CompileFailed`) | Not a patching problem — an ordinary compile error, or a sandbox rejection | [sandbox rules](sandbox.md) tells the two apart |

## Why a Burst-compiled `OnUpdate` cannot be intercepted

Harmony rewrites managed IL. A Burst-compiled system never runs that IL, so
there is nothing for the patch to intercept — and Harmony has no way to tell you
that, because the bind itself succeeded.

The dispatch chain is worth knowing, because the fix only makes sense against
it. `WorldUnmanagedImpl.UpdateSystem` invokes `UnmanagedUpdate` as a
`$BurstDirectCall` (`Unity.Entities:67217`), which takes the Burst path when
`BurstCompiler.IsEnabled` **and** the compiled function pointer is non-zero — a
failed `CompileFunctionPointer` falls through to the managed body.
`CallForwardingFunction` then runs *inside* Burst, where `CheckBurst` is
`[BurstDiscard]` and therefore stripped, so its `status` stays `true` and the
per-system `BurstFunctionEnabledBits` flag is never read on that path. The
function then invoked is whatever `SelectBurstFn` (`:58169-58188`) stored — the
Burst-compiled body where one exists, and a managed forwarding thunk where the
function was not Burst-compiled. So "the Burst path" names the dispatch route,
not a guarantee that native code runs.

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
early** for a managed system. Between those two checks it does work that belongs
to both paths: it creates the shared `_harmony` instance on first use and runs
`PatchAll(typeof(DisableBurstForSystemPatch))` (`:805-809`). What the branch
selects is which system gets patched how:

| System shape | What actually happens |
|---|---|
| **`ISystem` struct** (unmanaged) | the two-halves mechanism below |
| **`SystemBase` class** (managed) | `PatchManagedSystem` Harmony-patches whichever of `OnCreate`/`OnStartRunning`/`OnUpdate`/`OnStopRunning`/`OnDestroy` the system actually declares, with prefixes and postfixes that toggle `BurstCompiler.Options.EnableBurstCompilation` around each call — immediately, globally, with no world registry involved. It logs `Could not find method X on Y` for each one it does not find and patches nothing there, so a system declaring only `OnUpdate` produces four such warnings and one patched method |

**The two halves below, the per-world snapshot, and the dedicated-server trap
built on it apply to the `ISystem` path only.** A managed `SystemBase` never
reaches `SystemTypesToDisableBurstFor`, so `AddWorld` has nothing to arm for it
and the server trap does not arise.

**The `AndJobs` variant is the exception — it is not `ISystem`-only.** Both
branches end in `CreateCompleteDependencyPatch` (`PugMod.SDK.Runtime:924`),
called from `PatchSystem` (`:867`, `isManaged: false`) and from
`PatchManagedSystem` (`:885`, `isManaged: true`). A managed system therefore
gets the same dependency-completing postfix from the same flag; only the
route to it differs.

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
`ManagedFunctionsUnBursted`, the `OnUpdate` you can patch. It also saves the
previous setting into `out bool? __state` (`PugMod.SDK.Runtime:963-971`), which
is what the postfix restores — and leaves `__state` null on the unarmed path, so
that postfix restores nothing when the prefix did nothing. If half 2 never armed
for the world your system runs in, half 1 is dead weight.

The same patch's `Postfix` restores `EnableBurstCompilation` to whatever it was
before the `Prefix` ran. So the bypass is a **window around that one system's
`UpdateSystem` call, not a lasting state change** — it closes the moment
`OnUpdate` returns, and the next system to update runs Burst-compiled again
unless it is armed too. `OnStartRunning` and `OnStopRunning` go through the same
forwarding table inside that window, so they are patchable while a system is
armed, and only then.

### Nested jobs need the `AndJobs` variant

`DisableBurstForSystem<T>` is not enough when the system's real work lives in a
nested job. `EquipmentUpdateSystem` (`Pug.Other:419765`) does everything in
`UpdateJob`, which carries its own `[BurstCompile]` (`:419767`) and calls
`PlaceObjectSlot.UpdateEquipment` (`:419899`). Note the blast radius before
reaching for it: that call sits in a `switch` on `slotType` (`:419894`) covering
`ShovelSlot`, `EatableSlot`, `WaterCanSlot` and the rest, so un-Bursting this
one system takes the equipment path off Burst for **every** slot type, not only
the one you meant to patch. With the plain variant, **no** patch on that path
fires; with `BurstDisabler.DisableBurstForSystemAndJobs<T>()`
(`PugMod.SDK.Runtime:783`) they do — provided the world is armed, which the call
alone does not guarantee. On a dedicated server it is not, and the same patches
stay silent with the `AndJobs` variant in place; that trap is two sections
below, and its log line is the false shortcut described just after this one.

**The criterion is what you patch, not which system it belongs to.**
`DisableBurstForSystem<T>` calls `DisableBurstForSystemInternal(type,
burstEnabled, addCompleteDependencyPatch: false)` (`:780`);
`DisableBurstForSystemAndJobs<T>` passes `true` (`:785`). For an unmanaged
`ISystem`, `PatchSystem` (`:862-870`) does nothing with that flag off — it
builds an empty method list and stops. With the flag on, it adds exactly one
more thing: a postfix on `OnUpdate(ref SystemState)` that calls
`state.Dependency.Complete()`. There, that one postfix is the entire difference
between the two calls — a managed system is patched either way, and the flag
only adds the same postfix on top.

**Do not call both variants for the same system.** `PatchSystem` ends
`_patchedMethods[systemType] = list` (`:869`), which **overwrites** the existing
entry, so an `AndJobs` call followed by a plain one for the same type discards
the record of the `Complete()` postfix while leaving the postfix itself
installed — patched behaviour the SDK no longer knows it applied.

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

Taking a system off Burst costs more than its `OnUpdate` running managed. The
bypass clears the **global** `BurstCompiler.Options.EnableBurstCompilation` for
the duration of that `UpdateSystem` call (`PugMod.SDK.Runtime:963-971`), so
everything dispatched inside the window runs un-Bursted —
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
requires `ClientInput`, `PlayerStateCD`, `PlayerGhost` — `Pug.Other:419114`),
and the job is scheduled with `Schedule()`, not `ScheduleParallel()`
(`:420660`), so it was single-threaded anyway and `Complete()` costs only the
frame overlap.

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
(`PugMod.SDK.Runtime:731`), so a sibling keeps your system un-Bursted with your
own call gone, and the two runs then differ in nothing. Two mods in this family
register `EquipmentUpdateSystem`. Disable the others for the comparison, or
measure a system nothing else touches. That is a small experiment, and it beats
both this anecdote and any assumption you would otherwise make.

## The dedicated-server trap

**`DisableBurstForSystem<T>()` in `IMod.Init()` has no effect on a dedicated
server.** The call itself does everything it always does — it registers the
type, clears the enable bits, installs the SDK's patch — and none of it reaches
a world, so the prefix simply never fires. No error, no log line. The mod works
whenever a player hosts and does nothing on a dedicated server.

**"Does nothing in multiplayer" is the wrong scope, and this file said it until
2026-08-24.** A hosting client is not affected: `StartEcs` creates the
ServerWorld in that same process (`Pug.Other:2654`, guarded at `:2652` by
`worldId != -1 && requestedPlayType != PlayType.Client` — **both** conditions,
which is why the menu path below creates none despite not being a pure client),
adds it to `_allWorlds`, and arms both worlds at `:2673-2675` — all of it after
`Init()` on the client ordering. So host-based multiplayer works, and on the
observed builds the defect appears on the dedicated server alone. What it
belongs to is the *ordering*, not the binary: a mod that registers after its own
`StartEcs` — calling `DisableBurstForSystem*` from `ModObjectLoaded` or `Update`
instead of `Init` — reaches the identical dead patch on a hosting client. The
distinction matters when reading a bug report: "works for me in multiplayer"
from a host neither reproduces nor refutes it.

The cause is the lifecycle order — which is **measured**, not derived; the
paragraphs below say why no derivation replaces it, and one that was tried was
wrong. `BurstDisabler.AddWorld` is called from exactly one place,
`ECSManager.StartEcs` (`Pug.Other:2675` in the client build, `:2656` in the
server build), and it **snapshots** the types registered up to that moment.
Nothing back-fills that snapshot for a world already passed to `AddWorld` — but
neither set is permanent, and a later world load rebuilds them correctly; see
the bound on this below. Two different resetters exist and only one of them
appears there: `ResetWorlds` clears the per-world handles, while
`BurstDisabler.Init()` (`PugMod.SDK.Runtime:739-750`) — a
`[RuntimeInitializeOnLoadMethod(SubsystemRegistration)]`, so once per process
start rather than per world — additionally unpatches Harmony, clears
`_patchedMethods`, and clears the **type** registry itself.

Note what this does *not* mean: the call is present and runs on both builds, at
the end of `ECSManager.StartEcs` once the worlds have been created. The server
does not skip it. So "`AddWorld` never runs server-side" is the wrong diagnosis —
it runs, it is simply reached before your `Init()` had a chance to register
anything.

The two builds differ twice inside that one method, and only one of the two
differences is about the call. The client's `StartEcs` opens with a
client-world creation block (`:2645-2651`) that the server build does not have
at all — so the worlds `AddWorld` is handed are not the same set on the two
sides. Beside the call itself, the client kicks off authoring-data conversion as
a coroutine and falls straight through to `AddWorld`, so the conversion has not
run yet; the server drains the same enumerator synchronously first. Neither
difference affects the snapshot problem, but together they mean the surrounding
state is not the same on the two sides.

| Process | Order (measured in the logs) | Result |
|---|---|---|
| Client | `Init()` first, worlds built afterwards | registration precedes the snapshot → works |
| Dedicated server | worlds built first (`adding worlds to the update loop`), `Init()` afterwards | snapshot empty → patch dead |

**The decisive file is not in the decompile at all, which is why measurement is
the only route.** The server build's own guard names its real entry point and
then acts on it — `UnityEngine.Debug.LogError("Server should start from
ServerMain!")` followed immediately by `Application.Quit()`
(`Pug.Other:361103-361104`, server build), so a server build reaching
`SceneHandler.Awake` with a ServerWorld already created terminates rather than
continuing. That is what rules the `SceneHandler.Awake` → `StartEcs` route out
as the server's ordinary path. And `ServerMain` exists nowhere as a type:
that string is its single occurrence in either checkout, with zero `class`/`struct`
declarations. Anyone tracing the boot order follows the guard to a file that was
never decompiled. Check this before attempting a derivation; it is cheap and it
settles the question.

**That table is a measurement, and no derivation has replaced it — one was
tried and was wrong.** The tempting mechanism is: `StartEcs` is reached from
`SceneHandler.Awake` (`Pug.Other:361075`, calls at `:361114`/`:361119` in the
server build) while `IMod.Init()` comes from `Loader.Update`
(`PugMod.Loader:1157`, `:1159`), so Unity's rule that every `Awake` precedes
every `Update` fixes the order. **It does not.** `Loader.Update` is reached from
two places, not one. Both go through `Integration.Instance.Update()` — an
`IIntegration` interface call that lands on `Loader` only because
`Loader : IIntegration` — and one of them sits in `Manager.EarlyInit`
(`Pug.Other:263334`, client build; server `:263271`), which is a
`[RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterAssembliesLoaded)]`
(`:263245` client, `:263187` server) and therefore runs *before* any scene
`Awake`. The other, the MonoBehaviour `Update()` the derivation actually means,
is at `:270347` (server `:270188`). The lifecycle rule never applies to the
first path, so it cannot settle the ordering. Nor is the hosting
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

`World.All` is sandbox-legal (`safetyCheck=True` on both client and server).
The pass is harmless in the client ordering, but not because of the `HashSet`
behind `AddWorld`: that only makes re-adding the *same* world free, and
`World.All` is a strict superset of what startup arms — `StartEcs` calls
`AddWorld` over `_allWorlds` alone, the one or two worlds it created
(`:2673-2675`), where the counter below measures six live worlds on a client.
What makes the extra worlds harmless is that arming one is a set insertion with
no other effect, so a world the mod does not care about carries an entry nothing
ever consults.

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
"dead from launch" rather than intermittent — and why a dedicated server, whose
world in an observed session was loaded once at startup and kept, never got the
second chance a world switch would hand it. Nothing in either tree makes that a
property of the binary: the server build carries a full `UnloadWorldsInternal`
(`:2890`), reachable from `OnSceneUnload` and from `StartEcs`'s own
"Trying to start new ECS instance without unloading old" path (`:2622-2626`), so
a second `StartEcs` there is not forbidden — merely not something an ordinary
server run does.

**`EarlyInit` is not the fix.** Moving the registration there fails on client
*and* server: `TypeManager` is not initialised that early, so
`TypeManager.IsSystemType` throws `NullReferenceException` out of
`DisableBurstForSystemInternal` and the registration never happens at all.

### The pass is load-bearing — measured, not assumed

A counter placed in `IMod.Init()`, walking `World.All` and counting how many of
the worlds it hands to `AddWorld` actually contain the system whose bypass the
mod needs, read:

```text
Client            armed by this pass in  0/6  live world(s)
Dedicated Server  armed by this pass in  1/12 live world(s)
```

Both lines are **measured**, on game version `1.2.1.5-8be0`: the client one is
recorded beside the counter in `reusable-cattle-box`, the server one re-taken on
2026-09-02 from a local dedicated server's own log with thirty mods loaded. The
mod count does not colour the result — the counter tests
`world.GetExistingSystem(typeof(EquipmentUpdateSystem)) != SystemHandle.Null`,
which is a property of the world rather than of anyone's Burst registration, so
another mod un-Bursting the same system cannot inflate it.

On the server, that one world is the manual pass's own doing: `StartEcs`'s own
call to `AddWorld` (above) had already taken its snapshot before `Init()` ran,
so without the `foreach` loop nothing in that world would be armed at all. This
turns "the manual pass matters on the server" from a derivation into a
measurement.

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
`system X is already registered` (`PugMod.SDK.Runtime:835`) when a sibling mod
un-Bursted the same system before you — the interference that makes a
performance comparison meaningless a few sections above, and the one condition
this early that a mod can actually act on.

### How the breakage presents itself

The client's own patch still works and suppresses its *prediction* — a
durability system, for instance, sits in `EndPredictedSimulationSystemGroup` —
but the server stays authoritative and its ghost snapshot overwrites the value a
few ticks later. The player sees the effect flicker in and revert.

Mods usually look half-broken rather than broken, because patches on methods the
client itself reaches from managed code — `SaveManager`'s save and load path,
the UI — keep working. Only the ECS half goes quiet.

**The property is per method, not per type, and picking the type is how this
goes wrong.** `PlayerController` and `PetExtensions` are ordinary managed
classes that host both kinds of member, and the two this chapter builds its XP
recipe around are the Burst-reached kind: `PlayerController.AddSkill` is the
case [scaling a value](#scaling-a-value-that-flows-from-a-burst-producer-into-a-burst-consumer) opens with ("do not patch the producer"), and
`PetExtensions.GetExperienceFromDamage` is called from
`AttemptToDealDamageToEnemy` (`Pug.Other:303957`), inside that same Burst sim
path. What survives the trap is a method managed code actually calls, which is
not something the declaring type can tell you.

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
An explicit static ctor suppresses `beforefieldinit`, so it fires on the class's
first use — which is the first `Prefix()` call **as long as nothing touches the
class earlier**. A `[HarmonyPatch]` class that also holds a static field another
patch reads, the shape [correlating private state](#correlating-private-state-across-two-methods) uses, runs its
initialiser at that access instead, and the line then proves the class loaded
rather than that the patch fired. Keep the probe class free of shared statics
and the line appearing in the *server* log is the proof you want.

Two caveats make an absent line meaningless:

- **An idle dedicated server sits at `timescale = 0` and does not simulate.** A
  player must be connected, or nothing you patched in the simulation runs.
  `PauseWorld` (`DedicatedServer/Pug.Other:2560-2582`) disables the
  `SimulationSystemGroup` and nothing else — seven systems keep ticking every
  frame, networking and command buffers among them — so "no system updates at
  all" would be the wrong expectation to debug against.
- The server log stops growing after world start, so read it *after* the
  session, not during.

See [multiplayer and server](multiplayer-and-server.md) — for version and protocol issues, and for [getting one running](multiplayer-and-server.md#getting-one-running).

## Harmony binding mechanics

### Look for a public event before you patch

Not every hook has to be a patch. Some extension points are plain public
multicast delegate **fields** — not `event`s — which any assembly can assign to
or combine onto. `Mods.OnModManagementEvent` is one: it is declared
`public static ModManagementEventDelegate` in `modio.UI` (`ModIOBrowser.Mods`,
`:2906`), and the game's own `RadicalMainMenuOption_OpenMods.Awake` combines its
handler onto it via `Delegate.Combine` at `Pug.Other:338594`.

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

Whether CK has further hooks of this kind has not been surveyed — but checking
the decompile for a public delegate field on the type you were about to patch is
cheap.

### `in`/`ref` parameters need `argumentVariations`

A patch whose target has an `in` parameter — by-ref, written `in A` in the
decompiled C# and rendered `A&` in Harmony's own error text and anywhere else
reflection names the type — fails at load with `ArgumentException: Undefined
target method for patch method …`. Searching the `.cs` files for `A&` finds
nothing; the parameter reads `in EquipmentUpdateAspect equipmentUpdateAspect`
(`Pug.Other:311319`). The mod itself loads and sandbox-compiles fine
(`safetyCheck=True`); only the bind fails. That distinguishes it cleanly from
the Burst case, which binds and stays silent.

The bind is not the only casualty, though. That exception propagates out of the
loader's `PatchAll`, so the patch classes it had not reached yet are abandoned
with it — see [what a throw costs](mod-anatomy.md#harmony-patches-are-auto-discovered).

**And the mod goes on loading, which is what makes this expensive.**
`HarmonyPatchAssembly` wraps the call in `try/catch (Exception)`
(`PugMod.Loader:1414-1428`), logs `failed to patch mod <name>, got exception`
plus the exception, and returns normally; the load continues from there. So the
mod appears in the mod list, its assembly is registered, and an unknown number
of its patches simply are not there — a single logged line between a working
mod and a half-patched one.

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
type exclusion"), as is `System.Reflection` member access. **`AccessTools` is
not the only one**, so do not read this as "use a different `HarmonyLib` helper
instead": the deny list names fifteen `HarmonyLib.*` types, `Harmony` itself,
`Traverse`, `PatchProcessor`, `Transpilers` and `ReversePatcher` among them, so
a manual `new Harmony(...).Patch(...)` hits the next wall rather than a way
round. The `[HarmonyPatch(typeof(X), nameof(X.Y))]` attribute form is fine,
because that reflection runs inside trusted `0Harmony.dll`. Details in [sandbox rules](sandbox.md).

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
at `:311319`. Identical-looking ones at `:310177` and `:311118` belong to
`BucketSlot` (`:310153`) and `PaintToolSlot` (`:311097`) — patching by shape
rather than by owning type binds the wrong method.

**Those are subclasses, and that costs you coverage rather than merely risking a
mis-bind.** `BucketSlot`, `PaintToolSlot` and `WaterCanSlot` (`:312626`) all
derive from `PlaceObjectSlot` and shadow both `UpdateEquipment` and `PlaceItem`
with `public new static` members of their own (`:310161`, `:311101`, `:312634`).
Because these are statics there is no virtual dispatch to carry a patch across
— the caller names the class outright, one branch per slot type
(`:419896-419902`) — so the "sole caller" relation above holds for each class
separately. A patch on `PlaceObjectSlot.PlaceItem` therefore covers neither
bucket, paint-tool nor watering-can placement. Patch each class you actually
mean to cover.

**The audit question is what you patch, not what Burst touches.** `[BurstCompile]`
on the systems that *write* the components you read is irrelevant. `BurstDisabler`
is needed only when the **patch target itself** is executed by Burst. Read-only
access needs it not at all: an `EntityQuery.ToEntityArray` plus `GetComponentData`
out of a managed coroutine or `Update` requires nothing, even though Burst jobs —
`DropSelfJob` (`Pug.Other:88847`), for instance — match the very same components.
`BurstDisabler` is not a precondition for touching ECS from a mod, and a
needless `DisableBurstForSystemAndJobs` is not free.

### A postfix on an input-driven method fires per input tick

`PlaceItem`'s postfix runs after *every* call, including every early return — no
valid placement spot, cooldown, and so on. While the player **holds the place
button down** on a placeable item, that is roughly one call per input tick.

**Correction: it is not called while the item is merely equipped.** The call
site guards it twice before entering (`:311307`, `:311311`):

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
| `if (!valueRW.canPlaceObject) return;` | `Pug.Other:311322` |
| `CanPlaceItem` → `tilePlacementTimer` (0.65 s in this build) — **not a pure guard**: it stops the timer for a non-tile prefab (`:311538`) and starts it on the success path (`:311553`), so a prefix returning `false` suppresses those writes too | call `:311332`, declaration `:311533`, timer logic `:311538-311555` |
| `timeSincePlaced.isRunning && … < 1f && pos == positionLastPlacedAt` | `:311337` |
| `PlayerController.CanConsumeEntityInSlot` | `:311349` |
| Creative / `ObjectType.PlaceablePrefab` check | `:311353` |

The first point past all five that commits the placement **as player state** is
`playerStateCD.ValueRW.PushState(PlayerStateEnum.PlaceObject)` (`:311368`),
immediately followed by `StartCooldownForItem` (`:311370`). That is a semantic
choice rather than the literally first unconditional statement: `:311367`
already writes `placeObjectStateCD.positionToPlaceAt` unconditionally. It is the
better signal because it is what the rest of the game reads as "a placement is
happening".

`EntityUtility.AddTile` (`:311379`) comes later and is **not universal**: it
sits inside `if (…tileLookup.HasComponent(equipmentPrefab))`, so it is reached
only for *tile* placements. Its `else` branch handles everything else — a chest,
a cattle box, a critter. Gating a mod on "AddTile was reached" silently misses
every non-tile placeable.

Any side effect gated only on item identity over-fires massively. Gate instead
on a signal that the placement actually **committed**: the `PlaceObject`
player-state push for any placeable, a *completed* `AddTile` when you
specifically mean tiles, or the consume branch being taken. The postfix firing
is not that signal — and neither is entering `AddTile`, which returns without
queuing anything for a `tileSet` outside `0..74` and skips the
`tileUpdateBuffer.Add` outside creative mode for tileset 2 at the four
positions around the core (`Pug.Other:256440-256465`).

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
the same sessions, which fits a process that does no re-prediction, though the
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
a `Command.Remove` for `roofHole` at the same position (`:256461-256473`), so a
prefix that counts or rewrites entries one-for-one is wrong for every wall. Many
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
outcome. The mechanism remains **unverified**: Burst selection is per *system*,
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

That example obtains the active character's GUID.
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
alone.** `SaveManager.SetCharacterId(int)` (`Pug.Other:363006-363014`) warns on
an incompatible version and sets `_characterDead` and `_characterId` — it
triggers no deserialize, and nothing in either tree links it to
`CharacterData.OnAfterDeserialize`. Whatever couples them comes from the call
site, not from the producer, and what couples them is **unverified**. The
pattern is sound; treat the pairing as the part you verify for your own two
methods rather than as one demonstrated here.

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
   applies your inflated number. A `void` prefix is the shape both mods here
   use; a `bool` one returning `true` behaves identically.

This is robust regardless of whether the consumer's inner *job* stays Burst: you
are mutating the shared component memory that job then reads. It also leaves the
system's own guards (max level, caps) intact, so the change becomes a natural
no-op at the cap. Querying and `SetComponentData`/`GetBuffer` from inside the
prefix are sandbox-safe.

### Worked example — XP grants

Two XP choke points fit this shape:

| Track | Producer | Component | Burst consumer |
|---|---|---|---|
| Player skill XP | `PlayerController.AddSkill(Entity, SkillID, int amount, EntityCommandBuffer, bool isServer)` — the sole creator of the component, only `if (isServer)` | `AddSkillValueCD : IComponentData` | `AddSkillValueSystem` (`SkillBuffer.Value += amount`, guarded `levelFromSkill < maxSkillLevel`) |
| Pet XP, when the **pet** lands the hit | `PetExtensions.GetExperienceFromDamage(dmg) = clamp(dmg / 20, 1, 250)`, appended by `AttackSystem.CheckForHit` (`Pug.Other:12591`) | `AddPetExperienceBuffer : IBufferElementData` | `PetHandlerSystem` (`pet.objectData.amount += amount`, guarded `!IsAtMaxLevel`) |

**Correction: pet XP has a second route, and "pets level only from dealt damage"
is wrong.** This section said there were exactly two choke points and that pets
gain XP from damage alone; both statements survived into `faster-pet-talents`,
which scales the buffer above and therefore reaches only the row in that table.
`PlayerController.IncreasePetXp` (`:302241`) raises the pet's `amount` by
writing an `InventoryChangeBuffer` entry directly (`Create.AddAmount`),
bypassing `AddPetExperienceBuffer` and `PetHandlerSystem` entirely. It has two
callers, and neither is covered by a prefix on `PetHandlerSystem`:

- `PlayerController.AttemptToDealDamageToEnemy` (`:303958`) — XP for damage the
  **player** deals, using the same `GetExperienceFromDamage` formula.
- `:92814` — **pet candy**, `xpIncrease = petCandyGivesMuchXp ? 100000 :
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
delivers XP that a consumer-side patch neither sees nor scales. (The session
mixed player damage and pet candy, so which of the two callers those 50 came
from is **unverified**; that they bypass the consumer is what the measurement
settles.)

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
body back into the original method **in the source, before compiling it**. The
same routine does it for properties, collected as
`[DOTSCompilerPatchedProperty]` and logged as `Replacing property … with …`, so
diagnostic code in a generated property body is equally dead — so the generated
code goes through the same Roslyn pass and the same sandbox check as everything
else you ship. Player.log states it per mod:

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

**Procedure — client only.** Edit the `.g.cs` inside the mod.io cache
(`…/Public/mod.io/5289/mods/<modId>_<modfileId>/Scripts/Generated/`), delete the
loader's extraction at `…/Temp/Pugstorm/Core Keeper/ModLoader/<ModName>/`, then
restart the game. The deletion step has no target on a dedicated server: the
same line (`PugMod.Loader:1742` in both builds) extracts to `ModLoader/<mod
name>` on the client but to `ModLoader/DedicatedServer/<fresh GUID>` on the
server, a new directory per start, so there is nothing stable to delete and
nothing stale to clear. Leave the ZIP under `…/Temp/Pugstorm/Core Keeper/5289/`
alone — mod.io tracks integrity and downloads through it.

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
  be compiled along with everything else — unless the manifest is the authority,
  which it is: the loader compiles `mod.Metadata.files` filtered to `.cs`
  (`PugMod.Loader:1737`, read at `:1301`), so a file no manifest lists is never
  opened. A `.bak` is safe from the compiler and unsafe from the next mod
  update, which replaces the folder; keep it outside either way.

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
a long detour. `EntityMonoBehaviourDataConverter.Convert` (`Pug.ECS.Conversion:5808`) fills
`ObjectTypeCD` and `ObjectDataCD` on *every* object entity, and those two carry
the identity. A third goes on unconditionally beside them and is worth knowing
before hand-rolling a category test: `ObjectCategoryTagsCD` (`:5833`), a
`ulong tagsBitMask` with a `HasAnyMatches` helper, which is how the game asks
"is this any of these kinds of thing" without an `objectID` list.

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

**Name the overload — `nameof` alone is ambiguous here.** `SaveManager` declares
both `WriteCharacter()` (`Pug.Other:363867`) and `WriteCharacter(int)`
(`:363872`), so the attribute needs the argument-type array; the parameterless
one delegates to the `int` overload, which is why patching that one covers both
call paths:

```csharp
[HarmonyPatch(typeof(SaveManager), nameof(SaveManager.WriteCharacter), new[] { typeof(int) })]
```

What the hook fires on, its symmetric load point, the trap that loses a save
silently, and the cost of writing on that thread are all in [writing in lockstep with the game's save](persistence.md#writing-in-lockstep-with-the-games-save).
