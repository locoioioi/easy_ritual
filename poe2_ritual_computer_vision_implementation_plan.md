# Implementation Plan: PoE 2 Ritual Computer Vision Helper

## 1. Objective

Build a Python application that analyzes a Path of Exile 2 Ritual reward table using computer vision, identifies items from their visual assets, estimates their value, decides which items should be selected, generates a JSON execution plan, and optionally executes the planned clicks.

The application must support both offline testing with saved screenshots and live operation against the game window.

The user interaction must follow this hotkey model:

- `F2`: enable or disable the helper.
- `T`: analyze the current Ritual table and generate or execute a selection plan.
- `R`: reroll, open the Defer view, analyze the refreshed table, execute the plan, and confirm.
- `F12`: stop the application.

---

## 2. Core Architecture

The application must be split into independent components:

```text
Hotkey Controller
    ↓
Capture Processor
    ↓
Computer Vision Analyzer
    ↓
ritual_plan.json
    ↓
Execution Processor
    ↓
execution_result.json
```

### 2.1 Hotkey Controller

Responsibilities:

- Register and handle `F2`, `R`, `T`, and `F12`.
- Maintain enabled and busy state.
- Prevent overlapping workflows.
- Coordinate capture, analysis, plan generation, and execution.
- Switch between test and live modes.
- Ensure errors do not terminate the application unexpectedly.

### 2.2 Capture Processor

Responsibilities:

- Capture the active game client in live mode.
- Load a saved screenshot in test mode.
- Return a normalized captured-frame object.
- Record image dimensions and source metadata.
- Save screenshots used for analysis.

### 2.3 Computer Vision Analyzer

Responsibilities:

- Locate or crop the Ritual board.
- Detect occupied item regions.
- Group multi-cell items.
- Extract clean item icon crops.
- Match icons against an indexed PoE asset database.
- Resolve item metadata.
- Retrieve cached or remote price estimates.
- Apply the selection policy.
- Generate `ritual_plan.json`.

The analyzer must not move the mouse or click anything.

### 2.4 Execution Processor

Responsibilities:

- Read and validate `ritual_plan.json`.
- Convert percentage coordinates into current client pixels.
- Support dry-run, recording, rendering, and live execution.
- Execute click actions with configurable delays.
- Stop safely if the target window loses focus.
- Generate `execution_result.json`.

The executor must not perform image recognition, pricing, or item selection logic.

---

## 3. Required Operating Modes

### 3.1 Test Mode

Test mode must work without the game being open.

Inputs:

- Saved Ritual screenshot.
- Local icon database.
- Static or cached price data.
- Recording or rendering backend.

Behavior:

- Load fixture screenshot.
- Analyze the board.
- Generate `ritual_plan.json`.
- Record planned clicks.
- Produce a preview image showing detected items and click positions.
- Never move the real mouse.

### 3.2 Live Mode

Inputs:

- Active PoE 2 client window.
- Live screenshot capture.
- Live mouse backend.

Behavior:

- Capture only the game client area.
- Validate that the correct window is active.
- Analyze the current board.
- Generate a plan.
- Execute only validated actions.
- Stop if focus is lost or safety limits are exceeded.

Live execution must be disabled by default and enabled explicitly through configuration.

---

## 4. Hotkey Workflows

### 4.1 F2 — Toggle Helper

When disabled:

- `R` and `T` must do nothing.
- No capture or mouse action must occur.

When enabled:

- Store the current target window.
- Allow `R` and `T`.
- Show or log enabled status.

When disabled again:

- Reject new workflows.
- Clear transient busy state.
- Do not terminate the application.

### 4.2 T — Analyze Current Ritual Table

Workflow:

```text
Validate enabled state
→ Validate not busy
→ Capture current screen or load fixture
→ Analyze Ritual table
→ Generate ritual_plan.json
→ Validate generated plan
→ Execute using selected backend
→ Generate execution_result.json
→ Save debug artifacts
```

In test mode:

```text
Fixture screenshot
→ Analyzer
→ JSON plan
→ Rendered preview or recorded clicks
```

In live mode:

```text
Game capture
→ Analyzer
→ JSON plan
→ Controlled mouse execution
```

### 4.3 R — Reroll and Process

Workflow:

```text
Validate enabled state
→ Validate not busy
→ Click Reroll
→ Wait for UI update
→ Click Defer
→ Wait for UI update
→ Capture refreshed Ritual table
→ Analyze table
→ Generate ritual_plan.json
→ Execute selected item actions
→ Click Confirm Defer
→ Generate execution_result.json
```

Known percentage coordinates:

```text
Reroll:
x = 0.1969
y = 0.2009

Defer:
x = 0.4479
y = 0.2019

Confirm Defer:
x = 0.3276
y = 0.8231
```

All delays must be configurable.

---

## 5. Project Structure

```text
poe2-ritual-helper/
├── pyproject.toml
├── README.md
│
├── config/
│   ├── application.json
│   ├── vision.json
│   └── selection-policy.json
│
├── src/
│   └── ritual_helper/
│       ├── main.py
│       │
│       ├── controller/
│       │   ├── application_controller.py
│       │   ├── hotkey_controller.py
│       │   └── application_state.py
│       │
│       ├── capture/
│       │   ├── capture_source.py
│       │   ├── fixture_capture.py
│       │   └── window_capture.py
│       │
│       ├── analyzer/
│       │   ├── ritual_analyzer.py
│       │   ├── board_extractor.py
│       │   ├── grid_analyzer.py
│       │   ├── item_region_detector.py
│       │   ├── multi_cell_grouper.py
│       │   ├── icon_extractor.py
│       │   ├── icon_normalizer.py
│       │   ├── icon_matcher.py
│       │   ├── metadata_resolver.py
│       │   ├── price_service.py
│       │   ├── selection_policy.py
│       │   └── plan_builder.py
│       │
│       ├── executor/
│       │   ├── ritual_executor.py
│       │   ├── click_backend.py
│       │   ├── recording_backend.py
│       │   ├── render_backend.py
│       │   └── live_mouse_backend.py
│       │
│       ├── models/
│       │   ├── captured_frame.py
│       │   ├── ratio_geometry.py
│       │   ├── detected_item.py
│       │   ├── identification_result.py
│       │   ├── price_estimate.py
│       │   ├── selection_decision.py
│       │   ├── ritual_plan.py
│       │   └── execution_result.py
│       │
│       └── shared/
│           ├── configuration.py
│           ├── logging.py
│           └── validation.py
│
├── tools/
│   ├── asset-extractor/
│   ├── convert-assets.py
│   └── build-icon-index.py
│
├── data/
│   ├── raw-icons/
│   ├── normalized-icons/
│   ├── item-database.sqlite
│   ├── icon-index.npz
│   └── prices.sqlite
│
├── fixtures/
│   ├── screenshots/
│   ├── expected-plans/
│   ├── expected-regions/
│   └── price-data/
│
├── output/
│   ├── screenshots/
│   ├── plans/
│   ├── execution-results/
│   └── debug/
│
└── tests/
    ├── controller/
    ├── capture/
    ├── analyzer/
    ├── executor/
    └── integration/
```

---

## 6. JSON Plan Contract

The analyzer and executor must communicate only through a validated JSON plan.

Example:

```json
{
  "schema_version": "1.0",
  "plan_id": "ritual-20260801-001",
  "created_at": "2026-08-01T18:00:00+07:00",
  "source": {
    "image_path": "output/screenshots/current-ritual.png",
    "client_width": 1920,
    "client_height": 1080,
    "mode": "test"
  },
  "board": {
    "left": 0.1604,
    "top": 0.2444,
    "right": 0.4880,
    "bottom": 0.7343
  },
  "items": [
    {
      "item_id": "item-001",
      "region": {
        "left": 0.1700,
        "top": 0.2600,
        "right": 0.1980,
        "bottom": 0.3100
      },
      "click_point": {
        "x": 0.1840,
        "y": 0.2850
      },
      "identification": {
        "internal_item_id": "Metadata/Items/Currency/Example",
        "display_name": "Example Orb",
        "category": "currency",
        "status": "matched",
        "score": 0.94,
        "confidence_gap": 0.08
      },
      "estimated_price": {
        "amount": 14.5,
        "currency": "exalted",
        "confidence": 0.90
      },
      "decision": "select",
      "decision_reason": "Estimated value exceeds threshold"
    }
  ],
  "actions": [
    {
      "action_id": "action-001",
      "type": "click",
      "target": "item-001",
      "position": {
        "x": 0.1840,
        "y": 0.2850
      },
      "delay_after_ms": 400
    }
  ],
  "summary": {
    "items_detected": 8,
    "items_identified": 6,
    "items_selected": 2,
    "items_for_review": 1
  }
}
```

Use Pydantic models for validation.

Validation requirements:

- All ratios must be between `0.0` and `1.0`.
- Rectangles must have valid dimensions.
- Click actions must contain a position.
- Delays must be non-negative.
- Schema version must be supported.
- Every action target must reference an existing item or supported UI control.

---

## 7. Computer Vision Pipeline

### 7.1 Board Extraction

Use the known Ritual board rectangle initially:

```text
left   = 0.1604
top    = 0.2444
right  = 0.4880
bottom = 0.7343
```

Convert percentage coordinates to pixels based on the captured client size.

Do not implement automatic board detection in the first version.

Save the cropped board as a debug image.

### 7.2 Grid Analysis

Use the known 10×10 grid geometry.

For each grid cell:

- Calculate brightness variance.
- Calculate edge density.
- Compare against an empty-cell reference.
- Estimate whether the cell is occupied.
- Store occupancy confidence.

Output an occupancy matrix.

Example:

```text
0 0 1 1 0 0
0 0 1 1 0 0
0 0 0 0 1 0
```

### 7.3 Multi-Cell Item Grouping

Items may occupy more than one grid cell.

Use connected-component grouping with four-directional adjacency.

Requirements:

- Adjacent occupied cells must be grouped into one item region.
- A multi-cell item must produce one item ID.
- A multi-cell item must produce one click point.
- Duplicate regions must not be generated.
- The click point should normally be the visual center of the grouped region.

### 7.4 Icon Extraction

For each detected item region:

- Crop the item region.
- Remove the Ritual border.
- Exclude the defer badge region.
- Exclude tribute cost or quantity text.
- Preserve only the item artwork.
- Save both raw and cleaned crops.

Required debug files:

```text
item-001-region.png
item-001-icon.png
```

Icon extraction quality must be verified before implementing matching.

### 7.5 Icon Normalization

Normalize screenshot icons and extracted game assets using the same process.

Suggested operations:

- Remove transparent or dark padding.
- Resize to a fixed canvas such as `64×64`.
- Preserve aspect ratio.
- Normalize brightness.
- Generate grayscale and edge-map variants.
- Calculate perceptual hash.

Store:

```text
RGB image
grayscale image
edge image
perceptual hash
```

### 7.6 Asset Database

Use VisualGGPK2 for manual discovery and inspection.

Use LibGGPK3 for the automated extraction pipeline.

The asset update process should:

```text
Detect game update
→ Extract relevant item icons and metadata
→ Convert textures to PNG
→ Normalize icons
→ Resolve internal item IDs and display names
→ Generate hashes and image features
→ Update local database
```

The runtime Python application must not depend directly on LibGGPK3.

The database must map:

```text
internal item ID
→ display name
→ category
→ icon asset path
→ normalized icon path
→ content hash
```

### 7.7 Icon Matching

Use a two-stage matching process.

#### Stage 1: Candidate Shortlisting

Calculate perceptual hash distance between the query icon and all indexed assets.

Return the nearest 20–50 candidates.

#### Stage 2: Detailed Comparison

Compare the query against shortlisted candidates using a weighted score.

Suggested inputs:

- OpenCV normalized correlation.
- Structural similarity.
- Edge similarity.

Example:

```text
final score =
45% correlation
+ 35% structural similarity
+ 20% edge similarity
```

Return:

- Best candidate.
- Best score.
- Second-best score.
- Confidence gap.
- Match status.

Suggested initial classification:

```text
Matched:
best score >= 0.90
and confidence gap >= 0.05

Review:
best score >= 0.78

Unknown:
otherwise
```

All thresholds must be configurable and calibrated using real screenshots.

---

## 8. Identification Limitations

Icon matching may confidently identify:

- Currency.
- Fragments.
- Deterministic consumables.
- Some maps.
- Visually unique items.

Icon matching may identify only the base type for:

- Rare weapons.
- Rare armour.
- Rare jewellery.
- Items whose value depends on modifiers.

The analyzer must represent this explicitly:

```json
{
  "identification_scope": "base_type_only",
  "requires_tooltip": true
}
```

The first version should not assign a full market price to rare equipment using icon recognition alone.

---

## 9. Pricing Layer

Define a `PriceProvider` interface.

Implement providers in this order:

1. Static fixture provider.
2. Local SQLite cache.
3. Optional remote provider.

Requirements:

- Pricing must be separate from image matching.
- Failed price lookups must not fail the complete analysis.
- Cache keys must include league and relevant item variant.
- Unknown prices must be represented explicitly.
- Test mode must not require network access.

---

## 10. Selection Policy

Store policy in configuration.

Example:

```json
{
  "minimum_value": 10.0,
  "price_currency": "exalted",
  "minimum_identification_confidence": 0.88,
  "select_unknown_items": false,
  "select_uncertain_items": false,
  "category_rules": {
    "currency": true,
    "fragment": true,
    "unique": true,
    "equipment": false
  }
}
```

Supported decisions:

- `select`
- `skip`
- `review`

Every decision must include a reason.

Example:

```text
select:
value exceeds threshold and identification is sufficiently confident

review:
potentially valuable but identification or pricing is uncertain

skip:
below threshold, unsupported, or unknown
```

---

## 11. Executor Backends

### 11.1 Recording Backend

Records intended clicks without executing them.

Output example:

```json
[
  {
    "type": "click",
    "x": 355,
    "y": 315
  }
]
```

### 11.2 Render Backend

Produces a preview image containing:

- Board boundary.
- Item rectangles.
- Identified item names.
- Confidence values.
- Selection status.
- Numbered click positions.

### 11.3 Live Mouse Backend

Performs actual clicks.

Requirements:

- Disabled by default.
- Target window must be active.
- Stop if focus is lost.
- Enforce maximum click count.
- Enforce workflow timeout.
- Respect configurable delay between clicks.
- Support emergency stop.

---

## 12. Required Debug Output

Every analyzer run must create a dedicated debug directory.

Example:

```text
output/debug/run-001/
├── captured-frame.png
├── board.png
├── cell-analysis.png
├── item-001-region.png
├── item-001-icon.png
├── item-001-candidates.json
├── selection-preview.png
├── ritual_plan.json
└── execution_result.json
```

This output is required for offline development and troubleshooting.

---

## 13. Implementation Phases

### Phase 1: Project Skeleton

Implement:

- Package structure.
- Configuration.
- Logging.
- CLI.
- Application state.
- Hotkeys.
- Clean shutdown.

Acceptance criteria:

- Application starts.
- `F2` toggles state.
- `F12` exits.
- `R` and `T` are ignored while disabled.
- No real mouse movement occurs.

### Phase 2: Plan Models and Validation

Implement:

- Ratio geometry models.
- Captured frame model.
- Detected item model.
- Identification result model.
- Price estimate model.
- Selection decision model.
- Ritual plan model.
- Execution result model.

Acceptance criteria:

- Valid plans serialize and deserialize.
- Invalid plans fail with readable errors.
- JSON output is deterministic.

### Phase 3: Executor and Offline Backends

Implement:

- Plan reader.
- Coordinate mapping.
- Recording backend.
- Render backend.
- Executor result generation.

Acceptance criteria:

- A handcrafted plan can be recorded.
- A handcrafted plan can be rendered onto a fixture image.
- No real mouse input occurs.

### Phase 4: Controller and Hotkeys

Implement:

- F2 workflow.
- T workflow.
- R workflow.
- Busy lock.
- Test/live mode switching.
- Error isolation.

Acceptance criteria:

- F2, R, T, and F12 work consistently.
- Overlapping workflows cannot occur.
- Test mode never moves the mouse.

### Phase 5: Capture Layer

Implement:

- Fixture capture.
- Live client capture.
- Captured frame metadata.
- Debug screenshot persistence.

Acceptance criteria:

- Fixture and live capture return the same data model.
- Client dimensions are recorded correctly.
- Invalid or unavailable windows fail safely.

### Phase 6: Stub Analyzer

Implement a hardcoded analyzer that returns two selected item positions.

Purpose:

- Validate complete application flow before computer vision.

Acceptance criteria:

```text
F2
→ T
→ fixture loaded
→ plan generated
→ preview rendered
→ execution recorded
```

### Phase 7: Board and Item Detection

Implement:

- Board crop.
- 10×10 grid generation.
- Occupancy detection.
- Multi-cell grouping.
- Click-point generation.

Acceptance criteria:

- One-cell items are detected.
- Multi-cell items are grouped.
- Items near board edges are detected.
- Repeated analysis produces stable results.

### Phase 8: Icon Extraction

Implement:

- Region crop.
- Border removal.
- Badge exclusion.
- Text exclusion.
- Normalized icon output.

Acceptance criteria:

- Debug crops contain item artwork with minimal UI contamination.
- One-cell and multi-cell items produce usable icon crops.

### Phase 9: Asset Index

Implement:

- Asset extraction workflow.
- PNG conversion.
- Metadata mapping.
- Normalization.
- Hash generation.
- Local database update.

Acceptance criteria:

- A known exported icon maps to its item metadata.
- The asset index can be rebuilt using one command.

### Phase 10: Icon Matching

Implement:

- pHash shortlisting.
- Detailed candidate scoring.
- Confidence calculation.
- Candidate debug output.

Acceptance criteria:

- Known currencies match correctly.
- Unknown items do not produce false high-confidence results.
- Top candidates are included in debug output.

### Phase 11: Pricing and Policy

Implement:

- Fixture price provider.
- Local price cache.
- Selection policy.
- Decision reasoning.

Acceptance criteria:

- Offline tests produce deterministic prices.
- Threshold changes require configuration only.
- Unknown or uncertain items are not automatically selected.

### Phase 12: Offline End-to-End Testing

Create fixtures for:

- Empty board.
- One item.
- Multiple items.
- Multi-cell item.
- High-value currency.
- Low-value currency.
- Similar icons.
- Unknown item.
- Items near board edges.
- Different client resolutions.

Acceptance criteria:

- `T` performs the complete workflow in test mode.
- JSON plan matches expected output.
- Preview image shows correct detections and actions.
- No real mouse input occurs.

### Phase 13: Live Capture

Implement live client capture only after offline tests pass.

Acceptance criteria:

- Current game client is captured correctly.
- Board crop matches fixture behavior.
- Capture failures are logged without terminating the application.

### Phase 14: Live Execution

Implement real mouse execution with safety checks.

Acceptance criteria:

- Live mode requires explicit enablement.
- Target window validation occurs before every action.
- Execution stops when focus is lost.
- Click and timeout limits are enforced.
- Every action is logged.

---

## 14. First Deliverable

The first deliverable must be a narrow offline vertical slice:

```text
Start application
→ F2 enables helper
→ T loads a saved Ritual screenshot
→ Stub analyzer produces a valid ritual_plan.json
→ Recording backend records clicks
→ Render backend creates a numbered preview image
→ F12 exits
```

Expected files:

```text
output/
├── plans/
│   └── ritual_plan.json
├── execution-results/
│   └── execution_result.json
└── debug/
    └── selection-preview.png
```

Do not implement price APIs or live mouse control in the first deliverable.

---

## 15. Definition of Done

The implementation is complete when:

- F2, R, T, and F12 behave consistently.
- Test mode works without the game running.
- The analyzer generates a validated JSON plan.
- The executor can record, render, or execute the same plan.
- Multi-cell items are treated as one item.
- Known item icons can be matched against the asset database.
- Pricing and selection logic are independently testable.
- Live mode is guarded by window, focus, timeout, and click-count checks.
- Every run produces sufficient debug artifacts for troubleshooting.
