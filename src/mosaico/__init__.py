"""mosaico — declarative image-project renderer.

Lifted from claude-toolkit/tools/image; see vault design doc
2026-05-03-microcli-app-mosaico-mira-split-design.md.

The `App` instance lives here (rather than in cli.py) so it survives the
`python -m mosaico.cli` re-import dance — when cli.py runs as `__main__`,
this module is imported first and `app` already has its commands.
"""
import microcli as m

app = m.App(
    name="mosaico",
    description="Declarative image-project renderer.",
    tour_source=__file__,
)

# Registration side effects: each module decorates its CLI entry with
# `@app.command` against the App instance defined above. Imported here so
# any `import mosaico` populates the registry exactly once.
from . import gen  # noqa: E402, F401
from . import render  # noqa: E402, F401
from . import explain  # noqa: E402, F401

__all__ = ["app"]
