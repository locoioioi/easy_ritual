wwwwwwwww# PoE 2 Ritual Helper

Offline-first scaffold for the Ritual helper described in
`poe2_ritual_computer_vision_implementation_plan.md`.

Current deliverable:

- `F2` toggles the helper.
- `T` runs the offline fixture flow.
- `R` runs the reroll/defer/analyze/click/confirm workflow.
- `Ctrl+C` price checks the copied tooltip and remembers the decision in memory
  for the current ritual.
- `F12` stops the app.
- Real mouse movement is opt-in through live mode and the `live_mouse` backend.

Run from a checkout without installing:

```powershell
$env:PYTHONPATH = "src"
python -m ritual_helper.main --once
```

Run interactive hotkeys:

```powershell
$env:PYTHONPATH = "src"
python -m ritual_helper.main
```

Run the desktop control panel:

```powershell
$env:PYTHONPATH = "src"
python -m ritual_helper.main --gui
```

The GUI is a small control panel for background gameplay mode. Use `Start` to
register hotkeys and enable the helper, `Stop` to unhook them, and `Save Config`
to edit runtime mode, price source, defer threshold, click coordinates, delays,
and vision thresholds.

The GUI tabs map to these files:

- Runtime, Coordinates: `config/application.json`
- Selection: `config/selection-policy.json`
- Vision: `config/vision.json`

Or install the package in editable mode:

```powershell
python -m pip install -e .[dev]
ritual-helper --once
ritual-helper-gui
```

If `fixtures/screenshots/ritual.png` does not exist, the fixture capture layer
creates a placeholder image so the full JSON and preview flow can still be
verified.

## Asset Extraction

The project includes a LibGGPK3-based extractor wrapper. It reads PoE 2
`Content.ggpk`, extracts likely item icons/metadata, and writes
`data/item-assets.json`.

Build/check the extractor:

```powershell
tools\dotnet\dotnet.exe build tools\RitualAssetExtractor\RitualAssetExtractor.csproj -c Release
```

List candidate paths first:

```powershell
tools\extract-poe2-assets.ps1 `
  -GgpkPath "C:\Path\To\Path of Exile 2\Content.ggpk" `
  -ListOnly `
  -Limit 200
```

Extract the candidate assets and write the manifest:

```powershell
tools\extract-poe2-assets.ps1 `
  -GgpkPath "C:\Path\To\Path of Exile 2\Content.ggpk" `
  -OodleDllPath "C:\Path\To\oo2core_9_win64.dll" `
  -Output data\extracted `
  -Manifest data\item-assets.json
```

LibGGPK3 needs the Oodle runtime DLL to decompress bundled GGPK data. If
`oo2core*.dll` is beside `Content.ggpk`, the extractor finds it automatically.
Otherwise pass `-OodleDllPath`.

Build the runtime icon catalog from directly readable PNG/JPG icons:

```powershell
.venv\Scripts\python.exe tools\build-asset-catalog.py `
  --manifest data\item-assets.json `
  --output data\item-icon-catalog.json
```

Files such as DDS/TGA are extracted and marked with `needs_conversion: true`.
They need a texture conversion step before they can enter the runtime icon
catalog.

## Tooltip Identification

For live item naming, the lighter path is to hover a detected item and press
`Ctrl+C`. PoE copies structured item text to the clipboard, and the app can
parse that into a name/category without scanning the GGPK. The controller then
uses the configured live price provider to decide whether the item should be
deferred.

Each copied tooltip is kept in an in-memory `checked_items` list with a
`shouldSelect` boolean. Re-copying the same tooltip reuses the cached decision
instead of price checking again. Pressing `R` to reroll clears the list because
price decisions are only valid for the current ritual screen.

Example:

```text
Item Class: Omen
Rarity: Currency
Omen of Sinistral Exaltation
--------
Stack Size: 1/10
```

The parser lives in `ritual_helper.analyzer.tooltip_parser`.

## Price Checking

Price checking is configured in two places.

`config/application.json` chooses the source and league:

```json
{
  "pricing": {
    "source": "poe2scout",
    "league": "Runes of Aldur",
    "timeout_seconds": 8.0
  }
}
```

Supported sources are:

- `poe2scout` - default, uses `https://api.poe2scout.com/poe2`
- `poe.ninja` - alternate source for the same tooltip flow
- `static` - disables live lookup and returns unknown prices

`config/selection-policy.json` controls the defer decision:

```json
{
  "minimum_defer_value": 10.0,
  "price_currency": "exalted"
}
```

`price_currency` supports only `chaos`, `exalted`, and `divine`. The selected
currency is used both for the API lookup and for comparing against
`minimum_defer_value`.

## Gameplay Mode

Real gameplay clicks are opt-in. To use the `R` flow in game, set
`config/application.json` to live mode and enable the live backend:

```json
{
  "mode": "live",
  "live_execution_enabled": true,
  "executor_backends": ["recording", "render", "live_mouse"]
}
```

With the helper enabled, `R` runs:

```text
reroll click -> wait -> defer click -> wait -> screenshot/analyze -> click selected cells -> confirm defer
```

The screenshot in that sequence is captured automatically from the active PoE 2
client after the reroll/defer clicks. The user does not provide a screenshot in
gameplay mode.

The configured `ui_controls` coordinates are ratios of the captured screen.
They are interpreted like the AutoHotkey script: mouse and image coordinates are
relative to the active window client area, not the full desktop.

In live mode, hotkey actions are ignored unless the active foreground window
matches the configured PoE 2 title/process filters in `target_window`. The live
mouse backend checks again before each click, so focus loss blocks the rest of
the sequence.

Current gameplay delays are:

```text
reroll -> defer: 350ms
after defer: 250ms
after each selected cell: 300ms
before confirm defer: 250ms
after confirm defer: 250ms
```

## Debug Output

Each run writes a numbered folder under `output/debug/run-*`. The main visual
artifact for cell decisions is:

```text
output/debug/run-*/cell-analysis.png
```

The run folder also includes `board.png`, `captured-frame.png`,
`item-groups.json`, `ritual_plan.json`, `execution_result.json`, and rendered
click previews. The older `foreground-mask.png` and `grouped-items.png` images
are no longer produced; cell analysis is the final visual decision view.
