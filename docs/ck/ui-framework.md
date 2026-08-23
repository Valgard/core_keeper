# The UI framework

Core Keeper's interface is not built the way a Unity developer expects. There is
no Canvas, no `RectTransform`, no `Image` in the sprite UI you build — it is sprites on a
dedicated layer, driven by the game's own `UIelement` hierarchy. This chapter
covers the pattern every UI mod follows, how to mount a window and suppress the
gameplay UI behind it, how to show a vanilla item tooltip, how to add a row to
the options menu and a rebindable key to the controls screen, what the footer
hint bar will and will not let you do, how to get a text field, how to make a
scroll window clip its content and follow the selection, and how to grey out a
setting the player may not change right now.

## Sprite UI, not uGUI

**Do not build with uGUI.** A May 2026 survey of ten published Core Keeper UI
mods — roughly 43,000 lines of prefab YAML — found zero occurrences of `Canvas`
or `RectTransform`. That is not a stylistic preference, and the mechanism is
what makes it a rule rather than a headcount: CK's `UIMouse` resolves pointer
input with a **physics raycast into Layer 5** and therefore only ever finds a
`SpriteRenderer` with a `Collider`. A uGUI hierarchy is invisible to it, and to
everything downstream.

The canonical shape of a modded UI object:

This shape describes an **interactive UI window** — something the player opens,
clicks and navigates. A passive HUD element belongs on a different layer and
follows different rules; see [why a mod HUD stays invisible](prefabs-and-rendering.md#why-a-mod-hud-stays-invisible) before building one.

| Element | What it must be |
|---|---|
| Layer | `5` (UI) — windows only; a HUD element goes on `27` |
| Renderer | `SpriteRenderer` — never `Image` |
| Transform | plain `Transform` — never `RectTransform` |
| Sorting | the `"GUI"` sorting layer plus an explicit `sortingOrder` |
| Root class | `class MyUI : UIelement, IModUI` — inheritance *and* interface |
| Navigation | chain neighbours via `UIelement.bottomUIElements` / `topUIElements` |

The four `UIelement` neighbour lists — `top`, `bottom`, `left` and
`rightUIElements` — feed `UIelement.GetAdjacentUIElement` and nothing else: they
are **directional keyboard and controller navigation**. An element left out of
the chain still works with the mouse but cannot be reached with a D-pad or the
arrow keys. Mouse reachability is a separate mechanism entirely — see below.

**Trap: there is no `"UI"` sorting layer, and "layer" means two unrelated
things here.** `TagManager.asset` defines no sorting layer named `"UI"` — CK UI
sprites sort on **`"GUI"`** (uniqueID `1241602095`). Unity's *layer 5* is also
called "UI", but that is a tag-layer used for `Physics.Raycast` filtering, an
entirely separate axis. Setting one does not set the other, and both must be
right. Watch the round-trip too: an Editor-authored prefab child has come back
with `m_SortingLayerID: 0` while its tag-layer 5 was correct.

Inheriting from `UIelement`, reading `Manager.input` and touching
`API.Rendering.UICamera` are all permitted inside the Roslyn sandbox — see [the load-time sandbox](sandbox.md).

### How `UIMouse` picks and selects an element

`UIMouse.UpdateMouseUIInput()` (`Pug.Other` ~355773) re-runs
`Physics.RaycastNonAlloc` against `ObjectLayerID.UILayerMask` **every frame**
and calls `TrySelectNewElement`. `Manager.ui.currentSelectedUIElement` is
therefore owned by that raycast: a selection you assign from code is clobbered
on the next frame.

There is **no `isSelectable` flag**. What makes an element selectable is a
**3D collider on the same GameObject that carries the `UIelement`** — that is
where `UIMouse`'s `GetComponent<UIelement>()` resolves — on the UI layer,
passing `isVisibleOnScreen` (active + enabled + non-zero lossy scale).
Deselection runs through `DeselectAnySelectedUIElement` (~273433) via
`UIManager.OnUIElementSelected` (~273416).

**Trap: it must be a `BoxCollider`, not a `BoxCollider2D`.** The raycast is 3D,
so `!u!65` is hit and `!u!61` never is — and the 2D component is the natural
first choice for a 2D sprite UI. It fails silently.

**Overlapping clickables are arbitrated by Z.** The ray starts at
`pointer + back * 5` along `Vector3.forward` and the smallest-distance hit wins.
Two colliders both at z-centre `0` are a nondeterministic tie; pull the one that
must win forward via `m_Center.z` (`-0.1` was enough in two cases, `-0.5` in
another). The collider's `z` extent is raycast depth (`4` in the shipped
scrollbar handle). Two consequences worth knowing: an open popup drawn over a
list does **not** leak hover to the elements behind it, so a guard for that is
dead weight; and `ScrollBar.UpdateHandleSize` — which runs only when the handle is dragged
or the content height changes — overwrites the handle collider's `y` whenever
it runs, so authoring that value is pointless either way: `ScrollHeight` —
content height minus window height (`Pug.Other:357633`) — is 0 until content
actually overflows the window, and below that `ScrollBar.Update` deactivates
the whole scrollbar root and never calls `UpdateHandleSize` at all; the
moment it does overflow, `UpdateHandleSize` runs that same frame and
overwrites the authored value anyway.

**Hover, not click, drives selection.** `RadicalMenu.SelectOptionIndex` fires
`OnDeselected()` on mere hover exactly as it does on arrow-key navigation.
Moving the mouse into empty space calls
`Manager.ui.DeselectAnySelectedUIElement()` and sets `selectedIndex = -1`
regardless of any override of yours. What that does to a field the player is
editing is in [text rendering and text input](#text-rendering-and-text-input).

**Clicking a *different* element is a second, separate path — and it discards.**
`TrySelectNewElement` opens with a hardcoded
`Manager.input.activeInputField.Deactivate(commit: false)`, but that line is
gated on its `interactDownThisFrame` argument, which the caller fills with
`WasButtonPressedDownThisFrame(UI_INTERACT)` (inside an active menu, that value
is replaced with `Manager.input.IsMenuMouseInteractButtonDown()` before the
call — a press either way) — a real click, never a hover. So
hover-deactivation and click-deactivation are two mechanisms with two different
remedies; only the first one is what `dontDeactivateOnDeselect` suppresses.

### Subclassing a CK UI component

**Check whether the method is virtual before overriding it — CK is not
consistent about this.** Most UI base classes declare `protected virtual void
Awake()`, so `override` is the right keyword: `SlotUIBase`, `RadicalMenuOption`,
`RadicalMenu`, `ButtonUIElement`, and `UIelement.LateUpdate` are all virtual.

Some are not. `TextInputField` declares a plain `protected void Awake()`, and
there a subclass cannot `override` at all: hide it with `private new void
Awake()` and call `base.Awake()` explicitly. Unity dispatches the message once,
to the most-derived method, so the base body runs only if you call it — which is
also how you correct state a base `Awake` writes.

Grep the decompile for the specific class rather than assuming either shape.
Applying the hiding idiom to a method CK declared virtual produces a `new`-hiding
warning and forfeits the override CK intended you to use.

**Mirror a virtual's signature exactly.** `UIelement.OnDeselected(bool
playEffect = true)`, `GetHoverStats(bool)` — a near-miss compiles as a *new*
method and the override silently never binds, or fails with `CS0115`. Grep the
decompile before writing the override.

**An overridden `UIelement.LateUpdate` must call `base.LateUpdate()`** — CK's
own `ButtonUIElement` calls it first. The base implementation runs CK's
UI-element tracking; without it input blocking and other housekeeping quietly
stop working.

### Hit-testing without a collider

`Manager.camera.uiCamera.ScreenToWorldPoint(Input.mousePosition)` gives the
cursor position in world space, and because the uiCamera is **orthographic** the
resulting world X/Y are z-independent — no z calibration, no near-plane
fiddling. Comparing that against a panel's world rect (`popupPanel.position ±
panel.size / 2`) is a complete, collider-free hit test. `Manager.camera` is
sandbox-safe.

One mechanic solves two problems with it: **click-outside-to-close** (a naive
"any mouse-down closes" also fires on clicks *inside* the popup) and [mouse-wheel ownership](#mouse-wheel-ownership).
Note the direction: screen → uiCamera world is fine and useful; the dead end
that [prefabs and rendering](prefabs-and-rendering.md) warns about is the opposite projection, world → HUD.

## Mounting a standalone window

There are two established routes. Pick A unless you need something it cannot
express.

### Route A — CoreLib's `UserInterfaceModule`

Load the submodule in `EarlyInit`, register the prefab when the mod's assets are
available, open it on demand:

```csharp
// IMod.EarlyInit
CoreLibMod.LoadSubmodule(typeof(UserInterfaceModule));

// IMod.ModObjectLoaded
UserInterfaceModule.RegisterModUI(go);

// wherever you want it shown
UserInterfaceModule.OpenModUI("MyMod:UIName");
```

The prefab it expects: a `ModUIAuthoring` component on the root GameObject and
your `IModUI` component on that **same** root GameObject. Those two are what
CoreLib actually looks for — `RegisterModUI` does `GetComponent<ModUIAuthoring>()`
and **returns without a word** when it is missing, and the `UIManager.Init`
postfix instantiates the prefab and takes its `IModUI` off the instantiated
root.

The third part is a convention, not a check. `IModUI.Root` is a `GameObject`
property *you* supply, and CoreLib never inspects the name of what it points
at — the string `"root"` never appears in code its `UserInterface` module
executes, only once, in an XML doc comment on `IModUI.Root` itself. Every
mod in this family points it at a child GameObject named `root` holding all the
actual UI elements, and the next trap is why that split is worth keeping.

What you get for free: the window is mounted under
`UIManager.chestInventoryUI.transform.parent`; it hides automatically when
vanilla runs `HideAllInventoryAndCraftingUI`; and cursor, input capture, pause
behaviour and mouse mode all arrive through a postfix on
`isAnyInventoryShowing`, meaning vanilla's own logic does the work.

**Trap: that auto-hide disqualifies route A for an always-on HUD.**
`RegisterModUI` is meant for **modal** UI and hides it at
`HideAllInventoryAndCraftingUI` — the opposite of what a permanent HUD needs. An
always-on element is instead instantiated by the mod itself under
`Manager.ui.chestInventoryUI.transform.parent`; the layer and visibility rules
for that are in [prefabs and rendering](prefabs-and-rendering.md).

**Trap: the `root` child is the visibility carrier; the parent stays active
forever.** CoreLib never touches the GameObject carrying the `Window` /
`UIelement` / `IModUI` component: it instantiates the prefab once in its
`UIManager.Init` postfix and leaves it active for the window's whole life.
Visibility is entirely your own code's job — `ShowUI()` and `HideUI()` are
`IModUI` methods *you* implement, and they enable and disable `Root`, the
**child**; CoreLib only calls `HideUI()` from its
`HideAllInventoryAndCraftingUI` postfix. So any guard meaning "only while the
window is open" has to test `root.activeSelf` (or the interface's own
`IsVisible()`, which returns `Root.activeInHierarchy`).
`gameObject.activeSelf` is always true, never gates anything, and the guarded
code — usually a per-frame path — keeps running while the window is hidden.

**Trap: `OpenModUI` has no toggle, and a bare `HideUI()` freezes the player.**
One key to open and close means toggling yourself, and the close must not be a
direct `HideUI()`. CoreLib's postfix on `HideAllInventoryAndCraftingUI` does two
things: it calls `IModUI.HideUI()` on every registered mod UI **and** clears
`UserInterfaceModule.currentInterface` (via `ClearModUIData`). Clearing that
field is what releases the player from menu state, so a bare `HideUI()` leaves
`currentInterface` dangling and **movement stays blocked** — a symptom that
reads as a completely unrelated bug. Close through

```csharp
Manager.ui.HideAllInventoryAndCraftingUI(forceClose: false);
```

mirroring `PlayerController.CloseAnyOpenInventory`. For the open-vs-closed
decision itself, read *real* visibility (`Instance.Root.activeSelf`) rather than
`currentInterface` — which is `internal static` in CoreLib's
`UserInterfaceModule`, unreachable from a mod assembly at all, not merely prone
to going transiently stale.

**CoreLib forces `isAnyInventoryShowing` true for mod UIs — and only that
getter.** The per-UI getters (`Manager.ui.isPlayerInventoryShowing` and
friends) are **not** patched. Two consequences that pull in opposite directions:

- The game now treats your window as an inventory. The keyboard-shortcuts
  panel's **S** toggle key goes live over your window and the HUD's
  inventory-context elements stay up — see
  [suppressing the gameplay UI](#suppressing-the-gameplay-ui-while-a-modal-window-is-open).
- To distinguish "a vanilla menu is open" from "my own window is open" you must
  read a per-UI getter. The aggregate cannot tell them apart, and gating on it
  makes your own window block itself.

**Trap: `ModUIManager` does not exist.** CoreLib's official v3 and v4 docs show
`ModUIManager.OpenModUI(...)`. The real type is `UserInterfaceModule`. Read
CoreLib's source, not its docs.

**Trap: CoreLib's version label has diverged from the code it ships.** mod.io
has displayed "4.0.4" while hosting the 4.0.3 build, with the real 4.0.4 only on
GitHub as a tag. The two differ in measurable UI-pool behaviour — a
`PugText.Clear()` before `Object.Destroy` that fixes text vanishing on repeated
opens under one build does nothing under the other, and the changelog does not
mention UI at all. Verify pool behaviour against the build that is actually
installed rather than deducing it from the release tag's source.

### Route B — hand-mounted with Harmony

Instantiate your prefab yourself from a Harmony postfix on a vanilla UI's
`Awake`, and mount it under a specific vanilla path. This is also the route for
**in-place extensions** of an existing screen rather than a standalone window,
where you attach to something like:

```csharp
Manager.ui.mapUI.transform.Find("container/largeMapBorder")
```

The cost is roughly a dozen extra Harmony patches for cursor, pause, input,
mouse mode, hotbar and shortcut suppression — everything route A inherits from
vanilla — plus the maintenance of those patches across game updates. `moorowl`'s
`ItemBrowser` is the complete worked template for this route — read it for the
*pattern*, but see [the warning about reference mods](reverse-engineering.md#every-installed-mod-is-readable-source) before lifting an identifier
out of it: several of its most API-looking types are its own, not the game's.

### Suppressing the gameplay UI while a modal window is open

Four separate things stay up behind a modal mod window, and each defeats the
naive attempt in its own way:

| What | The call that works |
|---|---|
| The gameplay HUD | `Manager.ui.TemporarilyDisableGameplayUI()` / `EnableTemporarilyDisabledGameplayUI()` |
| The keyboard-shortcuts panel (`ShortCutsWindow`) | a per-frame `LateUpdate` **prefix** calling its public `HideUI()` |
| Button hints (`InGameButtonHintsUI`) | a `LateUpdate` **prefix** forcing its public `container` inactive |
| ESC opening the pause menu | a **postfix** on `MenuManager.IsPauseDisabled` forcing `__result = true` |

**Never use `Manager.prefs.hideInGameUI` for the HUD.** It `SetDirty()`s to the
player's prefs on disk — the same class of damage as writing through
`PrefsData`. The `TemporarilyDisableGameplayUI` pair instead flips a private
*runtime* scale-multiplier field; it is CK's own mechanism for opening a
`RadicalMenu`, and roughly 51 HUD elements self-scale to zero from it.

The shortcuts panel needs the per-frame prefix even though
`InventoryShortCutsButton.ShortcutsCanBeToggled()` **does** gate the S keybind
itself:
`if (InventoryShortCutsButton.ShortcutsCanBeToggled() &&
!Manager.input.textInputWasActiveThisFrame && …TOGGLE_SHORTCUTS_WINDOW)`. The
gate is not what reopens the panel — `ShortcutsCanBeToggled()` itself reads
`isAnyInventoryShowing`, and CoreLib forcing that getter true is what makes the
predicate pass. The patch does bind: `ShortCutsWindow.LateUpdate` is a
`protected override` declared on the type, and `HideUI()` is public.
`InGameButtonHintsUI` needs its own prefix for a different reason: its
`LateUpdate` re-asserts `container.SetActive(showKeyHints)` every frame, so a
one-shot hide is simply overwritten.

`IsPauseDisabled` is **not** a flag you can set. It is a private method
computing an expression over `preventPausing`, scene state,
`isAnyInventoryShowing` and two frame latches, so the patch has to name it as a
string — `[HarmonyPatch(typeof(MenuManager), "IsPauseDisabled")]`; the usual
`nameof` form does not reach a private member. The public
`MenuManager.PreventPausing(bool)`, which writes the `preventPausing` field that
expression reads, is the blunter alternative.

The list applies to any modal mod window. On route A, *why* the shortcuts panel
and the inventory-context HUD are up at all is CoreLib forcing
`isAnyInventoryShowing` true.

### The first `SetActive(true)` can cost a second

The first time you activate a prefab instance created from your own AssetBundle,
about 98 % of the time goes into the `OnEnable` cascade — first-time asset
loading and shader-variant compilation. One measured prefab took **1039 ms**;
slower machines take longer. Treat the magnitude as "expect something on the
order of a second for a UI prefab of comparable size", not as a constant — the
figure comes from a single menu prefab on one machine.

The cost is **instance-specific, not global**: opening a vanilla menu that uses
the same font beforehand does not warm it. Pre-instantiating does not help
either — `Instantiate` itself is ~1.3 ms. The lever is a `SetActive(true)`
immediately followed by `SetActive(false)` **in the same frame** at load time:
the cost is paid synchronously inside `SetActive(true)`, so no frame is rendered
in between and nothing flashes on screen. The first real open after that
measured 15.7 ms.

### Sprites and pixel alignment

UI sprites are authored at **pixels-per-unit 16**, and every position snaps to a
**1/16 grid**. CoreLib ships a `PixelSnap` component to enforce it — but read
the [on-grid distortion trap](prefabs-and-rendering.md) before using it, because rounding a position onto
the grid is exactly what produces it. The import settings that decide whether
your PNG even arrives as a `Sprite` rather than a `Texture2D` are covered in [prefabs and rendering](prefabs-and-rendering.md).

### Reuse the vanilla window art

You almost never need to draw a background. CK's crafting UI ships finished
nine-slice backgrounds, retrievable at runtime:

```csharp
background.sprite = Manager.ui
    .GetCraftingUITheme(UIManager.CraftingUIThemeType.Wood)
    .background;
```

`UIManager.CraftingUIThemeType` has five members — `Wood`, `Stone`, `Merchant`,
`UpgradeForge`, `DangerousUsage` (`Pug.Other` ~272599) — and that is the whole
set; `GetCraftingUITheme` walks `craftingUIThemes` for a match and logs
*"Missing crafting ui theme setup for …"* when a theme was never configured. The
returned sprites are named `crafting_ui_hand_NN`; `Stone` is `11`. The call is
sandbox-clean, and the theme sprite **overrides whatever sprite you assigned in
the Editor**, so the Editor assignment is only a design-time preview.

## Item slots, icons and tooltips

### The vanilla tooltip is selection-driven, not entity-driven

`UIMouse.UpdateHoverText` (`Pug.Other` ~356342) reads
`Manager.ui.currentSelectedUIElement` and calls four `UIelement` virtuals on it:
`GetHoverTitle()`, `GetHoverDescription()`, `GetHoverStats(bool)` and
`GetContainedObject()`. **No live ECS entity appears anywhere in that path.** To
show the vanilla tooltip for an arbitrary catalog item, a `UIelement` need only
return a `ContainedObjectsBuffer { objectData = new ObjectDataCD { objectID =
objectID, variation = variation, amount = 1, variationUpdateCount = 0 },
auxDataIndex = 0 }`. Spawning an entity, or porting your element onto the slot
grid, is the expensive wrong answer.

The tooltip is positioned relative to the `pointer` transform (~357077) — it is
**cursor-anchored**, so the selected element's own transform position is
irrelevant and an off-screen proxy element works.

**Stat lines need a `SlotUIBase` instance.**
`SlotUIBase.GetHoverStats(ContainedObjectsBuffer, bool, bool)` (~327477) is an
**instance** method. A bare `new GameObject().AddComponent<MySlot>()` throws an
NRE inside `SlotUIBase.Awake` on `animator.enabled`; giving the subclass an
empty `Awake` body (see [subclassing a CK UI component](#subclassing-a-ck-ui-component)) fixes it, and the helper
then returns title, description and stats correctly **without** `base.world` and
without any of the serialized slot fields — verified by spike: a coin gave title
and description and correctly no stats, a Copper Sword gave `statLines = 2`. The
helper needs no prefab instantiation at all.

### Icons are not scaled to fit — the slot is sized around them

`Sprite.bounds.size` and `Sprite.rect` always report the **full sprite rect**,
never the tight visible bounding box. Any "fit to visible content" scale
computed from `bounds` therefore shrinks a padded 40×40 icon to a dot. CK's own
inventory slots do not scale at all: slot background and rarity border are
**1.25 u** (20 px at PPU 16), and the icon renders inside at native scale.
(`ItemBrowser`'s `ApplyObjectIconTransform` *does* apply a scale-to-fit; that
half of it is a dead end for padded sprites.)

Position the icon with

```csharp
icon.transform.localPosition = objectInfo.iconOffset;
```

**`iconOffset` is slot-relative**, so the icon transform must be a **child of
the slot**. As a sibling, the assignment discards the slot position and snaps
the icon to the row origin.

## Adding an entry to the options menu

There is **no API for this** — not in the SDK, not in CoreLib. You clone
vanilla's own menu objects with Harmony. Three classes matter:

| Class | Role |
|---|---|
| `RadicalMenu` | a menu screen; `Awake()` auto-discovers its rows |
| `RadicalOptionsMenu` | the options screen specifically |
| `RadicalMenuOption` | one row; subclass it for your own widgets |

`RadicalMenu.Awake()` collects rows with
`GetComponentsInChildren(includeInactive, menuOptions)`, so any
`RadicalMenuOption` sitting under the menu at `Awake` time is registered
automatically. That single fact dictates *when* you must inject.

**A row already has a second text field.** `RadicalMenuOption`
(`Pug.Other:343031`) declares `labelText` (`:343056`) **and** `public PugText
valueText` (`:343058`) — the latter is what CK uses for the right-aligned value
of a toggle row. Where it is wired, a value or badge suffix costs no prefab, no
new GameObject and no layout, only a string. Whether it is wired on a
*particular* row is a per-row question: check the extracted prefab before
building on it.

**Do not persist through `PrefsManager` / `PrefsData`.** `PrefsData` is a fixed
`[Serializable]` class of hardcoded vanilla fields with no slot for mods;
writing to it risks corrupting the player's `prefs.json`. Keep your own file —
see [storing configuration and state](persistence.md).

### The three patches

```text
1. MenuManager.Init          PREFIX   add your entry to the options menu PREFAB
2. MenuManager.Init          POSTFIX  instantiate your own menu screen
3. RadicalMenu.TypeToMenu    PREFIX   resolve your invented menu id to it
```

**Patch 1** clones the vanilla "Go to UI settings" row — a
`RadicalOptionsMenuOption_PushMenu` — out of `MenuManager.optionsMenuPrefab`, and
repoints its `menuToPush` at an id of your own.

**Patch 2** instantiates the mod's own AssetBundle prefabs — the settings screen
and the list-detail screen, each via `Object.Instantiate(prefab,
Manager.camera.uiCamera.transform)` then `SetActive(false)` — rather than
cloning a vanilla menu. The title is not set here; the screen renders it later,
itself, from `Populate()`. `MenuManager.Init` itself does `optionsMenu =
InstantiateMenu<RadicalMenu>(optionsMenuPrefab)`; `optionsMenuPrefab` is a
public `GameObject` field and `optionsMenu` a public property with a private
setter.

**Patch 3** is the mechanism that makes an invented id work. `MenuType` is a
normal enum, so you cast an integer far outside its range and intercept the
lookup:

```csharp
static bool Prefix(RadicalMenu.MenuType type, ref RadicalMenu __result)
{
    if ((int)type != MyMenuId) return true;   // run the original
    __result = _myMenu;
    return false;
}
```

Pick an id no other mod uses. `1493` (General Mod Config Menu), `19901`
(HealthBars) and `29314` are known to be taken, and `29314`/`29315` (a settings
menu and its drill-in screen).

**Trap: patch the prefab, not the live menu.** Adding your row to the already
instantiated `Manager.menu.optionsMenu` in a postfix is too late —
`RadicalMenu.Awake` has run, your row is not in `menuOptions`, and it renders as
a visible but unselectable entry. Inject into the *prefab* from the `Init`
prefix instead.

### Traps when cloning menu objects

**`Object.Instantiate(gameObject, parent)` threw an NRE when cloning a menu
option row.** The likely explanation: the two-argument overload activates the
clone mid-clone inside `Internal_CloneSingleWithParent`, so `OnEnable` and
`PugTextEffectMenuOption.ResetEffect` would fire before the row's `PugText`
component has been cloned. That internal call sequence is not checkable from
the decompile, and CoreLib itself uses this same overload without trouble, so
treat it as a hazard observed on this row shape rather than a blanket property
of the overload. Clone **parentless** and reparent afterwards, which sidesteps
it either way:

```csharp
var clone = Object.Instantiate(originalTransform);   // no parent argument
clone.SetParent(targetParent, worldPositionStays: false);
```

**On a prefab, use `PugText.SetText`, never `PugText.Render`.** This is the
"red twin". `Render` *builds glyph `SpriteRenderer`s*. Called on the shared
`optionsMenuPrefab` — a prefab asset, `gameObject.scene.IsValid() == false` —
those glyphs are baked into the asset. `MenuManager.InstantiateMenu` then clones
them into the live menu as **orphans**: they are not in the clone's `pt.glyphs`
list, so `PugText.Clear` and every re-render ignore them. They persist forever,
frozen at the language and colour they were rendered with — and because
`PugTextEffectMenuOption` had not yet coloured them, that colour is the dark red
`UNSELECTABLE_TEXT_COLOR`. While the mod was unlocalised the frozen glyphs
overlapped the fresh render perfectly and nobody noticed; the moment the live
entry rendered a *different* language, the frozen English copy showed up as a
dark red duplicate.

`SetText` only assigns `textString` and creates zero glyphs, leaving the prefab
row an unrendered template. **Every vanilla options row is an unrendered
template with `glyphs.Count == 0` — match them.** Diagnostic note: orphaned
glyphs belong to no live `PugText`, so `FindObjectsByType<PugText>` and
`pt.glyphs.Count` cannot see them. Only looking at the screen reveals them.

**Do not fight the colour.** A menu row's label colour is owned by
`PugTextEffectMenuOption`, which exposes public statics:

| Static | Value |
|---|---|
| `UNSELECTED_TEXT_COLOR` | `(0.5, 0.5, 0.5, 0.725)` |
| `SELECTED_TEXT_COLOR` | `(0.647, 0.792, 0.855, 1)` |
| `UNSELECTABLE_TEXT_COLOR` | `#6C2C2F` |

Set your row's resting colour to the `UNSELECTED_TEXT_COLOR` constant (reading
the static is sandbox-legal) and let the effect drive hover.

**The effect is wired by GameObject, not by `labelText`.** `PugTextEffect.Awake`
binds `_text = GetComponent<PugText>()` (`Pug.Other:348885`) — the text on its
*own* GameObject — and `RadicalMenuOption.Awake` collects the effects with
`GetComponentsInChildren<PugTextEffectMenuOption>(includeInactive: true)`
(`:343152`). Where the option's `labelText` / `valueText` fields point therefore
has no bearing on what is tinted: any text under the row that carries an effect
component is driven, and one that does not carry it is not, however the fields
are wired. The natural assumption — that `labelText` is the field the effect
follows — is wrong in both directions, and it matters when you build a custom
row that keeps its caption somewhere other than `labelText`. (Those fields do
decide something else: whether `InitClickCollider` builds a click collider at
all — see [the text-row section](#a-text-row-in-a-menu-radicalmenuoptiontextinput).)

**The prefab's filename drives the root GameObject's name.** Unity's
`PrefabImporter` syncs the root `m_Name` to the file name on import, so editing
`m_Name` in the YAML is reverted at build time. Rename the *file* (and its
`.meta`, which preserves the GUID). This matters because a prefab named
identically to a vanilla one produces two indistinguishable `Foo(Clone)` objects
under `uiCamera`.

**Auto-layout exists — use it.** `LinearLayoutUIComponent` is CK's vertical
stacker: `RenderUIComponent(true)` plus `GetUIComponentRenderHeight()` replaces
hand-rolled box positioning. A scrollable own menu is `: RadicalMenu,
IScrollable` with a `UIScrollWindow` alongside.

**But build and render are two steps, in that order around
`base.Activate()`.** `LinearLayout` skips children that sit in an inactive
hierarchy and computes their heights as `0`. So an own menu screen builds its
structure **before** `base.Activate()` and renders the layouts **after** it,
innermost first. Do it in one pass and every box collapses to zero height.

**Its three spacing fields are in PIXELS, including the two `float` ones.**
`gapBetweenItems` (`int`), `paddingStart` and `paddingEnd` (both `float`) are each
multiplied by `0.0625f` — one sixteenth, the units-per-pixel of CK's UI — before
they reach a position. A `float` field invites reading it as world units, which
would be sixteen times too much.

**A child taller than its layout slot overhangs it, and only the ends of the
list notice.** Slot heights usually come from measured content (a text height),
while a decoration drawn in that slot — a frame, a background — has its own
fixed size. If the decoration is the taller one it spills past the slot,
symmetrically when `WrapperUIComponent.pivot` is `MiddleLeft`, downward only
when it is `TopLeft`. Between children the spill lands in `gapBetweenItems` and
is invisible. At the **first and last** child there is no gap but the edge of
the scroll viewport's [`SpriteMask`](#clipping-with-a-spritemask), so with `paddingStart`/`paddingEnd` at their
default `0` the outermost pixels are clipped away.

The symptom is therefore *the first row's top and the last row's bottom look cut
off, while every row between them is fine* — and the fix is padding, not a taller
slot: the overhang is normal, the missing breathing room at the container's edge
is not. Enlarging every slot to contain its decoration would stretch the whole
list to solve a problem that exists at two rows.

### Reusing CK's "restart required" dialog

CK's own confirm dialog, localised in every language and wired to a real
relaunch, is reachable without shipping a dialog or a translation of your own:

```csharp
Manager.menu.centerPopUpText.StartNewDisplaySequence(
    "Menu/RestartToApplyModChanges",
    /* … */
    localize: true,
    TextManager.FontFace.boldMedium,
    response => { if (response.IsConfirm) Manager.platform.Restart(); },
    new List<string> { "cancelDialogue", "yes" },
    /* … */);
```

**Trap: this is a menu-stack push, and pushing out of a pop orphans the
buttons.** `StartNewDisplaySequence` → `ShowPopUpMenu` → `PushMenu(POP_UP)`.
Called from inside `RadicalMenu.Deactivate` it runs *within* the pop: the popup
never pops, and its Cancel/Yes buttons then survive across every later menu, all
the way into the main menu. An Editor build does not show this — only the game
does. CK itself sidesteps it with `Invoke("RestartToApplyModChanges", 0.1f)`;
the delay is the whole point, and a frame countdown out of `IMod.Update` does
the same job.

### Localising menu strings

Menu labels come from `TextDataBlock` assets, one per language, and `PugText`
resolves terms out of them — but the game-wide CSV shadows them at runtime, so
editing a `TextDataBlock` and seeing no change is the expected outcome rather
than a bug; see [localisation](localisation.md). In code the lookup is:

```csharp
API.Localization.GetLocalizedTerm(term) ?? term
```

Two behaviours to know about, because they pull in opposite directions:

- **The cloned options-menu entry relocalises natively.** It inherits
  `localize = true` from the vanilla row it was cloned from, and CK re-renders
  it on language change by itself. No `OnLocalizeEvent` hook is needed.
- **Everything inside your own menu should not.** Screen title, section hints
  and widget values are best rendered with `localize = false` and a
  pre-resolved string, because the menu re-populates on every open anyway and
  widget values are computed strings rather than single terms.

The inherited `localize = true` also means a **missing term renders as
`missing: <term>` in red**. The file format and merge behaviour that decide
whether a term exists at all are in [localisation](localisation.md).

## Text rendering and text input

### A non-zero `maxWidth` can crash on a character its face does not map

`PugFont.Render` enters `AddNewLinesToLinesExceedingMaxWidth` only when
`maxWidth > 0f`. Inside it, the kerning lookup at `Pug.Other:350905-350917`
(`kerning[cp]`) is unguarded — neither `num5 < glyphData.Length` nor
`cp < kerning.Length` is checked, unlike the twin lookup inside `PugFont.Render`
itself (`:350634-350646`), which carries both guards. `cp`/`num5` land outside
the current face's tables when the character is one the face does not itself
map — `thinTiny`'s 118-cell charset has no German `ä/ö/ü/ß`, for instance — and
the lookup falls through to a **fallback font**'s glyph data (`GetGlyphData`,
`:350973-351021`) at an index the current face's arrays were never sized for.
It only bites a **kerning-enabled** face: `Font5.asset` is one of only three
shipped faces with `enableKerning: 1`. Neither "overflow" nor "one unbreakable
token with no preceding break" survives a code read as the trigger — the
no-preceding-break case is exactly the branch the method handles (`num3 == 0`
and `num2 == num` take the `text.Insert(i, "\n")` branch; `text[num3 - 1]` is
reached only once `num3 >= 1`). The code path is verified; a runtime crash was
not reproduced this round. The fix stands regardless: `PugText.maxWidth = 0f`
on every single-line label, **before** `Render`.

**The symptom points nowhere near the cause.** The throw happens inside
`ShowUI()`, so CoreLib never reaches the point where it sets `currentInterface`:
the window opens but cannot be closed with ESC or E, and world input leaks
through it.

### Text input: `TextInputField`

CK ships `TextInputField : UIelement, InputManager.TextInputInterface`
(`Pug.Other.dll`). **uGUI's `InputField` is the wrong abstraction and unusable
here.** Subclassing `TextInputField` inherits PugText rendering (`pugText` /
`hintText`), the blinking caret (a `CharacterMarkBlinker` whose single
serialized field `sr` is the caret `SpriteRenderer`), click-to-focus
(`OnLeftClicked` calls `Manager.input.SetActiveInputField(this)`) and WASD
suppression.

Five details you must handle yourself:

| Detail | Why |
|---|---|
| **set** the serialized `trim` to `0` — CK's default is `true` | `AppendString` runs `s.Trim()` over the frame's `Input.inputString`, so with the default a typed space is trimmed to nothing and never arrives at all |
| set `dontDeactivateOnDeselect = true` | CK selection is hover-based, so the moment the cursor leaves the collider `OnDeselected` → `Deactivate` fires and typing stops |
| call `Deactivate(false)` when you close | otherwise **WASD stays blocked after the window is gone** |
| clear `maxWidth` from code, not the prefab | `Awake` sets `pugText.maxWidth = maxWidth + (dontAllowNewLines ? 1 : 0)`, forcing the crash path above — a prefab `maxWidth = 0` stays `0` (a no-op) only while `dontAllowNewLines` is off; with it on, `Awake` turns `0` into `1` |
| put the caret `SpriteRenderer` on a **child** GameObject | `Update()` re-asserts `characterMarkBlinker.transform.position = pugText.position` (world X/Y, Z preserved) every frame, clobbering any offset on the caret GameObject itself; a child at a constant `localPosition` inherits the per-frame position and adds the nudge |

Because [hover drives selection](#how-uimouse-picks-and-selects-an-element), three further rules apply to any field inside a
menu:

- **Never commit the value from `OnDeselected`** — it fires on mere hover. The
  usable signal is the transition of `Manager.input.activeInputField`.
- **A guard in `OnLeftClicked` is structurally too late**: CK has already set
  `activeInputField` to null by then (verified with `Debug.Log` against the
  running game).
- Moving the mouse into empty space sets `selectedIndex = -1`, and
  `PugTextEffectMenuOption` then greys the row out **while it is still being
  edited**. No override of yours prevents that.

### A text row in a menu: `RadicalMenuOptionTextInput`

Inside a `RadicalMenu` you do not need `TextInputField` directly.
`RadicalMenuOptionTextInput` is CK's own base class for editable menu rows — the
same one `CharacterCustomizationOption_NameInput`, the character-name field,
uses. Deriving from it gives you the on-screen keyboard for controller sessions,
focus and blink handling, the visual read-vs-edit split, an inherited `readOnly`
field, `GetInputText()`, and `OnActivated → Manager.input.SetActiveInputField(this)`
— no input plumbing of your own.

**Trap: never shadow the inherited `public bool readOnly`.** A same-named field
of your own compiles (with `CS0108`), but CK's internals read the *base* field
and your shadow copy stays `false` forever.

**Trap: `RadicalMenuOptionTextInput.Update()` does not call `base.Update()`.**
So `RadicalMenuOption.UpdateClickCollider()` never runs, and every text row keeps
Unity's default `BoxCollider` — 1×1×1, centred on the origin — no matter what it
contains. Call it explicitly.

**Then widen what it produces.** `UpdateClickCollider()` sizes the collider to
the *rendered text width*, so backspacing shrinks it out from under a stationary
mouse and CK's hover system reacts as though the pointer had left the row. Size
the collider to the maximum row width instead. This second half applies to every
`RadicalMenuOption` whose text changes, not only to text-input rows.

**And beware the empty string, which measures as nothing.** `PugText.Render`
returns early on `string.IsNullOrEmpty(textString)` after setting
`dimensions = Rect.zero` (`Pug.Other:351862`), so anything derived from text
metrics collapses for a blank row: a text-sized collider becomes unhittable by
`UIMouse`'s raycast, and a `renderHeightPixels` computed from
`dimensions.height` makes a `LinearLayout` swallow the row entirely. Keyboard and
controller still reach it, so an in-game check that does not deliberately click
the blank row will not find this. If blank rows are a legitimate state in your
UI, size from a frame sprite or a constant rather than from the text.

**On a controller, ALL text entry goes through the on-screen keyboard — and its
result arrives without a frame boundary.** `HandleTypingInput` takes the OSK branch
whenever `!SystemPrefersKeyboardAndMouse()`, so `AppendString` is never reached
there. The result handler, `UIManager.TrySetInputText`, then does both of these in
**one synchronous callback**:

```csharp
Manager.input.activeInputField.SetInputText(input);
Manager.input.activeInputField.Deactivate(success);
```

Any logic that watches for "the text changed *while* this field was active" will
therefore never fire on a controller: while the keyboard is open the text does not
move, and in the frame it does, `activeInputField` is already null. Watch the
previous frame's ownership as well, or the field silently behaves as read-only for
every controller player while looking editable.

Two details that make this hard to notice: **cancelling** the keyboard is a
different path (no `SetInputText` runs at all, so cancel-shaped tests pass), and
`SetInputText`/`Deactivate` are interface members of
`InputManager.TextInputInterface` implemented **non-virtually** on
`RadicalMenuOptionTextInput` — CK calls them through the interface, so a shadowing
member on your subclass is never dispatched and cannot be used to intercept them.

**`Deactivate(bool commit)` throws its own parameter away.** The implementation is
two lines and never reads it (`Pug.Other:343542`):

```csharp
public void Deactivate(bool commit)
{
    Manager.input.SetActiveInputField(null);
    characterMarkBlinker.gameObject.SetActive(value: false);
}
```

CK's own callers do pass an intent — Escape arrives as
`Deactivate(!IsMenuBackButtonDown())` — and it is discarded on the way in. Two
consequences follow, and neither has a workaround inside your subclass, because
`Deactivate` is a non-virtual interface member (above):

- **Escape is not a cancel.** For every mod built on this base class, backing out
  of a field commits whatever is typed, exactly like Enter. If you need a cancel,
  it has to come from a patch, not from an override.
- **A transition-based commit cannot see intent.** Since the only usable "the user
  is done" signal is `activeInputField` moving away from your row, and the flag
  saying *why* is gone by then, every ending looks the same from inside the row.

**`UIManager.HideAllInventoryAndCraftingUI` ends an edit by blanking it**
(`Pug.Other:273386`):

```csharp
if (Manager.input.textInputIsActive)
{
    Manager.input.activeInputField.SetInputText("");
    Manager.input.activeInputField.Deactivate(commit: false);
}
```

That is the same shape as the on-screen keyboard's result handler above — text set,
then deactivated, in one callback with no frame between — but it means the
opposite, so no timing rule can separate them; only the source of the call can.
This matters because the method has a dozen call sites and most are **world
objects**, not menu actions: `Chest`, `Cattle`, `VendingMachine`, `CraftingBuilding`,
`SignText`, `InstrumentUI`, plus `PlayerController.FadeOutAndLockPlayer` and
`CloseAnyOpenInventory`. In multiplayer the simulation keeps running while a player
sits in a menu, so **another player or a mob can wipe a field mid-edit**. If a
blanked field would cost data, prefix that method and commit first — committing
also clears `activeInputField`, so CK's own `textInputIsActive` guard then finds
nothing and the blanking never runs.

**While a field is active, the menu is deaf.** `HandleTypingInput` returns `true`
on every path (`Pug.Other:269675`), and its caller returns immediately when it does
(`:269555`) — so all menu navigation and activation input is swallowed for as long
as `Manager.input.activeInputField` is set. Useful in both directions: no other row
can be selected or activated by keyboard or controller during an edit (the mouse is
a separate path and is *not* covered), so a rebuild triggered from a menu option
cannot destroy the row that currently holds the field.

**A collider you put in the prefab is NOT the one the option uses.**
`RadicalMenuOption.InitClickCollider()` only ever *creates* one:

```csharp
if (clickCollider == null && (labelText != null || valueText != null))
{
    clickCollider = gameObject.AddComponent<BoxCollider>();
    clickCollider.isTrigger = true;
}
```

There is no `GetComponent` anywhere in the chain, and `clickCollider` is
`protected` with no `[SerializeField]`, so the Inspector cannot fill it either. An
authored collider therefore leaves the field null, a second one gets added beside
it, and `UpdateClickCollider` sizes only the runtime one. Two consequences worth
knowing before copying what the vanilla prefabs appear to do:

- **The vanilla prefabs are not the counter-example they look like.** Every
  interactive option in `Join Game Menu.prefab` ships a collider — and every one of
  those classes (`RadicalMenuOptionTextInput`, `RadicalEnterTextMenu_EnterButtonOption`)
  takes the automatic path, so each of them runs with two. Leftovers, not a
  convention.
- **The real opt-out is overriding both methods empty**, which is what
  `SaveSlotPlayOption` and the `WorldSlot*Option`s do: they carry a hand-sized
  collider for a large tile whose hit area has nothing to do with text metrics, and
  they stop CK from adding or resizing anything. That is the only shape in which an
  authored collider is actually the one in use.

**The automatic path is gated on `labelText`/`valueText` being set.** An option
whose caption lives anywhere else gets **no collider at all** and is silently
unreachable by mouse while keyboard and controller still work. `InitClickCollider`
tries `GetComponent<PugText>()` on the option's own GameObject as a fallback, which
does not help when the text sits on a child.

**Trap: the row's `maxWidth` is a capacity, and a prefab `PugText.maxWidth`
silently disables it.** The two fields share a name and do opposite things:

| Field | Effect |
|---|---|
| `RadicalMenuOptionTextInput.maxWidth` | **capacity** — `AppendString` re-measures after inserting and restores the previous string if the text now exceeds it, and `Update` strips one trailing character per frame while it does |
| `PugText.maxWidth` | **wrapping** — `Render` runs `AddNewLinesToLinesExceedingMaxWidth`, inserting line breaks |

**Neither is a character count.** Both values are a **rendered width in world
units**, and both checks measure `pugText.dimensions.width` — the width the text
actually occupies on screen. `PugFont` carries a per-glyph `kerning` byte array
and an `enableKerning` flag, so the advance depends on the character *and* on the
one before it. How many characters fit is therefore a property of the string, not
of the limit: a row of `1`s and a row of `W`s reach the same width at very
different lengths, and a measurement taken with digits does not transfer to
letters. Size a field by measuring the widest realistic value, never by counting
characters.

Both checks above test `pugText.dimensions.width`. So once the PugText wraps, the
rendered width can never exceed the wrap limit, the capacity comparison never
becomes true, and the row grows *downward* instead of refusing input — overflowing
whatever frame or layout slot it sits in, with no error anywhere.

**Unlike `TextInputField`, this class never propagates its `maxWidth` to the
PugText.** The rule is therefore the exact inverse of the one in the table above:
here the prefab is the only place the PugText's value comes from, and it must be
`0`. CK does this consistently — in `Join Game Menu.prefab` every field's `text`
and `hint` PugText carries `maxWidth: 0` while the capacity lives on the component
(`sessionId` 14.5, `sessionIP` 22, `sessionPort` 2.1, `password` 16). A prefab
adapted from a display-only row is the likely place to inherit a non-zero value by
accident.

Keeping it at `0` also avoids the [kerning crash](#a-non-zero-maxwidth-can-crash-on-a-character-its-face-does-not-map) above, which only exists on the
wrapping path.

**Consequence: an over-long value cannot be entered at all.** With wrapping off
there is no viewport and no scrolling — `localCharacterEndPositions` exists only
to place the caret, and no offset is ever applied. A value wider than the capacity
is silently refused keystroke by keystroke; `Shake()` (inherited, with
`shakeDuration` / `shakeMagnitude` / `shakesPerSecond` already serialized) is the
feedback CK provides for exactly that.

## Rebindable keybinds

CoreLib's `ControlMappingModule` (a submodule, loaded in `EarlyInit`) puts a
real, rebindable action into **Options → Controls → Mods**.

### Always create your own category

```csharp
int catId = ControlMappingModule.AddNewCategory("MyMod");   // != "Mods"
ControlMappingModule.AddKeyboardBind(
    keyBindName:     "MyMod-ToggleThing",
    defaultKeyCode:  KeyboardKeyCode.F1,
    /* modifiers … */
    categoryId:      catId);
```

**Trap: `categoryId: -1` gives you a header-less row.** `-1` is CoreLib's
default "Mods" bucket, and CoreLib *deliberately* suppresses that bucket's
sub-header: `AddNewCategory_Internal` sets `_showActionCategoryName =
(categoryName != "Mods")`, on the reasoning that the Controls tab is already
called "Mods" and a redundant sub-header would be noise. The consequence for you
is a loose row at the top of the tab with no mod name and no description. Any
named category other than `"Mods"` gets the header. CoreLib migrates an
already-persisted action into the new category on load via
`ChangeActionCategory`, so switching later is safe.

Actions created this way get an id `>= 1000` and live in a mod-owned `player`
category. Poll them by name:

```csharp
ReInput.players.GetPlayer(0).GetButtonDown("MyMod-ToggleThing");
```

`AddControllerBind` and `AddMouseBind` with the **same name** extend that one
action onto other devices.

**Trap: do not mirror the key into your own config file.** Storing a
`KeyboardKeyCode` / `ModifierKey` in a `.cfg` just to seed
`ControlMappingModule.AddKeyboardBind(...)` looks tidy and is an anti-pattern:
after the seeding, the Controls menu (Rewired) is the sole authority. The moment
the player rebinds there, the config value has no effect at all — a silent
contradiction between two surfaces the player can both see. Pass the literal
straight to `AddKeyboardBind` and keep the key out of the config; QuickToolSwap
does it that way.

### The localisation terms CK derives

`ControlMappingMenu.GetCategoryLabelLocaKey(name, getName)` returns
`"ControlMapper/" + name + (getName ? "Category" : "Description")`. So for a
category named `MyMod` you ship three terms under a `ControlMapper:` namespace:

| Term | Renders as |
|---|---|
| `ControlMapper/MyModCategory` | the section header |
| `ControlMapper/MyModDescription` | the section subtitle |
| `ControlMapper/MyMod-ToggleThingPC` | the action's row label |

The `PC` suffix is the keyboard/mouse variant of the action name. Note that the
description is a **category-level** label (CoreLib's own reads "Core Library
Commands"), not per-action — it stays correct as you add more binds.

### An unbound default renders the literal "None"

`AddKeyboardBind` always calls `keyboardMap.AddNewActionElementMap(..., keyCode:
defaultKeyCode)`; there is no branch that skips it for `KeyboardKeyCode.None`.
So a bind you registered as "unbound" still owns an `ActionElementMap`, and CK
renders that map's `elementIdentifierName` — the string `"None"`. A genuinely
unbound CK action has **no map at all**, and `ControlMappingMenu`'s setup loop
simply renders nothing for it.

The fix is to delete the forced None-map from the player's live maps on each
`rewiredStart` — idempotent, because CoreLib re-seeds it every `EarlyInit`:

```csharp
var action = ReInput.mapping.GetAction("MyMod-ToggleThing");
var maps = new System.Collections.Generic.List<ActionElementMap>();
rewiredPlayer.controllers.maps.GetElementMapsWithAction(action.id, false, maps);
foreach (var aem in maps)
    if (aem.controllerMap != null
        && aem.controllerMap.controllerType == ControllerType.Keyboard
        && aem.keyCode == KeyCode.None)   // UnityEngine.KeyCode, NOT Rewired.KeyboardKeyCode
        aem.controllerMap.DeleteElementMap(aem.id);
```

**Trap: `ActionElementMap.keyCode` is a `UnityEngine.KeyCode`.** Rewired's
`KeyboardKeyCode` is a *different* type; comparing the two is a `CS0019` compile
error. The `Keyboard` + `keyCode == None` guard never removes a real rebinding:
a real keyboard bind has a non-`None` keyCode, and a mouse or controller
rebinding is a different `controllerType`.

### What is stored where, and by whom

Three independent layers make a CoreLib bind work, all under CoreLib's
`ControlMapping/`:

1. The action and its `ActionElementMap` go into **Rewired's `UserData`** —
   this is what makes the bind functional and rebindable.
2. A `CategoryLayoutData` entry is appended to CoreLib's shared
   `modCategoryLayout` — the data behind a *visible* section, added only when
   the category is newly created.
3. A Harmony **prefix on `ControlMappingMenu.Initialize`** injects
   `modCategoryLayout` into CK's `_mappingLayoutData`.

All three still work in game 1.2.1.5, so a "my row is missing" symptom is almost
never a broken patch — check the header-suppression rule first.

CoreLib persists its own registries as JSON in the game config filesystem under
`mods/CoreLib/`:

| File | Contents |
|---|---|
| `KeyBindsCategories.json` | `{"Mods":[100,100],"CoreLib":[101,101],…}` |
| `KeyBindsActions.json` | `{"MyMod-ToggleThing":[actionId, categoryId], …}` |

Renaming an action leaves an orphan entry under the old name; it is harmless as
long as it has no element map, since nothing renders it. Both categories and
actions are re-logged each launch (`[Core Library - Control Mapping]: Added New
Category/Action: …`); a category logged without a `(Disabled)` suffix was
created user-assignable.

## The menu hint bar

The footer strip that reads "Navigate / Select / Back" is `MenuHelperButtons`, a
singleton on the menu manager. It is **not** the gameplay `InGameButtonHintsUI`.
It is refreshed **every frame** from `RadicalMenu.GetHelpButtonsToShow()`,
evaluated against whichever option currently has focus — so it genuinely is
per-selection contextual, and CK's own `RadicalPopUpMenu` and
`ControlMappingMenu` drive it that way. The hooks are:

- `RadicalMenu.UseCustomHelpButtons` — override to `true`
- `RadicalMenu.GetHelpButtonsToShow()` — return the set to display
- `RadicalMenu.OnSelectedOptionChanged()` — an empty `virtual`, yours to use

**Trap: the vocabulary is a closed enum and you cannot extend it.**

```csharp
enum HelpButtonTypes { NAVIGATE, SELECT, BACK, REFRESH, OPENPROFILE, RESET_DEFAULTS, CALIBRATE }
```

Each of the seven maps to a serialized GameObject slot carrying a **baked
per-platform glyph**. There is no clean way to add an eighth.

**But one of the seven is unclaimed.** `RESET_DEFAULTS` is fully wired and never
used: `MenuHelperButtons.Awake` registers it in `helpButtonToGameObject`
(`Pug.Other` ~338892) with a complete `HelpButton` — a `root` GameObject, an
`InputDependentSprite` and a `description` `PugText` carrying `textString:
Menu/Reset` with `localize: 1`, a term that exists in `I2Languages.asset`. No
vanilla menu ever asks for it: the only two mentions of `RESET_DEFAULTS` in the
whole of `Pug.Other` are the enum member and that registration, and no other
assembly names it either. So if your prompt *means* what the slot is named,
request it and take the per-platform glyphs and the translation for free.

When no slot fits your prompt — "[Y] Toggle view" and the like — **roll your
own hint object**: a `PugText` plus a sprite, parented under your own menu,
toggled with `SetActive` from `OnSelectedOptionChanged`. What you must not do is
repurpose a slot whose label means something else: the text is vanilla's, and
your prompt breaks the moment CK decides to request that slot itself.

**Trap: never call `base.GetHelpButtonsToShow().Add(...)`.** The base
implementation returns `Manager.menu.defaultHelpButtons` only when
`CanActivateCurrentOption()` is true — a **public field on the menu-manager
singleton**, and the very list instance the default path hands to every other
menu — and the menu's own private `helpButtonsNoSelect` otherwise. A single
`Add` on the shared list therefore mutates global state permanently: from the
first time your UI opens, the pause menu, the options menu and the main menu
all show your extra prompt, and the damage outlives your menu. Copy whichever
list you get before you touch it. `MenuHelperButtons.UpdateShowingButtons` stores the
reference it is handed and compares the next frame's list against it with
`SequenceEqual`, so an in-place edit is invisible to that check and the bar
stops refreshing as well.

## Which input actions you can use inside a menu

**Take `OpenProfile`, Rewired action id `223`.** Of the menu face-button
actions it is the only one vanilla never evaluates anywhere. The id appears
twice: its `RewiredConsts` definition (`Pug.Other:386497`), which is how you
reach it, and a single evaluation inside
`InputManager.IsOpenProfileButtonDown()` (`:267304`) — and *that* method has
zero callers in the whole decompile. Nothing collides with you.

**`MenuSecondaryActivate`, action id `221`, is the fallback.** It is free inside
a normal settings menu, but not unpolled: `ModIOBrowserInputCapture` reads it
(`~269987`) to fire `InputReceiver.OnAlternate()` while the mod.io browser has
focus. Use it when 223 is taken.

Both are category `"Menu"` and both are `RewiredConsts.Action` constants in
`Pug.Other`; `221` is additionally mirrored as
`CoreKeeperInput.Action.MenuSecondaryActivate` in `PugMod.SDK.Runtime`. Both
are bound by default to a controller face button, and polled the same way:

```csharp
Manager.input.GetButtonDown(223);
```

**Which physical button that is depends on the controller map — measure, don't
assume.** The binding is per controller template, not one global mapping: in the
shipped Rewired Input Manager asset, action `221` binds to
`_elementIdentifierId: 7` in two maps and to `5` in a third. So a hint that
names a face button ("[Y] Toggle view") is only right for the template you read
it off; if the label matters, read the element back at runtime rather than
hardcoding it.

**Controller only.** Neither action has a keyboard default, and you cannot give
one through the Controls screen: their category `"Menu"` is tagged `_tag: system`
with `_userAssignable: 0` in the Rewired Input Manager asset, and category
gating wins even though the action itself is marked `_userAssignable: 1`.

**The general rule: only `player`-tagged Rewired categories are rebindable.**
Every `system` category — `Menu`, `Debug`, `ControlMapperUI` — is effectively
read-only for mods and hidden from the Controls screen. You *can* write a
keyboard default onto 221 directly through Rewired's `UserData`, but the result
is invisible, non-rebindable, global and of uncertain persistence.

**The clean keyboard path is therefore a CoreLib action** (see above): a new
action in a mod-owned `player` category, visible and rebindable in Controls.

## Scrolling

### Wiring a scroll window

`UIScrollWindow` handles **scrolling only — not clipping.** Rows will render
past the window edge until you add a `SpriteMask` yourself — see [clipping with a `SpriteMask`](#clipping-with-a-spritemask).

**Trap: `UIScrollWindow.scrollable` is the public serialized field.** Do not
confuse it with the private `_scrollable`. `UIScrollWindow.Awake()` reads
`scrollable` directly, copies it into `_scrollable` itself and, if it is null,
sets `base.enabled = false` permanently — the window is dead for the rest of its
life. A `LogError` names the cause — the test is whether the object implements
`IScrollable`, not whether it is null. Wire your `IScrollable` implementor into
that slot in the Editor, or in the prefab YAML as `scrollable: {fileID: <your
MonoBehaviour id>}`. Setting the private field later via reflection does not
help; `Awake` has already disabled the component. And because `Awake` does that
copy, a mod never needs to write `_scrollable` at all: the older three-call
pattern (reflect `_scrollable` into place, `UpdateScrollHeight`,
`SetScrollValue`) collapses to two calls.

**`UpdateScrollHeight` is private, and must run before you reposition.** It computes
`scrollHeight = <full content height> − scrollWindow.windowHeight`, and it is
private, so a mod invokes it via `API.Reflection.Invoke` over a member resolved
through `GetMembersChecked()`/`GetNameChecked()` — the sandbox-legal reflection
surface, detailed in [the load-time sandbox](sandbox.md). After **any** change to what your
`IScrollable` reports — row count, row height — the sequence is
`UpdateScrollHeight` **first**, then the reposition. The staleness is not
lasting: `UIScrollWindow.LateUpdate` calls `UpdateScrollHeight()` itself every
frame, immediately before `UpdateScroll()`. But it lasts for the frame your own
call runs in, and everything that reads `ScrollHeight` in that frame works off
the old content height — `SetScrollValue(t)` for any `t` between the ends,
`MoveScroll`'s clamp to `[minScrollPos, ScrollHeight]`, and the scrollbar's
`VisibleRatio`. `ResetScroll()` is the one call that does not care: it is
`SetScrollValue(1f)`, and the lerp lands on `minScrollPos` whatever the height
says. A virtualising list changes its reported height on every open, so this
sits on the hot path.

**Trap: `SetScrollValue(t)` runs backwards from expectation.** It is a lerp
anchor where `t = 0f` is scroll-**bottom** (`ScrollHeight`) and `t = 1f` is
scroll-**top** (`minScrollPos = 0`). `ResetScroll()` is the explicit reset API
and calls `SetScrollValue(1f)`.

**`windowHeight` must equal the mask's height.** `windowHeight` is the scroll
*mathematics* view of the viewport (`ScrollHeight = GetCurrentWindowHeight() −
windowHeight`); the mask is the *visual* clip. When they disagree the list
scrolls too far or not far enough at the end. Flush edges need both: align the
mask's top edge with row zero's top edge (that is the mask's *position*, not
`windowHeight`), and set `windowHeight = maskHeight` for the bottom. Growing a
centred mask upward only means `scale.y += X` **and** `localPos.y += X/2`.

A working scrollbar is pure prefab wiring — no code beyond instantiating the
components:

| Component | Required fields |
|---|---|
| `ScrollBar : UIelement` | `scrollWindow`, `root` (GameObject, self-shown), `background` (the track `SpriteRenderer`), `handle` |
| `ScrollBarHandle : ButtonUIElement` | `handleSpriteRenderer`, `handleCollider` (a `BoxCollider` for the click), `handleSpritesToResize` |

`ScrollBar.Update()` does the rest itself: shows `root` while `ScrollHeight >
0`, converts a drag to `scrollWindow.SetScrollValue`, and sizes the handle to
`max(VisibleRatio * background.size.y, MIN_HANDLE_SIZE)` with `MIN_HANDLE_SIZE =
0.625`. **`UIScrollWindow.scrollBar` must point back at the component** or the
whole thing is a no-op; `autoHideScrollbar` hides it at `VisibleRatio >= 1`. The
optional arrow slots (`arrowUp`, `arrowUpInactive`, `arrowDown`,
`arrowDownInactive`) may stay at `fileID: 0`. Mouse-wheel scrolling works
without any scrollbar at all — the bar is purely the visible affordance.

**Trap: `ButtonUIElement.LateUpdate` toggles GameObject *activity* every
frame**, and the wrong list makes your button vanish. Everything in
`spritesShownUnpressed` is set active while `!leftClickIsHeldDown`, everything in
`spritesShownPressed` while it is held — and the pressed loop runs **last and
wins**. A GameObject listed in *both* is therefore visible only while the button
is held down; at rest the button appears to have no sprite, with no diagnostic
signal whatsoever. For a single always-visible sprite leave **both lists empty**
and let the owning component render it, and put a hover/selection border in
`optionalSelectedMarker` instead, toggled by `OnSelected` / `OnDeselected`. This
holds for `ScrollBarHandle` and for every other `ButtonUIElement` subclass.

### Clipping with a `SpriteMask`

Clipping in CK's sprite UI is a `SpriteMask` with a **Custom Sorting-Layer
Range** on the `"GUI"` layer. Five preconditions, each of which silently breaks
the clip when violated — the first four by clipping nothing, the last by
clipping almost everything:

| Precondition | What goes wrong |
|---|---|
| every renderer has `maskInteraction = VisibleInsideMask` | the default `None` ignores every mask there is — see [when a renderer is clipped](prefabs-and-rendering.md#a-renderer-is-clipped-only-when-three-conditions-hold) |
| every renderer in the region is already on `"GUI"` | one left on `"Default"` is not clipped at all |
| every renderer's `sortingOrder` falls inside the band | outside the band it is not clipped |
| `PugText` needs `style.orderInLayer` set; `sortingLayer` defaults to a sentinel that already resolves to `"GUI"` | the prefab keys are `sortingLayer:` / `orderInLayer:` — **not** `m_SortingLayer` / `m_SortingOrder`, which are `SpriteRenderer` keys and are silently ignored on a `PugText` |
| the mask sprite's `.meta` needs `spritePixelsToUnits: 1` | at CK's default of 16 a 1×1 white PNG is 0.0625 units, so a Transform scale of (11, 6) yields a 0.69 × 0.375 mask, which clips almost everything |

`PugText` has a `SetOrderInLayer` method but **no** sorting-layer setter — assign
`style.sortingLayer` directly, it is a public field.

Building the mask sprite at runtime with `Texture2D` + `Sprite.Create` does not
get you out of the layer requirement: the sprite is not the problem, the render
domain is.

**A mask clips sprites, never colliders.** A row scrolled out of the viewport
still hover-selects from the surrounding chrome if its collider reaches past the
visible area, so a viewport bounds check has to be explicit.

### Mouse-wheel ownership

`UIScrollWindow.UpdateScroll` — called from its own `LateUpdate` — reads the
wheel **independently**, via `Manager.input.GetScrollValue()`. Whether the
cursor's position matters at all is gated by a serialized
`cursorMustBeInsideWindowToScroll` field that **defaults to false**, and every
prefab in this family ships it off — so by default the window consumes the
wheel no matter where the cursor is, which makes the prefix below *more*
necessary, not less. When the flag is on, the position check is
`IsMouseWithinScrollArea()`, a `Rect.Contains` test, not `Bounds.Contains`. An
overlay your mod draws on top of a scroll window therefore scrolls the list
underneath as well.

Take the wheel with a Harmony **prefix on `UIScrollWindow.UpdateScroll`**
returning `false` for the frames your overlay owns it, and compute that
condition fresh inside the prefix so no `LateUpdate` ordering can make it stale.
Harmony lives in trusted `0Harmony.dll`, so the patch is sandbox-clean. A
collider-free way to decide whether the cursor is over your overlay is in [hit-testing without a collider](#hit-testing-without-a-collider).

### Following the selection

`RadicalMenu` moves `selectedIndex` through `menuOptions` on navigation but does
**not** scroll. Every vanilla scrollable menu wires that itself, and so must
yours. Two idiomatic hooks:

- **Central**: override `protected virtual RadicalMenu.OnSelectedOptionChanged()`,
  which is called from `SelectOptionIndex` immediately after
  `menuOptions[i].OnSelected()`. One override covers every option type — prefer
  this.
- **Per-option**: override `UIelement.OnSelected()` and call
  `scrollWindow.MoveScrollToIncludePosition(pos, padding)`. This is what
  vanilla's character select, world select, cookbook, dropdowns and stats
  screens do.

**The position is the row's position in `contentRoot` (scrollingContent) local
space, pivot-corrected.** CK's canonical
`UIComponentMonoBehaviour.ScrollIntoView` computes `transform.position.y -
scrollingContent.position.y` — a world delta, valid because UI scale is 1 — and
then, if `GetUIComponentPivotPosition() == PivotPosition.TopLeft`, subtracts
`height / 2` to arrive at the **centre**. `PivotPosition { TopLeft, MiddleLeft
}` is nested in `UIComponentMonoBehaviour`, and `WrapperUIComponent.pivot` is
the authority on which one a given row uses (list rows tend to be `TopLeft`,
ordinary rows `MiddleLeft`).

For **nested** rows — row inside box inside section inside `contentRoot`, deeper
than vanilla's one-level menus — sum `localPosition.y` up the parent chain
instead of using the world delta.

Coordinates to keep straight:

| Quantity | Convention |
|---|---|
| Content `y` | `0` at the top (`minScrollPos`), `+ScrollHeight` when scrolled down |
| Window top | `0` |
| Window bottom | `-windowHeight` |

**Gate the whole thing on the mouse.** Skip the scroll when
`Manager.input.SystemIsUsingMouse()` returns true — this is what CK's own
`ScrollIntoViewIfNotUsingMouse` does, and without it hover-selection jumps the
page under the player's cursor. Keyboard and controller navigation leave the
flag false. `MoveScrollToIncludePosition` self-gates internally to keyboard
menu-up/down and controller input, but a direct `MoveScroll` does not — gate it
explicitly.

### Rows taller than the window

`MoveScrollToIncludePosition(centre, height / 2)` includes an element **fully —
but only if it fits the window.** It keeps the given point inside
`[-windowHeight + padding, -padding]`. A padding larger than `windowHeight / 2`
**inverts** that band, and the scroll overshoots, pushing the very label you
wanted to show off screen.

So for a row taller than the viewport — a large list widget, say — pin its top
edge just under the window top with a direct `MoveScroll` instead:

```csharp
float delta = -margin - (contentRoot.localPosition.y + topEdge);
scrollWindow.MoveScroll(delta);
```

**Better still: do not build a row taller than the viewport.** CK's menu
navigation works per option, not per pixel — it brings the row's *top edge* into
view and then jumps to the next *setting*, so the middle and bottom of an
over-tall row are unreachable by D-pad. That is a controller dead zone, and its
cause is architectural: a collection value pressed into CK's two-column,
single-value row model. CK's own idiom for a collection is a **pushed,
scrollable sub-menu** — the controls/keybinding screen is exactly that — with
its own `MenuType` id, resolved in the same `RadicalMenu.TypeToMenu` prefix you
already have. The price is that every additional screen brings its own [first-enable cascade](#the-first-setactivetrue-can-cost-a-second).

**Red herring: `IScrollable.IsTopElementSelected` / `IsBottomElementSelected`
have nothing to do with selection-follow.** Both are used only in
`UpdateScroll`'s controller analog-stick free-scroll path, guarded by
`flag = !SystemPrefersKeyboardAndMouse()`, and stubbing them is fine.

**`UpdateContainingElements` is not in that group.** `SetScrollablePosition`
calls it unconditionally, and every scroll write reaches it — from
`UpdateScroll`, `SetScrollValue` and `MoveScroll` alike. CK's own
`ControlMapper` leaves it empty because its list is fully built; a list that
virtualises its viewport has to do its work here, and stubbing it means nothing
ever updates as the user scrolls.

### Long lists: CK ships no recycler

`UIScrollWindow.SetScrollablePosition(S)` sets
`scrollingContent.localPosition.y = S` and then calls
`_scrollable.UpdateContainingElements(S)` **every frame**. That callback is the
official docking point for viewport virtualisation, even though vanilla leaves
it empty: compute `firstIndex = floor(S / RowHeight)`, reposition your pooled
rows to `localPos.y = -(idx * RowHeight)` (they are children of
`scrollingContent`) and rebind them. Guard the per-frame cost with
`if (firstIndex == _lastFirstIndex) return`, and force a rebind by setting
`_lastFirstIndex = -1` on non-scroll triggers (opening the window, data change)
— otherwise reopening at the same index keeps stale bindings.

A virtualising list must report the **full** list height from
`GetCurrentWindowHeight()` (`count * RowHeight`, not the pool size) so the
scrollbar and scroll range reflect the whole data set.

**Trap: `CookBookUI` is not a recycler**, despite looking like the obvious
template. `ItemSlotsUIContainer.InstantiateItemSlots` builds a *fixed* pool of
`MAX_ROWS × MAX_COLUMNS` (the cookbook's is 50 × 5 = 250) once, `UpdateFilter`
bails out at `num >= itemSlots.Count`, and scrolling just slides the entire pool
under the clip mask. Nothing is ever recycled. That is fine up to a few hundred
entries and useless for tens of thousands. Virtualisation is yours to build.

## Options that exist but cannot be changed right now

CK has a shipped convention for this: the whole row — label *and* value — in a
dull red, skipped by navigation, unclickable, but still visible and still
occupying its place in the layout. Vanilla uses it for "Frame rate target" while
V-Sync is on, and for the title-menu-only settings ("Season override",
"Multiplayer connectivity") seen from an in-game pause menu.

```csharp
enum OptionActiveState { INACTIVE, ACTIVE, GRAYED_OUT }
```

It is returned per row from the **virtual**
`RadicalMenuOption.GetActiveStateInCurrentScene()`. One override, one return
value, and four independent effects follow for free:

| Effect | Mechanism |
|---|---|
| Navigation skips the row | `RadicalMenu.SelectNextIndex` / `SelectPrevIndex` walk on while `!IsSelectionEnabled()` — the base implementation is `enabled && gameObject.activeInHierarchy && !ShouldBeGrayedOut()`, not merely the last term |
| The mouse cannot click it | `UpdateClickCollider` enables the collider only for `ACTIVE` |
| It keeps its place in the layout | `GetAllCurrentlyActiveMenuOptions` and `Activate` accept `ACTIVE \|\| GRAYED_OUT`; only `INACTIVE` gets `SetActive(false)` |
| The row turns red | `PugTextEffectMenuOption.UNSELECTABLE_TEXT_COLOR` (`#6C2C2F`), chosen via `IsSelectionEnabled(visualOnly: true)`, applied to the text *and* the effect's `spriteRenderers` |

Two routes in:

- **Imperative** — override the method and consult live state. Vanilla's
  `RadicalOptionsMenuOption_TargetFrameRate` does exactly this against
  `Manager.prefs.vsync`.
- **Declarative** — the prefab flag `visibleButNotSelectableWhenInactive`, which
  makes a scene-mismatched row grey out instead of vanishing.

**Make the red land immediately.** State that changes on a *neighbouring* row
does not repaint the locked row until the next selection change. Vanilla's
V-Sync row calls `ResetEffects()` by hand on its neighbour's label *and* value.

**The convention includes the reason.** `SettingsNotAvailableNote` is a
`PugText` that switches itself on exactly while a named option is `GRAYED_OUT` —
the player gets told *why*, not just that they are locked out. Ship the note
with the lock.

### `INACTIVE` and the phantom row

**Trap: a deactivated GameObject is still a menu row.** `RadicalMenu` collects
its options with `includeInactive`, so a disabled prefab **template** row is
registered like any other and is reachable by D-pad — an invisible entry the
player can navigate onto. The remedy is to override
`GetActiveStateInCurrentScene()` and return `gameObject.activeSelf ? ACTIVE :
INACTIVE`.

The mirror case: an option cloned from an **in-game-only** entry reports
`INACTIVE` on the title screen. A mod widget that should work there has to return
`ACTIVE` explicitly — but gated on the row actually being bound to something,
otherwise the phantom row is straight back.

### Three traps

**`visualOnly` splits optics from control.** `IsSelectionEnabled(visualOnly:
true)` answers "which colour?"; `IsSelectionEnabled()` answers "may navigation
land here?". Vanilla's popup buttons exploit the gap deliberately — input-dead
during the anti-misclick timer, visually normal.

**The skip exists only on the index-based navigation path.** With
`useUIElementsForNavigation`, `SelectIndexInDirection` asks
`GetAdjacentUIElement` *before* the state filter runs, so a locked neighbour
yields no match and navigation **stalls** at the boundary instead of stepping
over it. If your menu navigates via `UIelement` links, the skip is not there and
you must handle it yourself.

**The red comes only from `PugTextEffectMenuOption`.** A menu that hand-tints
its value texts — anything with its own effect paths — gets a half-red row, the
label correctly dull red and the value still in its normal colour, unless it
sets `UNSELECTABLE_TEXT_COLOR` on the value itself.

### `GRAYED_OUT` is not "read-only"

It means *"normally editable, just not right now"*: contextual, and the red
deliberately signals something withheld. A row that is permanently
non-editable — an informational value, a separator, a list entry that only
exists to be read — is a different question, and greying it out both lies to the
player and makes it unreachable by navigation. Keep permanently read-only rows
`ACTIVE` so they stay navigable.
