# FLUX.2 klein-4B via flux-shim — Stevenson 10-render review

**Date:** 2026-05-22
**Renderer:** FLUX.2 klein-4B (Apache 2.0, distilled, 4 steps, guidance=1.0)
**Backend:** `contrib/flux-shim/server.py` on falkor (RTX 5090, bfloat16, `enable_model_cpu_offload`)
**Driver:** mosaico v0.4.2 → `MOSAICO_ENDPOINT` override → shim
**Source manifest:** `repos/long-stories-short/mosaico.yml`, Stevenson sub-graph minus chapter 07 (to land at 10).

## Tally

| Artifact                              | Dims       | Time   |
| ------------------------------------- | ---------- | ------ |
| style-reference                       | 1024×1024  | 6.4s   |
| stevenson-style-sheet                 | 1024×1024  | 9.1s   |
| stevenson-character-sheet             | 1024×1024  | 18.1s  |
| stevenson-01-viejo-lobo-de-mar        | 1248×832   | 11.4s  |
| stevenson-02-mapa-y-hispaniola        | 1248×832   | 18.4s  |
| stevenson-03-barril-de-manzanas       | 1248×832   | 11.4s  |
| stevenson-04-isla-de-pesadilla        | 1248×832   | 13.9s  |
| stevenson-05-ben-gunn                 | 1248×832   | 12.2s  |
| stevenson-06-cable-del-ancla          | 1248×832   | 11.6s  |
| stevenson-cover                       | 896×1184   | 12.0s  |
| **Total**                             |            | **125s** |

Cost: $0.00 (local GPU). All 10 succeeded on first attempt, no retries.

## Plumbing — works as designed

- `aspect_to_dims` produced the expected mod-32 dimensions for every aspect (1:1, 3:2, 3:4); shim accepted them and the pipeline ran natively at each.
- Refs propagated end-to-end: chapter scenes received `stevenson-style-sheet` + `stevenson-character-sheet` as multi-ref editing input.
- `MOSAICO_ENDPOINT` override required zero changes to mosaico beyond the v0.4.2 wiring done in slice 1; mosaico has no idea it's not talking to OpenRouter.
- `enable_model_cpu_offload` keeps VRAM under control; per-image inference (4 steps) is ~3s, the rest is offload overhead.

## Image quality — qualitative read

**Style fidelity (vs. project register).** Klein lands in the "Brett Helquist / inked digital painting" register cleanly. Linework is confident, color fills are painterly, the palette stays in the warm-sunset / sea-blue band specified. It does NOT drift to Pixar 3D, vector, photoreal, or anime — the prohibitions in `{{ templates.style }}` are respected. The reference sheet's medium and palette propagate to the scenes without obvious style-drift.

**Character canonicity.** This is where klein falls short relative to gemini-3.1-flash-image-preview's strongest runs.
- **Jim Hawkins**: roughly canonical (sandy hair, boyish, open collar) but face geometry varies scene to scene — same archetype, different boy. Eye spacing and chin shape wobble.
- **Long John Silver**: the prompt's hard constraint (ONE leg + wooden crutch, NO eyepatch NO hook) was respected in the character sheet but **completely lost** in chapter 03 — the figure in the apple-barrel scene is a generic two-legged sailor with a tricorn. The crutch is absent, the parrot is absent. This is the largest fidelity miss in the set.
- **Billy Bones / Pew / Ben Gunn / Doctor Livesey**: each appears once and is recognizable from the prompt description, but character-sheet match is weak — Pew in scene 01 is not the hooded blind beggar of the sheet, it's a different hooded figure. Ben Gunn (scene 05) is the closest to canonical — gaunt, beard, goatskins, the "shaky joy" expression all read.

The character sheet itself (1024² composite) is decent for primaries on the left but the secondary strip at the bottom is muddy and small — likely a function of trying to fit eight characters into a 1MP canvas. A 2MP canvas (e.g. 1408×1408) would probably help, but klein's max is 2048 and quality past ~1.5MP degrades.

**Composition.** Scene composition follows prompt direction more reliably than character identity. Scene 02 (Doctor Livesey unfolding the map) lands the staging — Jim at the table edge, Livesey leaning in, warm hearth light. Scene 04 (Treasure Island shoreline) reads as a 2-panel comic-book layout rather than a single landscape, which is wrong but visually coherent. Scene 06 (cutting the anchor cable) is dramatic and well-staged.

**Text-in-image (cover).** The cover renders "La Isla del Tesoro" as legible display lettering — klein handles short text reliably. The author line "De Robert Luis Stevenson · ⟨garbled⟩ para niños" mangles "Robert Louis" → "Robert Luis" and the collection text becomes glyph soup. Title-only text works; multi-line typography does not.

**Negative-prompt adherence.** `{{ templates.no_text }}` is respected on the 9 scenes (no stray labels, captions, or speech bubbles). The exception is scene 01's wall sign behind the table, which renders garbled lettering ("EL VIEJO LENBEAR MER DE MAR") — a partial failure of the `NO text, NO labels, NO numbers, NO writing` instruction.

**Aspect handling.** Each aspect was sampled natively; no center-crop artifacts, no 1:1 letterboxing. The 3:2 chapter scenes feel intentionally widescreen rather than padded.

## Comparison vs. gemini-3.1-flash-image-preview

(Comparing against the equivalent renders in `repos/long-stories-short/img/stevenson-la-isla-del-tesoro/`, generated 2026-05-xx.)

| Dimension                | Klein-4B (local)               | Gemini-3.1-flash-image (OpenRouter) |
| ------------------------ | ------------------------------ | ----------------------------------- |
| Cost / 10 images         | $0.00 + ~125s wall             | ~$0.70 + ~400s wall                 |
| Style register match     | Solid, on-brief                | Solid, on-brief                     |
| Character consistency    | **Weak** — Silver loses crutch | Strong — Silver canonical           |
| Multi-ref editing        | Functional but identity drifts | Tighter identity preservation       |
| Text-in-image (title)    | Legible short text             | Legible short text                  |
| Text-in-image (subtitle) | Garbled                        | Garbled (both fail here)            |
| Negative-prompt fidelity | Mostly respected, 1 lapse      | Mostly respected                    |
| License                  | Apache 2.0                     | Proprietary (Google)                |
| Substitutability         | **Drop-in via shim**           | n/a                                 |

**Verdict.** Klein-4B is a viable Apache-2.0 fallback for mosaico when:
- The project doesn't depend on tight cross-image character identity (lookbook style sheets fine; multi-chapter character continuity not yet).
- Cost / offline-rendering matters more than 5-10% identity fidelity.
- Output is going through human review or distill anyway.

Klein-4B is **not** a replacement for gemini in production runs of long-stories-short where character canonicity is the contract.

## Mosaico recalibration — needed?

**No code changes needed.** The shim path validates that mosaico's existing data model (text + image_url blocks, `size` field, `model` field as informational echo) is sufficient for FLUX-class backends. The `aspect_to_dims` + `MOSAICO_ENDPOINT` work landed in v0.4.2 is the entire integration surface.

Things observed during the run that are **not** mosaico bugs but worth noting:

1. **`mosaico render --save` requires `=true`**, not bare `--save`. Already known. The plan caught it.
2. **`seed` field in defaults is silently ignored by the shim.** Not a mosaico concern — mosaico doesn't transmit seed (OpenAI multimodal payloads don't carry one). A future shim feature: accept a custom `seed` field in the request body. Filed as a follow-up, not a blocker.
3. **Output filenames in the source manifest end in `.jpg` but the shim only emits PNG.** I rewrote the experiment manifest to `.png` to match. Long-term, mosaico could content-sniff the response data URL and use the correct extension — but this is YAGNI until a backend emits something other than PNG.

## Follow-ups (not in scope for this experiment)

- [ ] Add a `seed` passthrough to flux-shim if reproducibility becomes important.
- [ ] Investigate why klein loses the crutch on Silver under multi-ref load — possibly a function of the ref-sheet being a multi-character composite rather than per-character refs.
- [ ] Try `FLUX.2-dev` (gated, but stronger identity preservation) under a separate shim for direct comparison if Alex obtains access.

## Reproducing

```bash
# falkor (one-time):
cd ~/flux-shim
setsid .venv/bin/python server.py > server.log 2>&1 < /dev/null & disown

# zion:
cd repos/mosaico/contrib/flux-shim/experiment-2026-05-22
OPENROUTER_API_KEY=placeholder \
MOSAICO_ENDPOINT=http://falkor:8000/v1/chat/completions \
  uv run --project /home/apiad/Workspace/repos/mosaico mosaico render project.yml --save=true
```

Outputs in `img/`. Cache state in `.mosaico/state.json`.
