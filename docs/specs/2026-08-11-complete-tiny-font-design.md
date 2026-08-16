# Complete Tiny Font — design

**Date:** 2026-08-11
**Scope:** a new mod `complete-tiny-font` that replaces Core Keeper's `thinTiny`
font with the hand-drawn 331-glyph full build, plus the ItemChecklist change that
drops its own glyph injection and depends on the new mod (ItemChecklist Iter-46).

## 1. Purpose

`thinTiny` (atlas `rrs5`) is CK's reduced face: 114 codepoints, no German
umlauts, no accents, no Cyrillic. `PugFont.GetGlyphData` falls a missing `ö`
back to the **chinese** font, which renders it in CJK metric — deformed, with no
warning. ItemChecklist worked around this in Iter-25 by injecting 85
mod-authored glyphs at runtime from its own bundle sheet.

Since 2026-08-11 the Pixaki master (`item-checklist/sources/thinTiny.pixaki`,
revision 12) is a **complete** font: 331 of 331 codepoints, defect-free per
`sources/thinTiny-review.md`, with § 8 of that review deciding on **full
replacement** (all 331 glyphs injected, not just the 217 missing ones).

A complete font is no longer an ItemChecklist implementation detail. This design
moves it into its own published mod so every mod with `thinTiny` chrome benefits,
and ItemChecklist consumes it.

## 2. Decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | **Passive font replacement, no public API** | The injection is a side effect on a global singleton (`Manager.text.thinTiny`), so consumers call nothing. A registration framework has no customer: `thinSmall` (331) and `boldHuge` (341) are complete; `thinTiny` is the only deficient face. |
| D2 | **ItemChecklist depends hard (`required: 1`)** | User's call, taken with the failure mode on the table (see § 7). Gains a guaranteed load order via the loader's topological sort. |
| D3 | **Full replacement is fixed, not configurable** | Keeps the mod **dependency-free** (no CoreLib, no Mod Settings Menu), which matters because a font is potentially the *bottom* layer other UI mods depend on — taking MSM as a dependency would foreclose a future MSM→font dependency. Offering "only the missing 217" as an option would also ship the style break § 8 rejected (6 px `A` beside 5 px `Ä`). |
| D4 | **Name: `complete-tiny-font` / `CompleteTinyFont` / "Complete Tiny Font"** | Family convention names mods by effect, not by engine internals (`thinTiny` is a `TextManager.FontFace` name). The precise wording ("replaces CK's `thinTiny` / `rrs5`") goes in the first line of the description, where mod.io full-text search finds it anyway. |
| D5 | **Mechanism: font swap (S2), not append (S1)** | The full build *is* a complete font resource with `rrsthin8` geometry (257 × 144), not a patch set. Swapping `texture` + `glyphData` and calling CK's own `InitCodePoints()` lets CK apply its own sprite convention (`rect2` padding, centered pivot) instead of the mod replicating it. |

## 3. Verified facts (decompile + runtime metrics)

Decompile paths are `~/Projects/checkouts/CoreKeeperDecompile/Pug.Other.decompiled.cs`
unless noted. Line numbers are from the CK 1.2.1.5 dump and are anchors, not
guarantees.

**Font structure.** `PugFont` (`:350348`) carries `public Texture2D texture`,
`public Vector2Int charDims`, `public float pixelsPerUnit = 16f`,
`public int spaceWidth = 5`, `public GlyphData[] glyphData`,
`[NonSerialized] public Dictionary<char,int> codePoints`, a `[Multiline] public
string _customCharset`, and a **static** `latinCharset` shared by all faces.
The `charset` property (`:350400`) returns `_customCharset` when it is not
null/whitespace, else `latinCharset`.

**`glyphData` is positionally parallel to `charset`.** `InitCodePoints`
(`:350429`) does `codePoints.Clear()`, then iterates
`Math.Min(glyphData.Length, charset.Length)`, skips `charset[i] == ' '`, skips
zero-size rects, and for the rest computes
`rect2 = (rect.position + (0,1), rect.size - (0,1))`, widens it by
`x -= 1; width += 2` when `rect2.width + rect2.x + 2 < texture.width` (else it
logs "*you need to make the font texture 1 pixel wider to the right to support
outlines*" — this is why the atlas is 257 and not 256 wide), derives a
**centered** pivot and calls
`Sprite.Create(texture, rect2, pivot, pixelsPerUnit, 0u, SpriteMeshType.FullRect)`.

**The two faces use different charsets.** Measured from
`item-checklist/sources/glyph-templates/glyph_metrics.json` (runtime dump):

| | `glyphData` | codePoints | `charDims` | atlas | index 0 / 1 / 2 |
|---|---|---|---|---|---|
| `thinTiny` (`rrs5`) | 118 | 114 | **[8, 10]** | 256 × 40 | empty / `!` / `"` |
| `thinSmall` (`rrsthin8`) | 384 | 331 | [8, 12] | **257 × 144** | `♥` / `♡` / controller glyph |

`thinTiny` therefore carries its own `_customCharset` starting at ASCII 33, while
`thinSmall` uses `latinCharset`. Painted-but-codepointless indices are
`{97, 98}` in `thinTiny` (the unmapped `Ç`/`ç` images Iter-25 found) and
`{2..7, 378..381}` in `thinSmall` (the six controller symbols plus the four
template orphans of the review's § 6).

**No codepoint is lost by switching charsets:** `thinTiny`'s 114 codepoints are a
strict **subset** of `thinSmall`'s 331 (measured: `thinTiny - thinSmall = {}`,
gain 217 — the same 217 § 8 names as the rejected minimal variant).

**`latinCharset` holds exactly one character per atlas cell:** measured length
**384 = 32 × 12**, the last six being spaces. So a charset position, a
`glyphData` index and an atlas cell are the same coordinate.

**`charDims` is layout metric only.** It feeds the line advance
(`:350574`), the reported text dimensions (`:350762`, `:350763`) and an x offset
(`:329076`, `:329095`). It plays no part in decomposing the atlas — that comes
solely from `glyphData[i].rect`.

**The injection anchor.** `TextManager.Init2` (`:271881`) calls
`InitCodePoints()` on all twelve faces and is itself called exactly once, from
`TextManager.Init()` (`:271826`).

**The dependency contract.** `PugMod.Loader.decompiled.cs:988`
(`ModSorter.SortMods`): a mod with a `required` dependency that is not present is
**removed from the load list** with only a `Debug.LogWarning("skipping mod X
because of missing dependency: Y")` — no in-game dialogue. The same loop then
`break`s after the first removal, so with two such mods the second survives the
filter and fails later; `required` is thus a partial guard, not a strong one.

**The Pixaki master.** Inspected directly (`document.json`): canvas
**257 × 144**, layers `Background / Dims / Rects / Atlas / Layer 1`, 5 cels —
matching the review. Per the review, all 337 rect boxes share
`y = 1, h = 10, x-offset 0`; 336 of 337 have zero right gap; digit advances are 3
(identical to real `thinTiny`, so digit layout does not shift).

## 4. Runtime architecture

One `IMod` bootstrap plus one Harmony patch class; no CoreLib, no localization,
no config.

```csharp
// Harmony postfix on TextManager.Init2
var f = __instance.thinTiny;
f.texture        = atlas;                   // our 257×144 sheet from the bundle
f._customCharset = null;                    // -> latinCharset, the order the atlas is drawn in
f.charDims       = new Vector2Int(8, 10);   // UNCHANGED (see below)
f.glyphData      = BuildGlyphData();        // one entry per charset position
f.InitCodePoints();                         // CK builds codePoints + volatileSprites itself
```

**Why `charDims` must stay at (8, 10).** The atlas uses a 12 px cell grid, but the
glyphs are 10 px tall (rect boxes `y = 1, h = 10` inside each cell). Since
`charDims` only drives line advance and reported dimensions, setting it to 12
would grow every line gap in existing mod UIs by 2 px while changing nothing about
the glyphs. Leaving it at 10 keeps vanilla `thinTiny` line metrics exactly.

**Why the anchor beats ItemChecklist's.** Iter-25 injects at
`PlayerController.OnOccupied` (world entry). `Init2` runs at manager start, so the
glyphs are in place for the **main menu and the options / Mod Settings menus** —
surfaces where accented labels are CJK-deformed today and cannot be fixed from a
world-entry anchor.

**Timing without a wager.** Whether `Init2` runs before or after
`IMod.ModObjectLoaded` (where the AssetBundle becomes available) is not
guaranteed. A single idempotent `TryApply()` is therefore called from **both**
the `Init2` postfix and `ModObjectLoaded`; it applies once both preconditions hold
(`thinTiny != null`, bundle loaded) and is a no-op afterwards. A hypothetical
second `Init2` would self-heal, since `InitCodePoints` clears `codePoints`.

**The glyph table is a width vector.** Because every rect box shares
`y = 1, h = 10, x-offset 0`, only the width varies. Per cell index `i`
(row-major, 32 columns × 12 rows = 384 cells):

```
x       = (i % 32) * 8
y_unity = 144 - ((i / 32) * 12 + 11)
w       = widths[i]          // 0 = empty cell -> zero-size rect -> skipped by CK
h       = 10
```

So the shipped table is 384 small numbers (a string of digits `0`–`8`), not 384
C# rows. `glyphData` is allocated at `Math.Min(f.charset.Length, 384)`.

**Index semantics change, deliberately.** After the swap, glyph indices follow
`latinCharset`, so index 2–7 are the codepointless controller-symbol slots
instead of `" # $ % & '`. This is what makes the six controller glyphs of atlas
row 0 reachable at all (§ 6 of the review notes that a codepoint-based
replacement never delivers them). Everything CK renders goes through
`GetGlyphData(char)` → `codePoints`, so index-based access is expected to be
confined to those slots — see the verification step in § 8.

**Sheet import.** The sheet ships as `Art/thinTiny_full.png` with the proven
`.meta` pair `textureType: 8` / `spriteMode: 1` and is loaded via
`LoadAsset<Sprite>(...).texture`, i.e. the ItemChecklist recipe (ModBuilder packs
a `Texture2D` under the default `textureType: 0`, which would make
`LoadAsset<Sprite>` return null).

## 5. Build pipeline

`sources/glyph-templates/pixaki_to_glyphs.py` was written for the Iter-25 file
(thinTiny-sized canvas, 8 × 10 cells, only the missing glyphs). It is reworked
rather than reused, and it becomes a **shared tool** at
`core_keeper/utils/pixaki_to_glyphs.py` beside its sibling `pixaki_to_sheet.py`
— the pytest harness (`utils/tests/conftest.py`) and the `ruff format` gate exist
only in the parent repo, and a generator without tests is what produced the
Iter-25 pivot bug. Its *reference data* still moves to the mod repo (§ 6). The
rework:

1. `NEWCDX, NEWCDY = 8, 12` — the cell grid is `thinSmall`'s.
2. Drop the `if str(code) in tt_cp: continue` guard — full replacement needs the
   114 glyphs `thinTiny` already has.
3. `PIXAKI` points at `sources/thinTiny.pixaki` (the old `thinTiny_full.pixaki`
   no longer exists).
4. Emit a **width vector per cell index**, not `{code, x, y, w, h}` rows; write
   the sheet from the `Atlas` layer to `unity/CompleteTinyFont/Art/thinTiny_full.png`.
5. **Fail loud on invariant violations**, mirroring the pin validation in
   `utils/pixaki_to_sheet.py`: abort when any rect box deviates from
   `y = 1, h = 10, x-offset 0`, when a painted cell has no rect box (or vice
   versa), or when `charset.Length != 384` (a CK update that extends the charset
   must not be papered over).

The magenta filter in `mbbox()` matches the `Rects` layer colour `(229, 59, 223)`
unchanged. `glyph_metrics.json`, `grids/` and the extracted `rrs*` atlases stay
gitignored (Pugstorm-derived); only the scripts and the README are tracked.

## 6. Repository layout and migration

New repo `complete-tiny-font/`, scaffolded without the Unity Editor:

```bash
# no --corelib: the mod has no dependencies
utils/new_mod.py complete-tiny-font \
  --summary "Completes Core Keeper's small pixel font: umlauts, accents and Cyrillic instead of deformed fallback glyphs."
```

- `requiredOn: 1` (Client). Semantically the mod needs no side, but `0` is not
  publishable — `CLIPublishHelper` derives the mod.io `Application Type` tag from
  it and aborts.
- `skipSafetyChecks: false` — the mod touches no `System.IO`; it needs
  `Sprite.Create`, a texture and public `PugFont` fields.
- fake-ID **9999987** (`9999988`–`9999999` are taken by the twelve existing mods).
- No localization (the mod has no UI), no config, version 1.0.0.

Moved out of `item-checklist/` (copy, then delete there; history stays readable in
the ItemChecklist repo — no `filter-repo`):

| Artifact | Destination |
|---|---|
| `sources/thinTiny.pixaki` | `complete-tiny-font/sources/` |
| `sources/thinTiny-review.md` | `complete-tiny-font/sources/` — the font's rationale record stays beside the master; `sources/` is not a docs directory, so its German text raises no language-convention conflict |
| `sources/glyph-templates/**` | same path in the new repo, **including the `.gitignore` stanza** (`*.py` + README tracked, derived CK data ignored) — **except `pixaki_to_glyphs.py`**, which becomes `core_keeper/utils/pixaki_to_glyphs.py` with unit tests (§ 5) |
| `unity/ItemChecklist/ThinTinyGlyphPatch.cs` | rewritten as `ThinTinyFontPatch.cs` (S2), not copied |
| `unity/ItemChecklist/Art/thinTiny_glyphs.png` (+ `.meta`) | **dropped** — the 85-glyph sheet is obsolete; the 257 × 144 sheet is generated fresh |

Logo (`unity/CompleteTinyFont/Editor/logo.png`), per the family DNA with its own
gesture: a teal/petrol letterpress type sort as the hero object, with three gold
diacritics (´ ¨ ˇ) floating above it as the gesture; golden radial glow,
4-point sparkles, 1024². Produced through the `image-generation` pipeline
(white candidates → native black → transparify) with two sibling logos as
references.

## 7. ItemChecklist changes (Iter-46)

- Delete `ThinTinyGlyphPatch.cs`, `Art/thinTiny_glyphs.png` (+ `.meta`) and the
  call site in `ItemCatalogWorldLoadHook.cs:66`.
- Add to `unity/ItemChecklist/ItemChecklist.asset` `dependencies:`
  `- modName: CompleteTinyFont` / `required: 1`.
- **No asmdef reference.** ItemChecklist references no type from the font mod;
  the manifest dependency exists only for load order and the skip rule.
- Version **1.4.0** — a new mandatory dependency breaks installation, so this is
  not a patch release. `CHANGELOG.md`, `README.md` and the mod.io description name
  the dependency **and** the failure mode: without the font mod the loader drops
  ItemChecklist from the load list with only a log warning, so a "the mod
  vanished" report is diagnosable.
- Documentation: `docs/architecture.md` § Runtime Glyph Injection becomes a
  pointer, likewise the corresponding `docs/gotchas.md` passage; the
  `docs/conventions.md` file-layout map loses the two deleted entries; the
  `PugFont` row in `CLAUDE.md`'s decompile table is shortened to a pointer. The
  Iter-25 entries in `docs/iteration-history.md` and `docs/roadmap.md` stay as
  written — historical findings are not rewritten — and a new Iter-46 entry
  records the extraction.

## 8. Publishing sequence and verification

**Sequence (a hard constraint, not a preference).** A freshly created mod.io mod
is invisible to the API until it is approved in the dashboard (verified with
`auto-rail-bridges`), so ItemChecklist's publish could not resolve the platform
dependency:

1. Publish `complete-tiny-font` 1.0.0, approve it in the mod.io dashboard.
2. Refresh `utils/modio-dependencies.json`.
3. Publish ItemChecklist 1.4.0 (its `.asset` dependency syncs to a mod.io
   platform dependency).
4. Annotated git tags on both published commits (`1.0.0`, `1.4.0`), pushed to
   `origin` and `backup`.
5. `utils/server.sh relink` — **the dedicated server needs the font mod too.**
   It loads ItemChecklist as well, so a missing font mod makes `SortMods` drop
   ItemChecklist *server-side*, and an asymmetric mod set is exactly what surfaces
   as `Error/BadProtocolVersion` ("wrong game version") on join.

**Verification, in this order:**

1. Build: 0 `error CS`; in-game `safetyCheck=True`, 0 `CompileFailed`. This is
   where writing `_customCharset` and `texture` proves sandbox-legal — Iter-25
   established `glyphData` and `codePoints`, these two are new.
2. **Main menu → Options → Mod Settings with language German**: umlauts correct.
   This is the gain that a world-entry anchor cannot deliver.
3. Damage numbers: 1 px flatter, layout unshifted (digit advance stays 3).
4. ItemChecklist chrome ("Gewöhnlich / Ungewöhnlich / Legendär") correct
   **without** the ItemChecklist patch.
5. Line spacing in ItemChecklist's list unchanged — the evidence that leaving
   `charDims` at (8, 10) was right.
6. The index reinterpretation: `thinTiny` index 2–7 used to be `" # $ % & '` and
   now holds the codepointless controller slots. Any CK site that hardcodes a
   `thinTiny` glyph index shows up here (button prompts, damage popups).
7. Negative test: disable the font mod and confirm
   `skipping mod ItemChecklist because of missing dependency: CompleteTinyFont`
   in `Player.log` — the documented failure mode, verified once so it is
   recognisable in support.

## 9. Risks and open points

- **Sandbox legality of `_customCharset` / `texture` writes** is unproven; both
  are public fields on a `ScriptableObject` whose siblings (`glyphData`,
  `codePoints`) are already written from a sandboxed mod. Detected at step 1; the
  fallback if either is rejected is S1 (append + rewire `codePoints`), which is
  the Iter-25 mechanism scaled to 331 glyphs.
- **Vanilla digits get 1 px flatter.** Accepted by § 8 of the review; it is the
  only vanilla-visible change. **Corrected 2026-08-12 against the shipped assets**
  (the earlier claim "damage and score numbers", inherited from the Iter-25 notes,
  was wrong): exactly **14** assets set `fontFace: 16777344`, and they are the
  slot surfaces — `InventorySlot{,Player,PlayerMasked,TrashCan, Furnace, FishingCrafting}`,
  `InventoryProgressSlot`, `RecipeSlot`, `RecipeCategorySlot`,
  `BossStatueRecipeSlot`, `DroppedItem` (stack size on the ground), `ConditionUI`,
  `CoolTextPrefab` (score text) and the main-manager prefab. **Damage numbers are
  NOT among them:** `CombatText.prefab` carries `fontFace: 16777232` (thinSmall),
  and CK's `isDamageNumber → SetDefaultFont(thinTiny)` branch is inert because
  rendering reads `style.fontFace` while `SetDefaultFont` writes
  `defaultStyle.fontFace` and nothing copies that direction. So the visible vanilla
  change is item counts in inventory/recipe slots, ground-item stack sizes, and
  score text.
- **`required: 1` is a silent total failure** when the dependency is absent, and
  the loader's `break` bug makes it an incomplete guard. Mitigated by the mod.io
  platform dependency (auto-install), the documented failure mode and the
  negative test.
- The old `rrs5` texture stays loaded in memory after the swap (harmless; a font
  atlas is ~1 KB of PNG).

## 10. Out of scope

- A registration API for other faces or third-party glyph sets (D1).
- A setting to choose partial replacement (D3).
- Migrating other family mods (Mod Settings Menu, player-coordinates-hud, …) to
  declare the font mod. They inject nothing today and merely benefit passively;
  whether any of them should declare a dependency is a separate decision per mod.
