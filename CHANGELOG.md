# Changelog

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
