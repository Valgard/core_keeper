# Mod Settings Menu — Design

- **Status:** design approved; ready for implementation plan
- **Date:** 2026-06-29
- **Names:** `ModSettingsMenu` (namespace) · `mod-settings-menu` (repo) · "Mod Settings Menu" (displayName)
- **Type:** standalone, published Core Keeper mod; CoreLib as a dependency

## Problem & goal

Core Keeper mods hardcode their config values — the RoslynCSharp sandbox forbids
`System.IO`, so tunables live as literals in a `ModConfig` singleton and changing
one requires a rebuild. No in-game settings UI, no shared machinery for it in the
SDK or CoreLib.

Goal: a published **framework mod** that lets *consumer* mods declare their
settings **declaratively in code**; the framework builds an in-game Options-menu
entry, persists the values (CoreLib `ConfigFile`), and reads back live. Consumers
say only *what they need*; the framework owns the menu, the layout and the widget
prefabs.

## Why build it (existing landscape evaluated)

The mod.io landscape was checked (247 CK mods scanned):
- **GMCM ("General Mod Config Menu")** — a CoreLib-`ConfigFile` reader, entry in
  the game settings, 53k subscribers. **Evaluated in-game and rejected as our
  UI:** (a) only **1 of 26** installed mods actually feeds it (PlacementPlus) —
  HealthBars, a polished popular mod, deliberately builds its *own* menu instead,
  so the real mainstream is "each mod its own menu", not GMCM; (b) wrong UX —
  nested (mod list → page per mod), raw `Path/File` keys, unpolished rendering;
  (c) no source on GitHub, no screenshots. **But adopted as a technical
  reference** (its source is readable as an installed Script-mod).
- **CK-QOL.ConfigUI** — a CTRL+Y *overlay*, not settings-menu integration; out of
  scope for our use case.

Decision: build our own (option B from brainstorming — own mod + CoreLib
dependency), with a better UX than GMCM, reusing GMCM's *techniques*. See
[[reference_ck_settings_menu_integration]].

## GMCM as technical reference — what we copy / skip

Source (installed): `ModLoader/GeneralConfigMenu/Scripts/` (31 files, 3383 lines).

**Copy:**
- **Menu mount** (`MenuPatch.cs`): `MenuManager.Init` **prefix** clones the
  `UI_OPTIONS` `RadicalOptionsMenuOption_PushMenu` inside `optionsMenuPrefab`,
  `SetSiblingIndex(idx+1)`, sets text + own `menuToPush`. `MenuManager.Init`
  postfix instantiates the own menu prefab under `Manager.camera.uiCamera`.
  `RadicalMenu.TypeToMenu` prefix maps an own `(RadicalMenu.MenuType)` id →
  own menu. (Cleaner than HealthBars: prefix-on-prefab, not postfix-on-instance.)
- **Own menu prefab** as `class … : RadicalMenu, IScrollable` +
  `[RequireComponent(typeof(UIScrollWindow))]` (`ModConfigMenu.cs`) — full layout
  control instead of cloning the vanilla flat options menu.
- **`LinearLayoutUIComponent`** for auto vertical stacking: hang sections/boxes
  in it, call `RenderUIComponent(true)`, report `GetUIComponentRenderHeight()` to
  the scroll window. **This replaces the hand-rolled box-stacking that was the
  design's largest UI risk** — the engine does it.
- **Template rendering** (`RegisterDetails()`): group entries by `def.Section`,
  `Instantiate(Template.Section)` + per entry `Instantiate(Template.Entry)` +
  `BindEntry(...)`. This is our box-per-mod + widget stamping.
- **Widget pattern** (`UIConfigValueBool.cs`): one MonoBehaviour per widget type,
  `Click()` → set + apply, `UpdateDisplayValue()` → read. Maps to Toggle / Slider
  / Stepper.
- **`ConfigFile.AllConfigFilesReadOnly`** to enumerate all registered configs (if
  we read ConfigFile directly).

**Skip:** GMCM's `ConfigSync/*` (RPC server↔client sync, permissions, AdminOnly)
— multiplayer complexity, the bulk of its lines; unnecessary for client settings.

## Components

| Component | Responsibility | Depends on |
|---|---|---|
| `ModSettings` (static facade) | Consumer API: `Section(this).Toggle/Slider/Stepper(...).Build()` (IMod ref → modId + displayName via `Handlers.Contains`); registry `modId → section` | – |
| `SettingHandle<T>` + `Setting.*` builders | Type-safe value handle (`.Value`, `.OnChanged`) | CoreLib `ConfigEntry<T>` |
| `ConfigStore` (persistence) | One CoreLib `ConfigFile` per consumer mod; binds handles to `ConfigEntry`s; autosave | CoreLib `ConfigFile` |
| `ModSettingsMenuMount` (clone layer) | GMCM-style: `MenuManager.Init` prefix injects the "Mod-Einstellungen" entry; postfix instantiates own menu; `TypeToMenu` prefix | Vanilla `RadicalMenu`, Harmony |
| `SettingsMenu` (own prefab) | `RadicalMenu, IScrollable` + `UIScrollWindow`; one page; `LinearLayoutUIComponent` stacks the per-mod boxes | `LinearLayoutUIComponent`, templates |
| `SectionBox` renderer | Per mod: free DisplayName + optional Hint, then a 9-slice box around its widgets (templates instantiated + bound) | `SettingsMenu` |
| Widget prefabs (AssetBundle) | Toggle/Slider/Stepper `RadicalMenuOption` subclasses + Header/Hint `PugText` | – |
| `ModSettingsMenuMod : IMod` | Bootstrap; CoreLib dependency; builds menus after registration | CoreLib |

## Consumer API & data flow

```csharp
// faster-talents, in IMod.Init():
ModSettings.Section(this)   // IMod ref → modId=Metadata.name (terms), heading=Metadata.displayName; hint ← FasterTalents-Config/_hint
    .Toggle (out Enabled,       "enabled",       def: true)                // term FasterTalents-Config/enabled
    .Slider (out XpMultiplier,  "xpMultiplier",  min: 1, max: 10,  def: 3) // term FasterTalents-Config/xpMultiplier
    .Stepper(out Tier1MaxLevel, "tier1MaxLevel", min: 1, max: 100, def: 60)
    // labels/hints live in faster-talents/localization/localization.yaml under
    // the derived "FasterTalents-Config/<key>" terms; no label arg in the builder.
    .Build();
// Read in patch — live: float mult = XpMultiplier.Value;
```

1. **Register** (consumer `Init`): each setting → CoreLib `ConfigEntry<T>` in the
   mod's `ConfigFile` (loads persisted or default), returns `SettingHandle<T>`.
2. **Build menu** (`MenuManager.Init` postfix): clone entry into options menu,
   render per registered section a DisplayName + Hint + box + widgets into the
   `LinearLayoutUIComponent`.
3. **Change**: widget writes `ConfigEntry.Value` → autosave → optional `OnChanged`.
4. **Read**: `handle.Value` is always current → live, no apply step.

Timing self-resolves: consumers register in `Init`; menu builds in the
`MenuManager.Init` postfix (fires when the player opens Options, after all
`Init`s) → all sections present before first render.

## UI / layout / sandbox

- Mount + own-prefab + LinearLayout + template rendering: see "GMCM reference".
- UX vs GMCM: **all mods as box-sections on one page** (not nested), **DisplayName
  + Hint** headings (not raw keys), clean labels.
- Reuse from ItemChecklist: scrollbar/`UIScrollWindow` wiring, 9-slice boxes via
  `GetCraftingUITheme(...).background`, sprite-prefab + fileID/GUID wiring, Pixaki
  sheet + `pixaki_to_sheet.py`, SpriteRenderer+Layer5+`UIelement`. See
  [[project_corekeeper_ui_pattern]], [[project_corekeeper_script_fileid_derivation]].
- **No `skipSafetyChecks`**: mounting via Harmony attributes (allowed);
  persistence delegated to CoreLib `ConfigFile` (its assembly); DisplayName via
  public `API.ModLoader.LoadedMods[…].Metadata.displayName`. No direct
  `System.IO`/`Encoding`/`Reflection`.

## Localisation

Reuses the project's **established** pattern (ItemChecklist Iter-11) — **NOT**
CoreLib `LocalizationModule` (deprecated, carries `//TODO Remove Localization
Module?`; the reason the mods avoid it). GMCM's CoreLib-`AddTerm` approach was
explicitly rejected here.
- **Source:** each consumer mod ships a `localization/localization.yaml` (mod-root,
  **outside** `unity/` so ModBuilder doesn't bundle it) — EN+DE inline by ISO code.
- **Generate:** the **shared** `utils/LocalizationGenerator.cs` (+
  `utils/ck-language-addresses.json`, 13 langs) templates native `TextDataBlock`
  assets per language at build time. Mod Settings Menu inherits this `utils/` infra via
  `link.sh` like faster-talents/disable-durability already do.
- **Render:** `Loc.T(term) = API.Localization.GetLocalizedTerm(term) ?? term`
  (`Loc.cs`, 10 lines); `Loc.F(term, arg0)` for `{0}` formats. Raw term is the
  fallback — never a broken key. Sandbox-safe.
- **Term convention:** `<ModId>-Config/<key>` (e.g. `FasterTalents-Config/xpMultiplier`),
  derived from the key, so the builder needs no label arg. Section **heading** =
  `Metadata.displayName` (fallback `Metadata.name`) — the raw modId is **never**
  displayed; `Metadata.name` (resolved from the `Section(this)` IMod ref via
  `Handlers.Contains`) is internal only (registry key + term derivation). The
  optional section **hint** uses the reserved term `<ModId>-Config/_hint`.
- **Hint is opt-in, no raw fallback:** labels use `Loc.T(term) ?? term` (a label must
  always show); the hint shows **only** if `GetLocalizedTerm(term) != null` — an
  undefined `_hint` term → no hint line at all (never the raw term). Leading `_`
  keeps the key collision-free vs a setting named "hint".
- **Consumer responsibility:** the consumer adds its label/hint terms to its own
  `localization.yaml`; Mod Settings Menu only renders over the derived term. **faster-talents
  has no `localization.yaml` yet → the pilot adds one** (its first loc infra).

## Bonus: dual visibility

Because the backend is CoreLib `ConfigFile`, consumer mods are configurable in
**both** Mod Settings Menu *and* GMCM (for players who have GMCM) at no extra cost — we
build the better UI on the shared fundament, not a competitor.

## Error handling

- Duplicate key → log warning, first wins. Corrupt config → CoreLib defaults.
- CoreLib missing → impossible (required dependency, topo-sort). Empty section →
  skipped.

## MVP scope (YAGNI)

| In | Out (post-MVP) |
|---|---|
| Toggle, Slider, Stepper | Dropdown/Cycling, colour picker |
| Box per mod (DisplayName + optional Hint) on one page | "Reset to default" per section |
| CoreLib `ConfigFile` persistence, live apply | many-mods overflow/scroll-of-sections scaling |
| **Labels via established loc** (YAML + shared `LocalizationGenerator` → `TextDataBlock`, `Loc.T`) | languages beyond EN/DE |
| Pilot: faster-talents **+** faster-pet-talents | further mods; server/client sync (GMCM has it) |

### Pilot tunables
- faster-talents: `enabled` (bool), `xpMultiplier` (float 3), `tier1MaxLevel`
  (int 60), `tier1RanksPerPoint` (int 3), `tier2RanksPerPoint` (int 2),
  `maxSkillBonusPoints` (int 0).
- faster-pet-talents: `enabled` (bool), `talentCount` (int 9), `xpMultiplier`
  (float 3).

Per mod: replace hardcoded `ModConfig` fields with `SettingHandle`s + one
`ModSettings.Section(...).…Build()` in `Init`; read sites get `.Value`.

## Risks / open points

- 9-slice theme availability (`GetCraftingUITheme`) — re-verify empirically at
  implementation (memory ~29 days old).
- `LinearLayoutUIComponent` exact API (`RenderUIComponent`,
  `GetUIComponentRenderHeight`) — confirmed via GMCM source; verify at build.
- Widget prefabs must carry correct `RadicalMenuOption` wiring + sprite `.meta`
  (`textureType:8`/`spriteMode:1`).
- Scaling beyond ~5–6 mods deferred; section registry built for *n* from the start.

## Testing

In-game smoke test (faster-talents box appears; slider changes XP rate; survives
restart; cross-check it also shows in GMCM). Pure logic (stepper clamping) as
small standalone tests where runnable without the Editor.
