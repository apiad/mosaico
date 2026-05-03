# Changelog

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
