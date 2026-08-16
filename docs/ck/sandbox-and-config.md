# The sandbox and mod configuration

A Core Keeper mod does not ship a compiled assembly. It ships C# sources
(`Scripts/*.cs`) that the loader compiles with RoslynCSharp at game start, and
then puts through a security verification before it is allowed to run. That
verification is default-deny: whole namespaces and individual class symbols are
off limits, and a violation kills the mod at load time — after the Editor build
already reported success. This chapter tells you what the sandbox actually
forbids, why that is narrower than it looks, and the three ways a sandboxed mod
stores settings and state anyway.

## What the verification checks

The check runs over **the mod's own Roslyn-compiled IL** and counts references
to banned namespaces, types and members. It does not care what those references
would have done at runtime; it only cares that the symbol appears in your
assembly. When it trips, `Player.log` shows:

```text
Assembly 'X' has failed code security verification.
  Illegal Namespace References = N,
  Illegal Type References = M,
  Illegal Member References = K
mod X load error: CompileFailed
```

**The ban is on the reference, not on the capability.** Your code may not
mention `System.IO`, but the *ability* to touch files is not withdrawn — it is
relocated. Every call you make into an assembly that is already loaded and
trusted (the game DLLs, `0Harmony.dll`, `Newtonsoft.Json`, CoreLib) costs zero
references in your own IL, no matter what that assembly does internally. This
single fact is what makes the rest of this chapter possible: "no `System.IO`"
never implies "no runtime config".

## An Editor build succeeding is not evidence

The SDK's `-batchmode` build does **not** enforce the sandbox. It compiles
against `precompiledReferences` that include `System.IO.dll` and friends, so
banned code compiles perfectly and fails only when the game loads it.

**Smoke-test it by launching the game to the main menu** and grepping
`Player.log` for `passed code security verification` versus `failed`. No world
load is needed — the loader runs the check at startup.

There are three independent gates, and passing two says nothing about the
third. Grep for all of them:

| Gate | What it is | Log needle |
|---|---|---|
| Editor compile | The SDK build | `error CS` |
| Sandbox verification | RoslynCSharp security check at load | `failed code security verification`, `CompileFailed` |
| Harmony bind | The loader's auto-`PatchAll` | `patching failed` |

A mod can clear the first two and silently fail the third, in which case none
of its hooks exist and it simply does nothing. The binding rules for that third
gate live in [Harmony and ECS](harmony-and-ecs.md); what a failed load does to
*other* mods is in [troubleshooting](troubleshooting.md).

## What is banned

Every entry below was verified by an actual failed load.

| Banned | Notes |
|---|---|
| The whole `System.IO.*` namespace | Including purely in-memory types: `MemoryStream`, `BinaryWriter`, `BinaryReader`, `EndOfStreamException`. Any byte encoding you need must be hand-rolled. |
| `Manager.saves.X()` — the `SaveManager` instance-access path | The entire class as an access surface, even trivial getters such as `GetWorldId()` that just return a cached int. `SaveManager` aggregates filesystem-touching methods, and the whole class symbol is banned. |
| `System.Diagnostics.Process` | Process spawning. |
| `System.Reflection.Emit.*` | Runtime code generation. |
| `HarmonyLib.Traverse` (and, by the same rule, `AccessTools.Field` / `Property`) | Banned even though it lives in the trusted `0Harmony.dll` — the reflection *wrapper class* is the banned symbol. `Traverse.Create(x).Field("y").GetValue<T>()` produces 1 illegal type ref plus 3 illegal member refs. Consequence: no private-field reflection from mod code. |
| `System.Reflection.MemberInfo.get_Name()` — and anything that resolves to it through inheritance | `Type.Name` *is* `MemberInfo.Name`, so an innocent `ex.GetType().Name` yields 1 namespace + 1 type + 1 member illegal ref and fails the load. |
| Some game-side ECS component reads | `em.HasComponent<CharacterGuidCD>(entity)` + `GetComponentData<CharacterGuidCD>(entity)` + `Hash128` together produced 1 namespace + 1 type + 1 member illegal ref. The exact blocked subset is not mapped — bisect when you hit it. |

**Trap: `Type.Name` is not a string operation.** The most common way to trip
the sandbox by accident is a diagnostic log line. Three ways around it:

- Catch the typed exception and write the type name as a string literal:
  `catch (NullReferenceException ex) { Debug.Log("NullReferenceException: " + ex.Message); }`
- Log only `ex.Message` and drop the type entirely.
- For non-exception cases, use CoreLib's `GetMembersChecked()` /
  `GetNameChecked()` extension methods — they live in the trusted CoreLib DLL
  and therefore bypass the sandbox. A reflective lookup written as
  `typeof(UIScrollWindow).GetMembersChecked().FirstOrDefault(x => x.GetNameChecked() == "_scrollable")`
  passes cleanly.

### Reaching a private member: resolving it is only half the job

The lookup above finds a private member. It does not let you *use* it — and
that gap is worth stating plainly, because stopping there makes the sandbox look
far more restrictive than it is, and sends people to `skipSafetyChecks: true`
for something that is perfectly legal.

The other half is the SDK's own reflection surface:

| Call | Purpose |
|---|---|
| `PugMod.API.Reflection.Invoke(member, target)` | call a private method |
| `PugMod.API.Reflection.SetValue(member, target, value)` | write a private field |

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

`API.Reflection` is SDK surface and costs no dependency. The `GetMembersChecked`
half comes from CoreLib — so the *resolution* step is what pulls that dependency
in, not the invocation.

## What is not banned

Verified by passing live loads:

- **`PugMod.API.ConfigFilesystem`** — the loader's own file API. See below.
- **Harmony attributes that name banned types.** See the next section.
- **`Newtonsoft.Json.*`** — trusted precompiled library; usable from mod code
  even though it uses `System.IO` internally.
- **`Convert.ToBase64String` / `Convert.FromBase64String`** — these live in
  `System`, not `System.IO`.
- **`UnityEngine.PlayerPrefs`** — Unity-native persistence, sandbox-safe.
- **Pug's ECS surface and most of `Unity.Entities` / `Unity.Collections`** —
  `Entity.Null`, `World.All`, `World.DefaultGameObjectInjectionWorld`,
  `EntityManager.CreateEntityQuery`, `ToEntityArray`, `ToComponentDataArray`,
  `HasBuffer<T>` / `GetBuffer<T>`. **ECS writes are sandbox-legal too**, not
  just reads. The query patterns and the performance rules that govern them are
  in [Harmony and ECS](harmony-and-ecs.md).

`Encoding`, `JsonUtility` and `StringBuilder` have not been verified either
way. Where existing mods needed to serialise, they hand-packed bytes rather
than find out.

## Harmony attributes are exempt — hook bodies are not

`[HarmonyPatch(typeof(SaveManager), nameof(SaveManager.SetObjectAsDiscovered))]`
loads cleanly, even though `SaveManager` is a banned access surface. The patch
attribute is a special-cased compile-time-only reference: the reflection that
resolves it happens inside the precompiled, trusted `0Harmony.dll`, not in your
IL.

**This unlocks every banned class's API.** Hook the method instead of calling
it; your code sees the arguments and the result, while the member access itself
happens inside trusted code.

**But the exemption stops at the attribute.** Calling `Manager.saves.X()` from
*inside* a Harmony postfix is still a banned reference and still fails
verification. Only the attribute is free.

Two patterns follow from this:

**Direct-args.** If the banned method's parameters already carry what you need,
hook it and read them — you only touch `int`/`string`/value types, so nothing
banned appears in your assembly. `SaveManager.SetObjectAsDiscovered(ObjectDataCD, bool __result)`
gives you the object ID and the new-or-not flag this way.

**State machine.** When the data lives in another method's scope, hook both and
correlate them with a static flag. To capture the active character GUID, for
example: a postfix on `SaveManager.SetCharacterId(int id)` sets a static
"awaiting" flag, and a postfix on `CharacterData.OnAfterDeserialize` reads the
public `__instance.characterGuid` field and clears it. This works because CK's
path is strictly sequential — `SetCharacterId` → file read → JSON overwrite →
`OnAfterDeserialize` on that specific character. No banned API is touched; you
read a public field and a value-type argument.

## Finding the banned identifier

The verification log reliably gives you **counts** — `Illegal Namespace/Type/
Member References = N`. Read those first: they tell you which *category* you
violated, which usually narrows it to one or two candidate calls.

Whether it ever also names the offending member is unresolved. A second-hand
account describes lines of the form `Referenced in method body: '<Type>.<Method>()'`
with an `IL_` instruction, but that record is schematic rather than a captured
log, so it may reflect the underlying verifier's documented format rather than
what Core Keeper actually prints. **Check your own log for such a line before
assuming you have to work without one** — if it is there, it answers the
question outright and the strategies below are unnecessary.

Two strategies otherwise, in the order that pays off:

1. **Bisect.** Comment out the most recently added external API call, rebuild,
   reload. If verification passes, that call was it. This is how the
   `Manager.saves.GetWorldId()` ban was found, and it is nearly always faster
   than the alternative.
2. **Decompile** the mod's freshly built DLL from `ModLoader/<Mod>/` and match
   its external type references against the reported counts. See
   [reverse engineering](reverse-engineering.md).

## Storing configuration: three routes

In order of preference.

### 1. `API.ConfigFilesystem` — the default answer

`PugMod.API.ConfigFilesystem` is the loader's own file API, implemented in the
trusted `PugMod.SDK.Runtime.dll`. The real I/O happens inside that DLL, so a
call to it is sandbox-free. It is the right answer for anything a `config.json`
would hold, it needs no dependency, and it is **initialised before any mod's
`EarlyInit`** — so you can read your settings at the earliest point of the
[IMod lifecycle](mod-anatomy.md).

| Member | Signature |
|---|---|
| `Read` | `byte[] Read(string path)` |
| `Write` | `void Write(string path, byte[] data)` |
| `FileExists` | `bool FileExists(string path)` |
| `DirectoryExists` | `bool DirectoryExists(string path)` |
| `CreateDirectory` | `void CreateDirectory(string path)` |
| `Delete` | `void Delete(string path)` |
| `GetFiles` | enumerate a directory |

Paths are relative to a per-mod root:

```text
…/LocalLow/Pugstorm/Core Keeper/<platform>/<user-id>/mods/<ModName>/
```

**Trap: `Write` does not create missing directories.** There is no `mkdir -p`
behaviour — a first-run `Write` into a mod directory that does not exist yet
throws `Could not find a part of the path …`. Call
`CreateDirectory("<ModName>")` before the first write.

The API is `byte[]` in and `byte[]` out, which means you serialise yourself. A
line-oriented format (`id:count;`) round-tripped through `(byte)char` /
`(char)byte` loops is verified to work; that avoids leaning on the
sandbox-unverified `Encoding` and `JsonUtility`.

That this is genuinely sufficient is not theory: CoreLib itself is a sandboxed
source mod (`skipSafetyChecks: false`) with **zero** `System.IO` references,
and it persists `CoreLib.cfg` and `KeyBindsActions.json` entirely through this
API.

There is also **`API.Config`**, a typed key-value store
(`Get` / `Set` / `Register<T>`) for simple scalar settings such as a tunable
radius, when you do not want to own a file format at all.

### 2. CoreLib's `ConfigFile` — typed entries, at a price

CoreLib's `ConfigFile` sits on top of the same `API.ConfigFilesystem` and adds
typed entries, defaults, `AcceptableValueRange` constraints and a TOML-ish
`.cfg` on disk. You buy that with a **hard CoreLib dependency**, which your mod
must declare in its ModBuilderSettings `.asset` and which propagates to your
mod.io listing — see [mod anatomy](mod-anatomy.md) and
[publishing](../publishing.md).

Take this route when the typed-entry ergonomics are worth the dependency, not
because you assume route 1 cannot do it.

### 3. `skipSafetyChecks: true` — last resort

Setting `skipSafetyChecks: true` in the ModBuilderSettings `.asset` disables
the verification entirely and gives you raw `System.IO`. It is for what the
first two routes genuinely cannot express.

Two costs: you lose the guarantee that your mod is inspectable-by-construction,
and the flag **feeds a derived mod.io tag** — the `Access Type` tag on your
published listing is computed from it, so flipping the flag re-tags the mod on
the next publish. See [publishing](../publishing.md).

## Writing in lockstep with the game's save

For per-character mod data, do not invent your own save moment. Harmony-postfix
**`SaveManager.WriteCharacter(int saveId)`** — CK's real character-file write
(`characterFiles[saveId].Write(EncodeJson(...))`). It fires on autosave *and*
on "Save & Quit"; the no-argument `WriteCharacter()` overload delegates to it.
`SaveManager` is a banned access surface but a perfectly patchable one, because
the patch attribute is exempt.

The symmetric load point is `CharacterData.OnAfterDeserialize`.

**Trap: do not gate your save on a return-to-menu signal.** Hooking
`SetCharacterId(-1)` and saving there looks equivalent and is not — a normal
"Save & Quit" does not reliably call it. The file simply never appears, with no
error and no log line: silent data loss. Keep a `Shutdown()` save and a
character-switch save as cheap backstops, but let `WriteCharacter` be the
trigger.

Saving in lockstep rather than ahead of CK also avoids a post-crash desync
where the game reverts the character to an older state while your file is
newer.

## The `.pugbackup` sibling — a free before/after diff

Every `ConfigFilesystem.Write` leaves a `<file>.pugbackup` next to the live
file holding the **previous** version. This is observed for every file under
`mods/<Mod>/` — configs, ledgers, throwaway `.bin` files alike — and the
backup's mtime always trails the live file's by exactly one write.

**This is the first thing to look at for any "my persisted state lost
entries" report.** It needs no new build, no diagnostic flag and no
reproduction: parse the live file and the `.pugbackup`, diff them, and the set
of vanished entries usually names the culprit outright. In one real case a
ledger had lost 21 object IDs covering 2677 units across 5 tiles while zero
tiles had been removed — every lost ID satisfied exactly one predicate, which
identified the offending code path with no guessing, and the same diff then
served as the fix's verification (`REMOVED=0 ADDED=0 CHANGED=0`).

**Caveat: it holds exactly one generation.** The next write overwrites it. If
the pre-damage state matters, copy the `.pugbackup` out before letting the game
write again.
