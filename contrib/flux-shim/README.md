# flux-shim

OpenAI-compatible `POST /v1/chat/completions` server that routes calls to
`diffusers.Flux2KleinPipeline` on a local GPU. Built to be called from
`mosaico` with `MOSAICO_ENDPOINT` pointing at it.

## Install on a GPU host

```bash
cd /path/to/flux-shim
uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install -e ".[dev,gpu]" --extra-index-url https://download.pytorch.org/whl/cu129
```

## Run

```bash
# Defaults: host=100.64.0.4 (falkor's tailnet IP), port=8000
.venv/bin/python server.py
```

Override host/port:

```bash
FLUX_SHIM_HOST=0.0.0.0 FLUX_SHIM_PORT=9000 .venv/bin/python server.py
```

Skip cpu_offload (faster per-call, more VRAM held):

```bash
FLUX_SHIM_NO_OFFLOAD=1 .venv/bin/python server.py
```

## Smoke

With server running on `localhost:8000`:

```bash
./smoke.sh
```

Writes `smoke.png` (a single 1024x1024 PNG).

## From mosaico

```bash
export MOSAICO_ENDPOINT=http://falkor:8000/v1/chat/completions
export OPENROUTER_API_KEY=placeholder  # shim ignores auth; mosaico requires it set
mosaico gen "a heron at dawn" --save --out heron.png
```

## Tests

```bash
uv run pytest -v
```

Tests mock the pipeline; no GPU required.

## Spec

`vault/Atlas/Architecture/2026-05-22-flux-shim-for-mosaico-design.md`
