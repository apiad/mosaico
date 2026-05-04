# mosaico

> Declarative image-project renderer.

`mosaico` reads a YAML manifest of image artifacts, builds the dependency
graph, topologically sorts it, and renders only what's missing or stale —
content-addressed caching, idempotent re-runs, two-phase plan/save flow.
Two commands:

- `mosaico gen "<prompt>"` — low-level: prompt → single image (with optional
  `--grid RxC` sheet + auto-cut).
- `mosaico render <project.yml>` — high-level: declarative project, full
  graph render with caching.

Both are designed to be agent-friendly: `--tour`, `--dry-run`, and
`mosaico` itself prints next-step instructions on every failure.

## Install

```bash
uv add mosaico
# or
pip install mosaico
```

## Quick start

```bash
export OPENROUTER_API_KEY=sk-...
mosaico gen "watercolor of a heron at dawn" --save --out heron.jpg
```

```yaml
# project.yml
version: 1
name: my-book
defaults:
  out_root: out
  state: state.json
artifacts:
  - id: cover
    prompt_template: "book cover, watercolor style, title '{{ templates.title }}'"
    out: cover.jpg
templates:
  title: "Érase una vez el Conocimiento"
```

```bash
mosaico render project.yml --save
```

## Migrating existing images under mosaico

If you already have generated images on disk and want to bring them under
mosaico's cache without re-rendering, use `--bootstrap`:

```bash
# Preview what would be anchored (dry-run, no state write)
mosaico render project.yml --bootstrap --dry-run

# Anchor existing files to the current manifest's hashes
mosaico render project.yml --bootstrap

# Anchor existing files, then render anything still missing on disk
mosaico render project.yml --bootstrap --save
```

For each artifact whose `out:` already exists, mosaico computes the
manifest's `input_hash` and the file's `output_hash` and writes that
entry to state — no API call. Pendings (artifacts whose `out:` is missing)
are reported but not rendered unless `--save` is also passed.

`--bootstrap` is also the right tool for **prompt refactors that shouldn't
trigger a re-render**: edit the manifest, run `--bootstrap`, and the new
`input_hash` is anchored to the existing output. A subsequent
`mosaico render --save` will see zero pending and call no API.

## Token discovery

`mosaico gen` reads its OpenRouter token from, in order:

1. `$OPENROUTER_API_KEY`
2. `$MOSAICO_TOKEN_FILE` (path to a file containing the key)
3. `$CLAUDE_TOOLKIT_WORKSPACE/.claude/openrouter.token` (set automatically
   when invoked under `claude-toolkit image …`)

## Mounting under another microcli app

`mosaico` exposes its `App` so a parent CLI can mount it:

```python
import microcli as m
from mosaico import app as mosaico_app

root = m.App(name="my-tool")
root.mount("image", mosaico_app)
root.main()
# my-tool image gen "<prompt>" --save
# my-tool image render project.yml --save
```

## License

MIT.
