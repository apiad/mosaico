"""mosaico render — project YAML -> topo-sorted, cached batch render.

Reads a project YAML, builds the dep graph, topologically sorts, renders
only what's missing or stale (content-addressed cache), writes outputs in
place. Idempotent. Re-runnable indefinitely.

Every error tells the agent how to inspect: --dry-run, --tour, etc.

Discoverability:
    mosaico render --tour
    mosaico render <project.yml>            # plan-only
    mosaico render <project.yml> --save     # actually render
    mosaico render <project.yml> --dry-run  # explicit plan
    mosaico render <project.yml> --only id1,id2 --save
    mosaico render <project.yml> --force all --save
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated

import microcli as m

from . import app

from .gen import run_gen
from .schema import (
    Artifact,
    Project,
    SchemaError,
    expand_templates,
    parse_project,
    topo_sort,
)
from .state import compute_input_hash, file_sha256, load_state, save_state


@dataclass
class RenderSummary:
    rendered: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    planned: list[str] = field(default_factory=list)
    anchored: list[str] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)


def _resolve_prompt(artifact: Artifact, project: Project) -> str:
    """Expand templates and prepend the explicit Image-N declaration block.

    The block uses the convention the multimodal image-gen models
    (Nano Banana / Gemini Image and similar) actually associate with the
    attached image_url payloads: ``Image 1: ...`` / ``Image 2: ...`` declared
    BEFORE the body. Append-style ``Reference N: ...`` after the body
    consistently produces lower fidelity to the references — the model
    treats the refs as decoration. Prepend with explicit per-image instructions
    locks character/style consistency to the attached images.
    """
    body = expand_templates(artifact.prompt_template, project.templates)
    if not artifact.refs:
        return body

    header = (
        f"Use the following {len(artifact.refs)} attached image(s) as visual "
        f"references. For each one, follow the per-image instruction below "
        f"EXACTLY — preserve faces, bodies, palette, medium, wardrobe and "
        f"composition cues from the referenced images. Do NOT invent "
        f"different characters or styles than what the references show."
    )
    ref_lines = []
    for i, r in enumerate(artifact.refs, 1):
        label = r.artifact if r.artifact else r.path
        hint = r.hint or "use as visual anchor"
        ref_lines.append(f"Image {i} ({label}): {hint}")
    return header + "\n\n" + "\n".join(ref_lines) + "\n\n---\n\n" + body


def _ref_hashes(
    artifact: Artifact,
    project: Project,
    state: dict,
) -> list[dict]:
    """Build the `ref_hashes` list for this artifact's input hash."""
    out: list[dict] = []
    for r in artifact.refs:
        if r.artifact is not None:
            stored = state["artifacts"].get(r.artifact, {})
            out.append({
                "kind": "artifact",
                "artifact": r.artifact,
                "hint": r.hint,
                "out_hash": stored.get("output_hash", ""),
            })
        else:
            ext_path = (project.yaml_path.parent / r.path).resolve()
            if not ext_path.exists():
                m.fail(
                    f"artifact `{artifact.id}` references external path "
                    f"`{r.path}` (resolved to {ext_path}) which does not "
                    f"exist. Fix the path or remove the ref. "
                    f"Run `mosaico render --tour` for the format."
                )
            out.append({
                "kind": "path",
                "path": str(r.path),
                "hint": r.hint,
                "file_hash": file_sha256(ext_path),
            })
    return out


def _input_hash_for(
    artifact: Artifact, project: Project, state: dict
) -> tuple[str, dict]:
    inputs = {
        "resolved_prompt": _resolve_prompt(artifact, project),
        "model": artifact.resolved_model,
        "seed": artifact.resolved_seed,
        "aspect": artifact.resolved_aspect,
        "grid": list(artifact.grid) if artifact.grid else None,
        "cells_spec": artifact.cells,
        "ref_hashes": _ref_hashes(artifact, project, state),
    }
    return compute_input_hash(inputs), inputs


def _restrict_to_only(
    ordered: list[Artifact], only: list[str], by_id: dict[str, Artifact]
) -> list[Artifact]:
    """Restrict to `only` plus all transitive deps. Preserves topo order."""
    unknown = [oid for oid in only if oid not in by_id]
    if unknown:
        m.fail(
            f"--only references unknown artifact(s): {', '.join(unknown)}. "
            f"Known ids: {', '.join(sorted(by_id))}. "
            f"Run `mosaico render <project> --dry-run` to see all."
        )
    needed: set[str] = set()
    def add_with_deps(aid: str):
        if aid in needed:
            return
        needed.add(aid)
        for r in by_id[aid].refs:
            if r.artifact:
                add_with_deps(r.artifact)
    for oid in only:
        add_with_deps(oid)
    return [a for a in ordered if a.id in needed]


def _collect_ref_paths(
    artifact: Artifact, project: Project, state: dict
) -> list[Path]:
    """Resolve `refs[]` to actual file paths usable by run_gen."""
    paths: list[Path] = []
    for r in artifact.refs:
        if r.artifact:
            stored = state["artifacts"].get(r.artifact, {})
            out_rel = stored.get("out")
            if not out_rel:
                m.fail(
                    f"artifact `{artifact.id}` requires upstream `{r.artifact}` "
                    f"but it has no recorded output. Render order broken? "
                    f"Run with --dry-run to inspect."
                )
            paths.append(project.yaml_path.parent / out_rel)
        else:
            paths.append((project.yaml_path.parent / r.path).resolve())
    return paths


def _collect_cells_state(written: Path, has_grid: bool) -> dict[str, str]:
    """Hash all per-cell files under <written.stem>/cells/. Empty if no grid."""
    cells_state: dict[str, str] = {}
    if not has_grid:
        return cells_state
    cells_dir = written.parent / written.stem / "cells"
    for cp in sorted(cells_dir.glob("*.jpg")):
        cells_state[cp.stem] = file_sha256(cp)
    return cells_state


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def _out_rel(written: Path, project: Project) -> str:
    try:
        return str(written.relative_to(project.yaml_path.parent))
    except ValueError:
        return str(written)


def run_render(
    project_path: Path | str,
    only: list[str] | None,
    force: list[str] | None,
    dry_run: bool,
    bootstrap: bool = False,
) -> RenderSummary:
    """Render or bootstrap a project.

    Two modes:

    - **render** (default, `bootstrap=False`): standard topo-sorted render
      with content-addressed cache. Skips artifacts whose `input_hash`
      matches state. With `dry_run=True`, plans without calling the API.
    - **bootstrap** (`bootstrap=True`): anchor existing on-disk outputs to
      the current manifest's hashes. For each artifact whose `out:` exists,
      compute the manifest's `input_hash` and the file's `output_hash` and
      write that entry to state — *no API calls*. Pendings (artifacts whose
      `out:` is missing) are reported in `summary.pending` but not rendered.
      Use this to migrate an existing image set under mosaico's cache, or to
      re-anchor after a prompt refactor that doesn't intend to re-render.
      With `dry_run=True`, the anchor pass runs in memory and state is not
      written.

    `bootstrap=True` is incompatible with `force` (bootstrap anchors;
    force re-renders — use them in separate calls).
    """
    project_path = Path(project_path)
    try:
        project = parse_project(project_path)
        ordered = topo_sort(project)
    except SchemaError as e:
        m.fail(str(e))

    by_id = {a.id: a for a in project.artifacts}
    if only:
        ordered = _restrict_to_only(ordered, only, by_id)

    state = load_state(project.state_path)

    if bootstrap and force:
        m.fail(
            "--bootstrap is incompatible with --force: bootstrap anchors "
            "existing files to the current manifest, force discards state to "
            "re-render. Run them separately if you need both. "
            "Run `mosaico render --tour` for the format."
        )

    if force:
        if "all" in force:
            state = {"artifacts": {}}
        else:
            unknown = [f for f in force if f not in by_id]
            if unknown:
                m.fail(
                    f"--force references unknown artifact(s): "
                    f"{', '.join(unknown)}. Use `all` to wipe state. "
                    f"Run `mosaico render <project> --dry-run` "
                    f"to inspect."
                )
            for fid in force:
                state["artifacts"].pop(fid, None)

    summary = RenderSummary()

    if bootstrap:
        for artifact in ordered:
            try:
                ihash, _ = _input_hash_for(artifact, project, state)
            except SchemaError as e:
                m.fail(str(e))

            out_abs = project.out_root / artifact.out
            if not out_abs.exists():
                summary.pending.append(artifact.id)
                continue

            output_hash = file_sha256(out_abs)
            existing = state["artifacts"].get(artifact.id, {})
            preserve = (
                existing.get("output_hash") == output_hash
                and existing.get("rendered_at")
            )
            state["artifacts"][artifact.id] = {
                "input_hash": ihash,
                "output_hash": output_hash,
                "model": artifact.resolved_model,
                "seed": artifact.resolved_seed,
                "rendered_at": preserve or _now_iso(),
                "out": _out_rel(out_abs, project),
                "cells": _collect_cells_state(out_abs, artifact.grid is not None),
            }
            summary.anchored.append(artifact.id)

        if not dry_run:
            save_state(project.state_path, state)

        return summary

    for artifact in ordered:
        try:
            ihash, inputs = _input_hash_for(artifact, project, state)
        except SchemaError as e:
            m.fail(str(e))

        stored = state["artifacts"].get(artifact.id, {})
        if stored.get("input_hash") == ihash:
            summary.skipped.append(artifact.id)
            summary.planned.append(artifact.id)
            continue

        summary.planned.append(artifact.id)
        if dry_run:
            continue

        out_abs = project.out_root / artifact.out
        m.info(f"render {artifact.id} -> {out_abs}")
        written = run_gen(
            prompt=inputs["resolved_prompt"],
            out=out_abs,
            refs=_collect_ref_paths(artifact, project, state),
            grid=artifact.grid,
            cell_names=None,
            model=artifact.resolved_model,
            seed=artifact.resolved_seed,
            aspect=artifact.resolved_aspect,
        )

        state["artifacts"][artifact.id] = {
            "input_hash": ihash,
            "output_hash": file_sha256(written),
            "model": artifact.resolved_model,
            "seed": artifact.resolved_seed,
            "rendered_at": _now_iso(),
            "out": _out_rel(written, project),
            "cells": _collect_cells_state(written, artifact.grid is not None),
        }
        summary.rendered.append(artifact.id)

    if not dry_run:
        save_state(project.state_path, state)

    return summary


def _print_summary(summary: RenderSummary, planned_label: bool) -> None:
    if planned_label:
        for aid in summary.planned:
            tag = "RENDER" if aid not in summary.skipped else "skip  "
            print(f"  [{tag}] {aid}")
    else:
        for aid in summary.rendered:
            print(f"  [render] {aid}")
        for aid in summary.skipped:
            print(f"  [skip  ] {aid}")


def _print_bootstrap_summary(summary: RenderSummary) -> None:
    for aid in summary.anchored:
        print(f"  [anchor]  {aid}")
    for aid in summary.pending:
        print(f"  [pending] {aid} — out missing on disk")


@app.command
def render(
    project: Annotated[str, "Path to the project YAML"],
    only: Annotated[str, "Render only these artifact ids (comma-separated)"] = "",
    force: Annotated[str, "Ignore cache for these ids; or `all` to wipe"] = "",
    dry_run: Annotated[bool, "Print plan, render nothing"] = False,
    save: Annotated[bool, "Required to actually render (microcli two-phase)"] = False,
    bootstrap: Annotated[
        bool,
        "Anchor existing on-disk outputs to current manifest hashes (no API)",
    ] = False,
):
    """Render a visual project from a YAML manifest.

    Topologically sorts the artifact graph, renders only what's missing or
    stale (content-addressed cache), writes outputs in place. Idempotent.

    Without --save (and without --dry-run): prints what would render but
    doesn't call the API. Equivalent to --dry-run for safety.

    With --bootstrap: anchors existing on-disk outputs to the current
    manifest's hashes — no API calls. Use to migrate an existing image set
    under mosaico's cache or to re-anchor after a prompt refactor that
    shouldn't trigger re-render. With --bootstrap --save: anchor first,
    then render any pending (missing-on-disk) artifacts.

    Examples:
      mosaico render project.yml --dry-run
      mosaico render project.yml --save
      mosaico render project.yml --only chapter-01-cover --save
      mosaico render project.yml --force all --save
      mosaico render project.yml --bootstrap          # anchor existing files
      mosaico render project.yml --bootstrap --dry-run  # preview anchor pass
      mosaico render project.yml --bootstrap --save   # anchor + render new
    """
    only_list = [s.strip() for s in only.split(",") if s.strip()] or None
    force_list = [s.strip() for s in force.split(",") if s.strip()] or None

    if bootstrap and force_list:
        m.fail(
            "--bootstrap is incompatible with --force. Bootstrap anchors "
            "existing files; force discards state to re-render. Run them "
            "separately."
        )

    if bootstrap:
        summary = run_render(
            project, only_list, None, dry_run=dry_run, bootstrap=True
        )
        _print_bootstrap_summary(summary)
        if dry_run:
            m.info(
                f"bootstrap (dry-run): would anchor {len(summary.anchored)}, "
                f"leave {len(summary.pending)} pending"
            )
        else:
            m.ok(
                f"bootstrap: {len(summary.anchored)} anchored, "
                f"{len(summary.pending)} pending"
            )
        if not save:
            return
        if not summary.pending:
            m.info("nothing pending; --save has nothing to render after bootstrap.")
            return
        m.info(
            f"--save: rendering {len(summary.pending)} pending artifact(s)…"
        )

    if not save and not dry_run and not bootstrap:
        m.info("Default mode is plan-only (no API calls). Showing plan…")
        summary = run_render(project, only_list, force_list, dry_run=True)
        _print_summary(summary, planned_label=True)
        m.info("Rerun with --save to actually render.")
        return

    summary = run_render(project, only_list, force_list, dry_run=dry_run)
    _print_summary(summary, planned_label=dry_run)
    if not dry_run:
        m.ok(f"render complete: {len(summary.rendered)} new, "
             f"{len(summary.skipped)} cached")
