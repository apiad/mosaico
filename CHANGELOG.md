# Changelog

## [0.4.1] - 2026-05-06

### Fixed

- **`render` now propagates `artifact.cells` to the cropper.** When a
  project-YAML artifact declared both `grid:` and `cells:` (mapping
  `slug -> {row, col}`), the `cells` dict was loaded from YAML but
  `render.py` called `run_gen(..., cell_names=None)`, so cropped cells
  were written with generic names (`cell-rR-cC.jpg`) instead of the
  declared slugs. Discovered while generating the cap. 5.1 glossary in
  the enciclopedia repo.

### Changed

- **`run_gen` signature: `cell_names: list[str] | None` -> `cells: dict[str, dict] | None`.**
  Single shape end-to-end: the artifact-level `cells:` dict (slug ->
  `{row, col, rowspan?, colspan?}`) is what the cropper accepts, and
  `run_gen` now passes it through unchanged. The flat-list ergonomic form
  is still exposed via the `--cell-names` CLI option on `mosaico gen`,
  but conversion + count validation now happen at the CLI layer (in
  `gen()`), not inside `run_gen`.

  Internal API change. External consumers calling `run_gen` directly with
  `cell_names=...` must rename to `cells=...` and convert flat lists to
  the dict shape themselves (or use the `gen` CLI which still handles
  `--cell-names` ergonomics).

- **Output convention reaffirmed.** Cells continue to land at
  `<sheet-stem>/cells/<slug>.jpg` (subdirectory under the sheet's stem),
  not flat alongside the sheet. This was already the established
  convention; documenting here to settle the question raised during the
  bug discovery.

## [0.4.0] - 2026-05-04

### Changed

- **Resolved-prompt format: `Image N (label): hint` declarations now PREPEND
  the body** with a directive header, instead of `Reference N: ...` appended
  after. The append-style block was producing low fidelity to the attached
  references — multimodal image-gen models (Nano Banana / Gemini Image)
  treated refs as decoration rather than character/style anchors. The new
  format mirrors the convention these models actually associate with the
  attached `image_url` payloads:

      Use the following N attached image(s) as visual references. For each
      one, follow the per-image instruction below EXACTLY — preserve faces,
      bodies, palette, medium, wardrobe and composition cues from the
      referenced images. Do NOT invent different characters or styles than
      what the references show.

      Image 1 (style-reference): style anchor — preserve medium and palette
      Image 2 (hermanas-sheet): canonical faces and bodies

      ---

      [body of prompt]

  This change invalidates the `input_hash` of every artifact that has refs.
  Run `mosaico render <project.yml> --bootstrap` after upgrading to re-anchor
  existing outputs to the new hashes (re-anchoring does not call the API).

## [0.3.0] - 2026-05-04

### Added

- `mosaico explain <project.yml>` — read-only inspection command that
  prints, for each artifact in topo order: status (ready / render / stale),
  output path, model/seed/aspect, refs with their upstream hashes, and the
  *fully resolved* prompt that would be sent to the API (templates expanded,
  ref-hint block appended). Use to validate the manifest before any render.
- `mosaico explain <project.yml> --only id1,id2` — restrict to specific
  artifacts (transitive deps included, same semantics as `render --only`).

### Use cases

- Confirm template expansion works as intended.
- Audit ref wiring before generating images.
- Inspect why an artifact is `[render]` vs `[ready]` (input_hash compared
  against state).

## [0.2.0] - 2026-05-04

### Added

- `mosaico render <project.yml> --bootstrap` — anchor existing on-disk
  outputs to the current manifest's hashes without calling the API. For
  each artifact whose `out:` exists, computes the manifest's `input_hash`
  and the file's `output_hash` and writes that entry to state. Pendings
  (artifacts whose `out:` is missing) are reported in the summary but not
  rendered. Use to migrate an existing image set under mosaico's cache, or
  to re-anchor after a prompt refactor that shouldn't trigger re-render.
- `--bootstrap --dry-run` previews the anchor pass without writing state.
- `--bootstrap --save` anchors existing files first, then renders any
  pending (missing-on-disk) artifacts in a single command.
- Idempotent: re-running `--bootstrap` preserves `rendered_at` when the
  output hasn't changed; updates only the `input_hash` if the manifest
  changed.
- `RenderSummary` extended with `anchored: list[str]` and
  `pending: list[str]` fields.

### Constraints

- `--bootstrap` is incompatible with `--force`. Run them as separate
  invocations if both behaviors are needed.

## [0.1.0] - 2026-05-03

### Initial release

Lifted from `claude-toolkit/src/claude_toolkit/tools/image/` into a
standalone repo, per design doc
`vault/Atlas/Architecture/2026-05-03-microcli-app-mosaico-mira-split-design.md`.

### Features
- `mosaico gen "<prompt>"` — single-image generation via OpenRouter, with
  optional `--grid RxC` sheet + auto-cut.
- `mosaico render <project.yml>` — declarative project rendering with
  content-addressed cache, topo-sorted graph, two-phase plan/save flow.
- Exposed as a microcli `App` for mounting under parent CLIs (e.g.
  `claude-toolkit image …`).
- Token discovery: `OPENROUTER_API_KEY` → `MOSAICO_TOKEN_FILE` →
  `$CLAUDE_TOOLKIT_WORKSPACE/.claude/openrouter.token`.

### Renamed commands

- `image-gen` → `gen` (now `mosaico gen`)
- `image-render` → `render` (now `mosaico render`)
