# The load-time sandbox

A Core Keeper mod ships C# sources (`Scripts/*.cs`) that the loader compiles
with RoslynCSharp at game start and then puts through a security verification;
the loader invokes nothing in an assembly that fails it. A mod can ship a
precompiled DLL beside its sources as well — the loader takes one only when the
manifest sets `accessesExtraAssemblies` (`PugMod.Loader:Loader:LoadDll:4`), and verifies it
too (`PugMod.Loader:Loader:LoadDll:29`) — but sources are the normal case and the one this
chapter describes. Everything here also assumes the manifest leaves
`skipSafetyChecks` at `false`: a mod that sets it is compiled and loaded with no
verification at all (`PugMod.Loader:Loader:LoadScripts:61`).

That verification is **default-allow with explicit deny lists**: seven
namespaces, sixteen types, seven assemblies and two members are listed, P/Invoke
declarations are refused besides, and a violation kills the mod at load time —
after the Editor build already reported success.

This chapter is what the sandbox forbids, and why that is narrower than it
looks. The commonest thing it costs you is file access — [storing configuration and state](persistence.md)
is how a mod does that anyway.

## What the verification checks

The check runs over **the mod's own compiled assembly** and counts references to
banned namespaces, types and members — in method bodies, and also in signatures,
field and local types, and base types. It is static: it does not care what a
reference would have done at runtime, only that it is there. What it does not
read is attributes. No checker looks at a member's custom attributes
(`Trivial.CodeSecurity:TypeChecker:SecurityCheckCode:1`), so a type named only
inside one — a `typeof` argument, or `[System.Diagnostics.Conditional("X")]` —
is never counted: **measured** 2026-10-16 on 1.3.0.6-6e73 with a probe mod whose
only `System.Diagnostics` reference was that attribute, and which the report did
not mention.

When it trips, `Player.log` shows these two lines — not adjacent: the occurrence
report described [below](#finding-the-banned-identifier) and a stack trace come between them, well over a hundred
lines in the measured case:

```text
Assembly 'X' has failed code security verification. Illegal Assembly Reference = 'N', Illegal Namespace References = 'N', Illegal Type References = 'N', Illegal Member References = 'N', Illegal PInvoke References = 'N'
mod X load error: CompileFailed
```

The first is **one line**, the counts are single-quoted, and there are five of
them — assembly and PInvoke counts come before and after the three you would
expect. Grepping for `Illegal Namespace References = 1` finds nothing; the
quotes are part of the string. The second is not specific to the sandbox: an
ordinary compile error ends in the same `CompileFailed`
(`PugMod.Loader:Loader:LoadScripts:68-75`).

**The ban is on the reference, not on the capability.** Your code may not
mention `System.IO`, but the *ability* to touch files is not withdrawn — it is
relocated. What a method in an assembly that is already loaded and trusted (the
game DLLs, `0Harmony.dll`, CoreLib) does internally costs zero references in
your own IL. Its *signature* is another matter: the return and parameter types
of every method you call are checked as if you had written them
(`Trivial.CodeSecurity:MethodReferenceChecker:SecurityCheckCode:3-7`), so a
trusted method that hands back a type from a denied namespace costs you that
namespace and type. **Measured** 2026-10-16 on 1.3.0.6-6e73:
`typeof(string).GetMethods()` on its own reported `System.Reflection` and
`System.Reflection.MethodInfo[]` — one namespace, one type, no member, since
`System.Type` itself is allowed. This is what makes the rest of this chapter
possible: "no `System.IO`" never implies "no runtime config", as long as the API
you call keeps `System.IO` out of its signatures.

## An Editor build succeeding is not evidence

The SDK's `-batchmode` build does **not** enforce the sandbox. Nothing in it runs
the verifier, and the denied types are ordinary BCL types every compile can
see, so banned code compiles perfectly and fails only when the game loads it —
the in-game Roslyn compile succeeds too, and the verification after it is what
rejects the assembly. The probe behind this chapter's measurements, full of
denied references, built cleanly.

**Smoke-test it by launching the game to the main menu** and grepping
`Player.log` for `passed code security verification` versus `failed`. No world
load is needed — the loader runs the check at startup. On a dedicated server,
which has no menu, the same check runs at server start.

There are three independent gates, and passing two says nothing about the
third. Grep for all of them:

| Gate | What it is | Log needle |
|---|---|---|
| Editor compile | The SDK build | `error CS` |
| Sandbox verification | RoslynCSharp security check at load | `failed code security verification`, `CompileFailed` |
| Harmony bind | The loader's auto-`PatchAll` | `patching failed` (the loader's own annotation check) or `failed to patch mod <name>, got exception` (anything Harmony throws, e.g. `ArgumentException: Undefined target method`) |

A mod can clear the first two and silently fail the third, and how much of it is
left depends on which needle the log shows. `patching failed` means the loader's
annotation check refused before Harmony ran, so none of its hooks exist. `failed
to patch mod <name>, got exception` means Harmony threw partway through
`PatchAll`, which works class by class — the patch classes it reached before the
throw stay bound, as recorded in `caveling-divining-rod`, whose `Undefined
target method` "aborted PatchAll for every patch class after it". Either way,
what does not depend on Harmony — the `IMod` lifecycle, the mod's ECS systems —
still runs. The binding rules for that third gate live in [Harmony and ECS](harmony-and-ecs.md); what
a failed load does to *other* mods is in [troubleshooting](troubleshooting.md).

**One change shape is nearly exempt: a fix that only deletes call sites.** The
verification fires on *references* present in the assembly, so removing a call
cannot add one — the change still clears the sandbox gate, and that is the case
where skipping the launch-and-grep cycle is justified rather than optimistic.
Deleting a *declaration* is not the same shape: removing your own `Path` helper
while a `using System.IO;` stands in the file rebinds every `Path.Combine` to
`System.IO.Path`, a banned reference created by a deletion.

## What is banned

**The list is data, not folklore.** The verifier reads
`Resources/Assets/Resources/RoslynCSharpSettings.asset` from the game's own
resources, and every group in it carries `defaultBehaviour: 0` — `Allow`. What
follows is that file's four deny lists, complete as of 1.3.0.6-6e73; the
dedicated server's `resources.assets` carries the same deny strings. Two more
settings in the file restrict a mod: `allowPInvoke: 0`, which the verifier
enforces by reporting any method declared with `[DllImport]`
(`Trivial.CodeSecurity:MethodChecker:SecurityCheckCode:15`), and
`allowUnsafeCode: 0`, which reaches the compiler.

**The lists are not a lookup table, though.** A symbol that is listed nowhere
fails when its namespace is denied (the next paragraph), and — the reverse, and
less obvious — a listed *member* does not fail on its own account. The member
check computes the deny-list answer and then, whenever the member list's default
is `Allow`, replaces it with the verdict on the member's declaring type
(`Trivial.CodeSecurity:CodeSecurityRestrictions:IsMemberReferenceAllowed:14-17`).
`UnityEngine.Application` and `System.Type` are allowed, so the Members row
below denies nothing by itself: **measured** 2026-10-16 on 1.3.0.6-6e73, a probe
referencing `Application.Quit()` was not reported. `Type.InvokeMember` should
still fail, by the code rather than by measurement — through the `BindingFlags`
and `Binder` in its own signature. So a failure on something not listed here is
not evidence that the game changed — read the namespace rule first.

| Group | Denied |
|---|---|
| Namespaces (7) | `System.IO.*`, `System.Diagnostics.*`, `System.Net.*`, `System.Runtime.InteropServices.*`, `System.Reflection.*`, `RoslynCSharp.*`, `Pug.Platform.*` |
| Types (16) | `System.AppDomain`, and fifteen `HarmonyLib.*` types: `AccessTools`, `Code`, `FastAccess`, `FastInvokeHandler`, `Harmony`, `MethodInvoker`, `Patch`, `PatchClassProcessor`, `Patches`, `PatchInfo`, `PatchProcessor`, `ReversePatcher`, `SetterHandler`, `Transpilers`, `Traverse` |
| Assemblies (7) | `UnityEditor.dll`, `Mono.Cecil.dll`, and the five `MonoMod.*` assemblies |
| Members (2) | `UnityEngine.Application.Quit`, `System.Type.InvokeMember` — listed, but not enforced on their own (above) |

Two consequences the list makes obvious and a bisection would not:

- **Whole namespaces, not selected types.** `System.Diagnostics.*` takes
  `Stopwatch`, `StackTrace` and `Debug` with it, not just `Process` — which
  matters to anyone trying to time their own scan. `System.Reflection.*` is why
  an innocent `ex.GetType().Name` fails: `Type.Name` *is* `MemberInfo.Name`.
- **Harmony's attribute surface is untouched.** Fifteen `HarmonyLib` types are
  denied, and `[HarmonyPatch]`, `[HarmonyPrefix]` and friends are not among them
  — nor would it matter, since the verifier reads no attributes at all. What the
  list closes is the programmatic entry points it names: `Harmony`,
  `PatchProcessor`, `PatchClassProcessor` and the rest. The loader has an open
  one of its own, `API.ModLoader.ApplyHarmonyPatch(modId, type)`, which patches
  a single patch class chosen at runtime
  (`Pug.Other:ModAPIModLoader:ApplyHarmonyPatch:1`) through the same annotation
  check as the automatic `PatchAll` (`PugMod.Loader:Loader:HarmonyPatchType:1`);
  CoreLib and StoragePlus both use it and pass verification.

**Read the count as one finding, not three — where a namespace is what trips.**
A member access whose declaring type falls under one of the seven denied
*namespaces* produces `1 namespace + 1 type + 1 member`: the namespace, the
declaring type it falls through to, and the member itself, all of one symbol.
`Type.Name` does this on its own, verified. A denied *type* counts differently —
`HarmonyLib` and `System` are allowed namespaces, so the namespace counter stays
at 0 — which is worth knowing before reading a triplet as a rule. A call to an
allowed member whose *signature* names a denied type counts a third way, `1/1/0`:
that is the `GetMethods()` measurement above.

**The counters count distinct symbols, not occurrences** — the type and member
counters per distinct reference, the namespace counter per distinct namespace,
so `File.ReadAllText` plus `MemoryStream` report one namespace against two
types. The numbers therefore bound how many distinct denied symbols there are
and say nothing about how many places to edit: twenty `Type.Name` calls still
report `1/1/1`. The occurrence block below the summary is what lists them, and
it is where to start rather than the deny lists. It names the method and the IL
instruction, and for a reference inside a method body it appends the source
file, line and column — which is usually enough to go straight to the
expression. Two caveats on that location: the file is the loader's extracted
copy under `ModLoader/`, not your repository (and on a dedicated server, a fresh
GUID directory per launch), and a reference that carries no instruction — a
denied type in a field, property or local declaration — reports the file alone.

The following were observed to fail and are *not* on the list. In neither case
has the named expression been shown to be what tripped the count — the first was
never isolated, the second was isolated and passed — so what tripped either
assembly is **unverified**. Bisect the rest of the failing assembly, not the
deny list:

| Observed failure | What it resolves to |
|---|---|
| `Manager.saves.X()` on `SaveManager` | `SaveManager` is on no deny list, and by the code the call cannot be what fails: `GetWorldId()` returns an `int` (`Pug.Other:SaveManager:GetWorldId:1`), so neither its declaring type nor its signature names anything denied. One mod's load record shows `Manager.saves.GetWorldId()` failing verification, yet `faster-talents` calls `Manager.saves.GetSkillValue(skillId)` and `Manager.saves.GetSkillTalentTreesPoints(skillTreeID)` — instance methods reached through the same static property, inside Harmony prefixes — and passes on 1.3.0.6-6e73, and the published ConveyorTunnelMod calls `Manager.saves.GetWorldId()` itself (not loaded on this machine, so not measured). |
| Some game-side ECS component reads | A mod's assembly reported 1 namespace + 1 type + 1 member illegal ref alongside an `em.HasComponent<CharacterGuidCD>(entity)` + `GetComponentData<CharacterGuidCD>(entity)` + `Hash128` expression — but that exact expression, isolated in an assembly of its own, **measured** 2026-09-03 (1.2.1.5-8be0) to pass verification, so the count belonged to something else the assembly referenced, not to this expression. |

`System.IO.*` deserves its own note because the namespace ban reaches further
than the name suggests: purely in-memory types go with it — `MemoryStream`,
`BinaryWriter`, `BinaryReader`, `EndOfStreamException`. `BinaryWriter`-style
framing has to be hand-rolled; string-to-`byte[]` does not, since
`System.Text.Encoding` is legal.

**`AccessTools` is denied outright** — it sits on the type list beside
`Traverse`, so the reflection-wrapper route into private fields is closed by
both of its entrances. The legal route below reaches private members with
neither — but not in every assembly, as `AccessTools` would: it refuses any type
outside five assembly-name prefixes, which leaves out CoreLib, the BCL and some
of the game's own assemblies ([below](#reaching-a-private-member-resolving-it-is-only-half-the-job)).

**Not banned, contrary to expectation: `System.Security.Cryptography`.** It
looks like exactly the BCL surface the sandbox rejects, and it is not: CoreLib
uses `MD5.Create()` and `ComputeHash` in its own sandboxed source
(`skipSafetyChecks: false`) and passes verification. That does not make it the
right tool for the job that tempts you into it — hashing to skip a redundant
write — but the reason is cost and allocation rather than legality; see [writing in lockstep with the game's save](persistence.md#writing-in-lockstep-with-the-games-save).

**Trap: `Type.Name` is not a string operation.** A diagnostic log line is an
easy way to trip the sandbox by accident. Four ways around it:

- `ex.GetType().GetNameChecked()` — the SDK's extension returns `type.Name`
  from inside its own trusted assembly
  (`PugMod.SDK.Runtime:ModAPIExtensions:GetNameChecked(Type):1-3`), so it is a
  drop-in replacement for the expression that trips.
- Catch the typed exception and write the type name as a string literal: `catch
  (NullReferenceException ex) { Debug.Log("NullReferenceException: " +
  ex.Message); }`
- Log only `ex.Message` and drop the type entirely.
- For a member rather than a type, use `GetMembersChecked()` and the
  `MemberInfo` overload of `GetNameChecked()` (`PugMod.SDK.Runtime`) — the
  reflection happens inside that trusted assembly, so it costs no reference of
  your own. A reflective lookup written as
  `typeof(UIScrollWindow).GetMembersChecked().FirstOrDefault(x =>
  x.GetNameChecked() == "UpdateScrollHeight")` passes cleanly.

### Reaching a private member: resolving it is only half the job

The lookup above finds a private member. It does not let you *use* it — and
that gap is worth stating plainly, because stopping there makes the sandbox look
far more restrictive than it is, and sends people to `skipSafetyChecks: true`
for something that is perfectly legal.

The other half is the SDK's own reflection surface:

| Call | Extension form | Purpose |
|---|---|---|
| `API.Reflection.Invoke(member, target, params…)` | `member.InvokeChecked(target, …)` | call a private method |
| `API.Reflection.GetValue(member, target)` | `member.GetValueChecked(target)` | read a private field |
| `API.Reflection.SetValue(member, target, value)` | `member.SetValueChecked(target, value)` | write a private field |

Note the type: these take a **`PugMod.MemberInfo`**, not a
`System.Reflection.MemberInfo` — which is exactly what `GetMembersChecked()`
hands you, so the two halves fit together directly.

```csharp
// resolve once, cache in a static — the lookup is not free
static readonly MemberInfo UpdateScrollHeight = typeof(UIScrollWindow)
    .GetMembersChecked()
    .FirstOrDefault(m => m.GetNameChecked() == "UpdateScrollHeight");

// call it
API.Reflection.Invoke(UpdateScrollHeight, scrollWindow);
```

**Both halves are SDK surface, so the whole recipe costs no dependency at all.**
`GetNameChecked` and `GetMembersChecked` are extension methods in
`PugMod.SDK.Runtime`
(`PugMod.SDK.Runtime:ModAPIExtensions:GetNameChecked(Type):1`,
`PugMod.SDK.Runtime:ModAPIExtensions:GetMembersChecked:1`) alongside
`API.Reflection` itself — CoreLib is not involved anywhere in this.

**A PRIVATE member is reported only by the type that declares it, so aim the
lookup there and not at a subclass you happen to hold.** `GetMembersChecked`
calls `type.GetMembers(Instance | Static | Public | NonPublic)`
(`PugMod.SDK.Runtime:ModAPIExtensions:GetMembersChecked:3`) with no
`DeclaredOnly` — inherited *public* and *protected* instance members come back
from a subclass just fine, which is what makes the private case easy to miss.
Inherited *static* members share the private case's fate, public ones included,
because the flags carry no `FlattenHierarchy`. Reading
`RadicalMenuOptionTextInput.currentCharIndex` from a row class deriving from it
means `typeof(RadicalMenuOptionTextInput)`, not `typeof(YourRow)`. Get it wrong
and `FirstOrDefault` hands back `null`, indistinguishable from a game update
having renamed the member — so null-check a cached lookup and say in the message
which member of which type was not found, because the null itself cannot tell
you why.

**The permission gate is the same one that decides Harmony patch targets** —
`InvokeChecker.CheckType`, described under [Harmony attributes are exempt](#harmony-attributes-are-exempt--hook-bodies-are-not):
the five assembly-name prefixes, `[DisallowPatching]`, and `PugMod.Loader`
itself. Four things differ on this route and are worth knowing before relying
on it:

- **It applies to every mod.** The patch-time check runs only for a mod with
  `skipSafetyChecks: false`; `ModAPIReflection` calls `CheckType` with no such
  condition (`Pug.Other:ModAPIReflection:Invoke:4`), so even a mod that disabled
  the sandbox is held to the five prefixes on this route.
- **It fires per call, not once before `PatchAll`.** `ModAPIReflection` holds
  its own `InvokeChecker` (`Pug.Other:ModAPIReflection:_checker:1`), separate
  from the loader's, and `Invoke` / `GetValue` / `SetValue` each run `CheckType`
  on entry (`PugMod.Loader:InvokeChecker:CheckType:1`). So the patch path's
  all-or-nothing rejection has no counterpart here: one refused type costs you
  that one call.
- **A refusal throws rather than returning `false`** —
  `InvalidOperationException` at your call site (`Pug.Other:ModAPIReflection:GetValue:6` for
  `GetValue`). A `catch` cannot identify it as a refusal, because those three
  methods throw the same type for shape mistakes too: `Invoke` on a non-method,
  `GetValue`/`SetValue` on a member that is neither field nor property,
  `SetValue` on a read-only one. Catching for a *different* reason is legitimate
  — a member that kept its name and changed its *kind* resolves non-null and
  throws this same exception at read time, and a caller that must not lose the
  user's input has no narrower channel to listen on. A member that changed its
  *type* does not throw here at all: `GetValue` hands back the new value boxed,
  and the failure surfaces at your own cast as `InvalidCastException`, or from
  `SetValue` as an `ArgumentException` — neither of which that `catch` sees.
- **A refusal is `Debug.Log`, not a warning, in one of three strings.** `Trying
  to patch disallowed type {type}` (`PugMod.Loader:InvokeChecker:CheckType:10`),
  `Patching mod loading not allowed`
  (`PugMod.Loader:InvokeChecker:CheckType:16`), `Trying to patch type {type}
  from unknown assembly` (`PugMod.Loader:InvokeChecker:CheckType:39`). Each
  finds only the refusals of its own cause — for a CoreLib or BCL target that is
  the last one. The needle that covers every refusal on this route is the
  exception's own message, `Not allowed to access <member>`
  (`Pug.Other:ModAPIReflection:Invoke:6`), wherever the exception reaches the log.

**The prefix test does not separate the game from mods, and reading it that way
is the trap.** Classifying the 132 assemblies of the 1.3.0.6-6e73 decompile
against the five prefixes gives 42 admitted and 90 refused (`PugMod.Loader`
matches `Pug` and is refused on its own rule), and the refused side is shipped game
code: `WorldGen`, `Interaction`, `ObjectLookup`, `ScriptableData`, `Affixes`,
`Assembly-CSharp` — and `0Harmony`. What it reliably reaches is `Pug*` and
`Unity*`. That mods fall outside is a consequence of naming, not of design: the
check has no concept of a mod, a mod's compiled assembly is named `metadata.name
+ ".dll"` verbatim (`PugMod.Loader:Loader:LoadScripts:48`, the Roslyn path), and
CoreLib is refused because its manifest name is `CoreLib`. Nothing would stop a
mod that named itself `Pug…`.

**The CoreLib case is measured, not only computed, and what it shows is that the
two gates fail at different moments.** A probe read
`AcceptableValueList<T>.AcceptableValues` — a *public* property, so nothing about
it is private-member territory — through `API.Reflection` in a loaded mod. The
mod compiled and loaded (`Successfully compiled … safetyCheck=True`): the
sandbox permits the source, because `PugMod.MemberInfo` and `API.Reflection` are
on none of its deny lists. The refusal came at the call, as
`InvalidOperationException: Not allowed to access AcceptableValues`, with
`InvokeChecker`'s own line beside it in the log — ``Trying to patch type
CoreLib.Data.Configuration.AcceptableValueList`1[System.Int32] from unknown
assembly``. So a build that loads cleanly proves nothing about whether a
reflection call in it will work.

The same run also settles what the obstacle is *not*. A non-generic control on a
CoreLib type (`AcceptableValueBase.ValueType`) was refused identically, while
`UnityEngine.Vector3.x` read fine — so the type parameter is irrelevant and the
declaring type's assembly is the whole test, exactly as `CheckType` reads. The
consequence for a mod that consumes CoreLib: its config API is reachable by
ordinary calls and closed to reflection, and a value only a generic property
exposes is reached by naming the type argument in a pattern-match — or, where
the text is enough, from the non-generic `ToDescriptionString()` every
acceptable-value class implements. `ModSettingsMenu`'s
`ForeignConfigDiscovery.ReadExactValues`, on its unreleased v2 branch, does the
first over most of the types `TomlTypeConverter` can convert — `bool` and enums
excepted — and keeps the second for whatever that cascade does not name.

**Cost, with the caveat that matters more than the numbers.** One process, one
Wine host, one mod set, on 1.2.1.5: **3.57 µs** for a cached-`MemberInfo` read,
and **0.404 ms** for the first such call in that session. What the 0.404 ms
contains is **unverified** — the candidates are the `GetMembersChecked` scan behind
a `beforefieldinit` static, and `InvokeChecker.LazyInit`'s one-off walk over
every type of every loaded assembly (`PugMod.Loader:InvokeChecker:LazyInit:1-8`)
— and on this machine CoreLib already reaches `API.Reflection` during mod load
for keybind registration, so a later caller likely finds that walk already paid.
Treat the figures as an order of magnitude: a read per keystroke or per click
needs no budgeting, and the published MapMarkersPlus does one per frame in a
`LateUpdate` (`API.Reflection.Invoke` on a scroll window) without a reported
problem. The uncached *lookup* is the half to keep out of a hot
path regardless — `GetMembersChecked` allocates two arrays plus one wrapper
object per member on every call
(`PugMod.SDK.Runtime:ModAPIExtensions:GetMembersChecked:3-9`,
`PugMod.SDK.Runtime:MemberInfo:operator MemberInfo:1`), which is why the recipe
above caches it in a `static readonly`.

## What is not banned

Each of these passes verification — by a live load where one is named, and
otherwise by the deny lists and the namespace rule above:

- **`PugMod.API.ConfigFilesystem`** — the loader's own file API. See [storing configuration and state](persistence.md).
- **Attributes that name banned types, Harmony's included** — the verifier reads
  no attributes, which the `System.Diagnostics` probe [above](#what-the-verification-checks) measured. See the
  next section.
- **`Newtonsoft.Json.*`** — a trusted precompiled library, legal to call even
  though it uses `System.IO` internally — but only reachable when the manifest
  sets `accessesExtraAssemblies`. It is not among the references the in-game
  compile gets by default; that flag is what adds every assembly the game had
  loaded at start (`PugMod.Loader:Loader:LoadScripts:10-25`).
- **`System.Text` — `Encoding`, `UTF8Encoding` and `StringBuilder`.** CoreLib
  compiles all three under the sandbox: `Encoding.UTF8.GetBytes` / `GetString`
  wrapping its `API.ConfigFilesystem` calls, and `new UTF8Encoding(false)` plus
  `StringBuilder` in its TOML writer. Its manifest carries `skipSafetyChecks:
  false`, so it goes through exactly the check your mod does, and its assembly
  logs `has passed code security verification`.
- **`Convert.ToBase64String` / `Convert.FromBase64String`** — these live in
  `System`, not `System.IO`.
- **`UnityEngine.PlayerPrefs`** — Unity-native persistence, sandbox-safe.
- **Pug's ECS surface and most of `Unity.Entities` / `Unity.Collections`** —
  `Entity.Null`, `World.All`, `World.DefaultGameObjectInjectionWorld`,
  `EntityManager.CreateEntityQuery`, `ToEntityArray`, `ToComponentDataArray`,
  `HasBuffer<T>` / `GetBuffer<T>`. **ECS writes are sandbox-legal too**, not
  just reads. The query patterns and the performance rules that govern them are
  in [Harmony and ECS](harmony-and-ecs.md).
- **`UnityEngine.JsonUtility`** — the deny lists never touch `JsonUtility`:
  among Members they name only `UnityEngine.Application.Quit` and
  `System.Type.InvokeMember`. The loader itself serialises with it:
  `JsonUtility.ToJson` in `ModAPIConfig.Set` (`Pug.Other:ModAPIConfig:Set:20`).
- **`Object.FindFirstObjectByType<T>()`** and the `GetComponentsInChildren`
  overloads — plain `UnityEngine.CoreModule` API, on none of the four lists.
  Worth stating because the name suggests otherwise: the method resolves types
  at runtime, but **the verification inspects the references your assembly
  declares**, not what a trusted assembly does internally. That is the same
  reason `Newtonsoft.Json` and `API.ConfigFilesystem` are fine despite using
  `System.IO`.
- **`System.Enum.GetValues` / `GetNames`** — same reasoning, and confirmed by
  live loads with `skipSafetyChecks: 0`: the published Player Coordinates HUD
  calls `System.Enum.GetValues`, and a dev build of Mod Settings Menu's
  unreleased v2 calls `System.Enum.GetNames(t)` in its foreign-config
  discovery; both pass on 1.3.0.6-6e73. Useful for deriving a settings
  dropdown's options from the enum instead of a hand-maintained array.
- **A sprite built at runtime** — `Sprite.Create` over `Texture2D.whiteTexture`,
  which gives a solid fill without shipping an image for it. Both are plain
  `UnityEngine.CoreModule` API. A dev build of Mod Settings Menu that calls them
  with `skipSafetyChecks: 0` logged `has passed code security verification` on
  a client and on a dedicated server, on 1.3.0.6-6e73.

## Harmony attributes are exempt — hook bodies are not

`[HarmonyPatch(typeof(SaveManager), nameof(SaveManager.SetObjectAsDiscovered))]`
loads cleanly, but proves nothing on its own — `SaveManager` is on no deny
list to begin with. The exemption is a property of the verifier, not of Harmony
or of this example: no checker reads custom attributes, so a type named only in
an attribute argument is never counted, whoever's attribute it is — measured
with a `System.Diagnostics` attribute [above](#what-the-verification-checks).
No live example with a Harmony attribute naming a type that IS on the deny list
exists, though: neither `System.AppDomain` nor the fifteen `HarmonyLib.*`
internals — the whole of the type deny list — is a patch target anyone would
plausibly write, and none of them lives in an assembly the patch-target check
below admits.

The verifier is not the only gate a patch attribute meets. For a mod with
`skipSafetyChecks: false`, the loader also reads the patch attributes before it
runs `PatchAll` (`PugMod.Loader:HarmonyBootstrap:Patch(string, Assembly, …):3`),
and `InvokeChecker.CheckType` accepts a patch target only if its assembly name
starts with `Pug`, `Unity`, `SpriteInstancing`, `I2` or `Rewired`, the type is
not marked `[DisallowPatching]`, and it does not live in `PugMod.Loader` itself.
BCL types, `modio.*`, `Newtonsoft.Json` and CoreLib are all outside those
prefixes. A refusal there is **all-or-nothing**: one disallowed target the check
finds makes it return false for the whole assembly, `PatchAll` never runs, and
*none* of the mod's patches bind. For a target outside the prefixes the log says
`Trying to patch type X from unknown assembly`; the other two causes have
strings of their own, listed [above](#reaching-a-private-member-resolving-it-is-only-half-the-job).

**Hooking a method is not a way around `Manager.saves`.** Until 2026-10-16 this
section recommended hooking the method instead of calling `Manager.saves.X()`,
and warned that calling it from inside a postfix failed "just the same". Both
rested on the observation in [what is banned](#what-is-banned) that such a call fails verification,
and that observation does not survive the code or the corpus: `Manager.saves`
passes, inside a Harmony prefix too, in `faster-talents` on 1.3.0.6-6e73. Hook
bodies are verified exactly like any other method, so a call is as legal in one
as anywhere else.

Two patterns for reading game state through a hook remain useful on their own
merits — when the data you need passes through a method you can patch:

**Direct-args.** If the hooked method's parameters already carry what you need,
hook it and read them — you only touch `int`/`string`/value types, so nothing
banned appears in your assembly.
`SaveManager.SetObjectAsDiscovered(ObjectDataCD, bool __result)` gives you the
object ID and the new-or-not flag this way.

**State machine.** When the data lives in another method's scope, hook both and
correlate them with a static flag. To capture the active character GUID, for
example: a postfix on `SaveManager.SetCharacterId(int id)` sets a static
"awaiting" flag, and a postfix on `CharacterData.OnAfterDeserialize` reads the
public `__instance.characterGuid` field and clears it. No banned API is
touched; you read a public field and a value-type argument.

**"Strictly sequential" is the caller's doing, not `SetCharacterId`'s.**
`SetCharacterId` itself triggers no deserialize — `OnAfterDeserialize` only
follows when the specific caller that invoked it goes on to start the game,
which not every one of its call sites does, and — on 1.3.0.6-6e73, the build
checked — only in a process that also hosts the world. Arming the "awaiting"
flag on every call, as above, leaks it across a call with no such decode and
pollutes whichever deserialize comes next. See [correlating private state across two methods](harmony-and-ecs.md#correlating-private-state-across-two-methods)
for which call sites load and which don't, and for gating the flag on the right
one instead of on `SetCharacterId` alone.

## Finding the banned identifier

**The log names the offending member. Grep for it and skip the detective work.**

A failed verification writes **two** separate error entries:

1. the counts summary — the single-quoted, five-counter line shown [above](#what-the-verification-checks)
2. a full occurrence report: for each denied symbol, a header line naming it —
   `Illegal reference to disallowed namespace: System.Reflection`, `… type: …`,
   `… member: …`, or an `Indirect illegal reference via …` variant — followed
   by one tab-indented line per usage site. A usage in a method body reads
   `Referenced in method body: '<Type>.<Method>()' at instruction: '<IL_…>'`;
   other usages name a field, parameter, property or method signature, a type
   definition, or a local variable instead. A known usage carries a tail this
   template used to stop short of: ` in source file: '<path>' at line: 'N',
   column: 'M'`. One site that trips several counters appears once under each
   header — the measured `GetMethods()` call is listed under the namespace and
   again under the type.

The second is not conditional on any setting: `RegisterAssemblyImpl` calls
`GetAllText(reportAllOccurences: true)` with the flag as a hardcoded literal
(`RoslynCSharp:ScriptDomain:RegisterAssemblyImpl:15`), through the same log gate
as the summary. If the counts line reached your `Player.log`, the naming lines
did too.

**Trap: a grep tuned to the summary misses the detail.** The two entries are
separate `Debug.LogError` calls, so Unity puts a stack trace between them — some
forty lines in the measured log — and the detail block scrolls out of a narrow
grep window. Search for **`Illegal reference`** instead: it lands on each
header, and the line after it names the site.

Fall back on these only when the log was truncated or the detail entry is
genuinely absent:

1. **Bisect — and confirm.** Comment out the most recently added external API
   call, rebuild, reload. If verification passes, the edit removed the reference
   — which is not the same as the call having been it, since an edit can take
   more with it than the one expression. This is how
   `Manager.saves.GetWorldId()` came to be blamed for a failure the code says it
   cannot cause ([what is banned](#what-is-banned)). Confirm a suspect by putting it alone in an
   assembly of its own.
2. **Read the compiled references yourself.** The in-game compile happens in
   memory
   (`RoslynCSharp.Compiler:RoslynCSharpCompiler:CompileFromSyntaxTree:27`):
   `ModLoader/<Mod>/` holds only the extracted sources, no DLL. The Editor
   build's DLL is the nearest substitute — a separate compile of the same
   sources, which the loader partly rewrites before its own, so a match there is
   a lead rather than proof. See [reverse engineering](reverse-engineering.md).
