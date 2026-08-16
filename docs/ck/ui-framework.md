# The UI framework

Core Keeper's interface is not built the way a Unity developer expects. There is
no Canvas, no `RectTransform`, no `Image` — the entire UI is sprites on a
dedicated layer, driven by the game's own `UIelement` hierarchy. This chapter
covers the pattern every UI mod follows, how to mount a window, how to add a row
to the options menu and a rebindable key to the controls screen, what the footer
hint bar will and will not let you do, how to make a scroll window follow the
selection, and how to grey out a setting the player may not change right now.

## Sprite UI, not uGUI

**Do not build with uGUI.** Not one published Core Keeper UI mod uses
`Canvas`, `Image` or `RectTransform` — a survey of published UI mods' prefab
YAML turns up zero occurrences of `Canvas` or `RectTransform`. That is not a
stylistic preference. CK's `UIMouse` resolves pointer input with a **physics
raycast into Layer 5** and therefore only ever finds a `SpriteRenderer` with a
`Collider`. A uGUI hierarchy is invisible to it, and to everything downstream.

The canonical shape of a modded UI object:

| Element | What it must be |
|---|---|
| Layer | `5` (UI) |
| Renderer | `SpriteRenderer` — never `Image` |
| Transform | plain `Transform` — never `RectTransform` |
| Sorting | a custom Sorting Layer plus an explicit `sortingOrder` |
| Root class | `class MyUI : UIelement, IModUI` — inheritance *and* interface |
| Navigation | chain neighbours via `UIelement.bottomUIElements` / `topUIElements` |

The `bottomUIElements` / `topUIElements` chaining is what gives you controller
navigation and correct `UIMouse` integration. An element that is not in the
chain is drawn but not reachable.

Inheriting from `UIelement`, reading `Manager.input` and touching
`API.Rendering.UICamera` are all permitted inside the Roslyn sandbox — see
[the sandbox and mod configuration](sandbox-and-config.md).

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

The prefab it expects: a `ModUIAuthoring` component on the root GameObject, your
`IModUI` component on that **same** root GameObject, and a child GameObject
literally named `root` holding all the actual UI elements.

What you get for free: the window is mounted under
`UIManager.chestInventoryUI.transform.parent`; it hides automatically when
vanilla runs `HideAllInventoryAndCraftingUI`; and cursor, input capture, pause
behaviour and mouse mode all arrive through a postfix on
`isAnyInventoryShowing`, meaning vanilla's own logic does the work.

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
`ItemBrowser` is the complete worked template for this route.

### Sprites and pixel alignment

UI sprites are authored at **pixels-per-unit 16**, and every position snaps to a
**1/16 grid**. CoreLib ships a `PixelSnap` component to enforce it. The import
settings that decide whether your PNG even arrives as a `Sprite` rather than a
`Texture2D` are covered in [prefabs and rendering](prefabs-and-rendering.md).

### Reuse the vanilla window art

You almost never need to draw a background. CK's crafting UI ships finished
nine-slice backgrounds, retrievable at runtime:

```csharp
background.sprite = Manager.ui
    .GetCraftingUITheme(UIManager.CraftingUIThemeType.Wood)
    .background;
```

`Wood` and `Stone` are confirmed enum members (the returned sprites are named
`crafting_ui_hand_NN`; `Stone` is `11`); more themes exist — enumerate them at
runtime if you need one. The call is sandbox-clean, and the theme sprite
**overrides whatever sprite you assigned in the Editor**, so the Editor
assignment is only a design-time preview.

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

**Do not persist through `PrefsManager` / `PrefsData`.** `PrefsData` is a fixed
`[Serializable]` class of hardcoded vanilla fields with no slot for mods;
writing to it risks corrupting the player's `prefs.json`. Keep your own file —
see [the sandbox and mod configuration](sandbox-and-config.md).

### The three patches

```text
1. MenuManager.Init          PREFIX   add your entry to the options menu PREFAB
2. MenuManager.Init          POSTFIX  instantiate your own menu screen
3. RadicalMenu.TypeToMenu    PREFIX   resolve your invented menu id to it
```

**Patch 1** clones the vanilla "Go to UI settings" row — a
`RadicalOptionsMenuOption_PushMenu` — out of `MenuManager.optionsMenuPrefab`, and
repoints its `menuToPush` at an id of your own.

**Patch 2** clones `Manager.menu.uiOptionsMenuPrefab` under
`Manager.camera.uiCamera`, clears its `Options/Scroll` children and its
`menuOptions` list, and gives it a title. `MenuManager.Init` itself does
`optionsMenu = InstantiateMenu<RadicalMenu>(optionsMenuPrefab)`;
`optionsMenuPrefab` is a public `GameObject` field and `optionsMenu` a public
property with a private setter.

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
(HealthBars) and `29314` are known to be taken.

**Trap: patch the prefab, not the live menu.** Adding your row to the already
instantiated `Manager.menu.optionsMenu` in a postfix is too late —
`RadicalMenu.Awake` has run, your row is not in `menuOptions`, and it renders as
a visible but unselectable entry. Inject into the *prefab* from the `Init`
prefix instead.

### Traps when cloning menu objects

**`Object.Instantiate(gameObject, parent)` throws.** The two-argument overload
activates the clone mid-clone inside `Internal_CloneSingleWithParent`, so
`OnEnable` and `PugTextEffectMenuOption.ResetEffect` fire before the row's
`PugText` component has been cloned — a `NullReferenceException`, and your entry
silently never appears. Clone **parentless** and reparent afterwards:

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

**The prefab's filename drives the root GameObject's name.** Unity's
`PrefabImporter` syncs the root `m_Name` to the file name on import, so editing
`m_Name` in the YAML is reverted at build time. Rename the *file* (and its
`.meta`, which preserves the GUID). This matters because a prefab named
identically to a vanilla one produces two indistinguishable `Foo(Clone)` objects
under `uiCamera`.

**Auto-layout exists — use it.** `LinearLayoutUIComponent` is CK's vertical
stacker: `RenderUIComponent(true)` plus `GetUIComponentRenderHeight()` replaces
hand-rolled box positioning. A scrollable own menu is
`: RadicalMenu, IScrollable` with a `UIScrollWindow` alongside.

### Localising menu strings

Menu labels come from `TextDataBlock` assets, one per language, and `PugText`
resolves terms out of them. In code the lookup is:

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
sub-header: `AddNewCategory_Internal` sets
`_showActionCategoryName = (categoryName != "Mods")`, on the reasoning that the
Controls tab is already called "Mods" and a redundant sub-header would be noise.
The consequence for you is a loose row at the top of the tab with no mod name
and no description. Any named category other than `"Mods"` gets the header.
CoreLib migrates an already-persisted action into the new category on load via
`ChangeActionCategory`, so switching later is safe.

Actions created this way get an id `>= 1000` and live in a mod-owned `player`
category. Poll them by name:

```csharp
ReInput.players.GetPlayer(0).GetButtonDown("MyMod-ToggleThing");
```

`AddControllerBind` and `AddMouseBind` with the **same name** extend that one
action onto other devices.

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

`AddKeyboardBind` always calls
`keyboardMap.AddNewActionElementMap(..., keyCode: defaultKeyCode)`; there is no
branch that skips it for `KeyboardKeyCode.None`. So a bind you registered as
"unbound" still owns an `ActionElementMap`, and CK renders that map's
`elementIdentifierName` — the string `"None"`. A genuinely unbound CK action has
**no map at all**, and `ControlMappingMenu`'s setup loop simply renders nothing
for it.

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
2. A `ControlMapping_CategoryLayoutData` entry is appended to CoreLib's shared
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

For a custom prompt — "[Y] Toggle view" and the like — **roll your own hint
object**: a `PugText` plus a sprite, parented under your own menu, toggled with
`SetActive` from `OnSelectedOptionChanged`. Do not hijack the closed enum;
mutating the shared singleton means fighting a per-frame diff, and it breaks the
moment vanilla wants the slot back.

## Which input actions you can use inside a menu

**`MenuSecondaryActivate` is Rewired action id `221`**, in category `"Menu"`. It
is defined in `PugMod.SDK.Runtime` (so it is reachable through `RewiredConsts`),
bound by default to a controller face button, and — usefully — **free inside a
normal settings menu**, because CK only polls it in the mod.io browser. Poll it
with:

```csharp
Manager.input.GetButtonDown(221);
```

**Controller only.** Action 221 has no keyboard default, and you cannot give it
one through the Controls screen: its category `"Menu"` is tagged `_tag: system`
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
past the window edge until you add a `SpriteMask` yourself.

**Trap: `UIScrollWindow.scrollable` is the public serialized field.** Do not
confuse it with the private `_scrollable`. `UIScrollWindow.Awake()` reads
`scrollable` directly and, if it is null, sets `base.enabled = false`
permanently — the window is dead for the rest of its life, with no error beyond
a warning. Wire your `IScrollable` implementor into that slot in the Editor, or
in the prefab YAML as `scrollable: {fileID: <your MonoBehaviour id>}`. Setting
the private field later via reflection does not help; `Awake` has already
disabled the component.

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

`ScrollBar.Update()` does the rest itself: shows `root` while
`ScrollHeight > 0`, converts a drag to `scrollWindow.SetScrollValue`, and sizes
the handle to `max(VisibleRatio * background.size.y, MIN_HANDLE_SIZE)` with
`MIN_HANDLE_SIZE = 0.625`. **`UIScrollWindow.scrollBar` must point back at the
component** or the whole thing is a no-op; `autoHideScrollbar` hides it at
`VisibleRatio >= 1`. The optional arrow slots (`arrowUp`, `arrowUpInactive`,
`arrowDown`, `arrowDownInactive`) may stay at `fileID: 0`. Mouse-wheel scrolling
works without any scrollbar at all — the bar is purely the visible affordance.

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
space, pivot-corrected.** CK's canonical `UIComponentMonoBehaviour.ScrollIntoView`
computes `transform.position.y - scrollingContent.position.y` — a world delta,
valid because UI scale is 1 — and then, if
`GetUIComponentPivotPosition() == PivotPosition.TopLeft`, subtracts `height / 2`
to arrive at the **centre**. `PivotPosition { TopLeft, MiddleLeft }` is nested in
`UIComponentMonoBehaviour`, and `WrapperUIComponent.pivot` is the authority on
which one a given row uses (list rows tend to be `TopLeft`, ordinary rows
`MiddleLeft`).

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

**Red herring: `IScrollable.IsTopElementSelected` / `IsBottomElementSelected` /
`UpdateContainingElements` have nothing to do with selection-follow.** They are
used only in `UpdateScroll`'s controller analog-stick free-scroll path, guarded
by `flag = !SystemPrefersKeyboardAndMouse()`. CK's own `ControlMapper` leaves
`UpdateContainingElements` empty. Stubbing all three is fine.

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
| Navigation skips the row | `RadicalMenu.SelectNextIndex` / `SelectPrevIndex` walk on while `!IsSelectionEnabled()` (= `!ShouldBeGrayedOut()`) |
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

### Three traps

**`visualOnly` splits optics from control.**
`IsSelectionEnabled(visualOnly: true)` answers "which colour?";
`IsSelectionEnabled()` answers "may navigation land here?". Vanilla's popup
buttons exploit the gap deliberately — input-dead during the anti-misclick
timer, visually normal.

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
