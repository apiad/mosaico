"""Smoke test: mosaico module imports and registers commands."""
import subprocess
import sys


def test_mosaico_commands_registered():
    result = subprocess.run(
        [sys.executable, "-m", "mosaico.cli", "--help"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "gen" in result.stdout
    assert "render" in result.stdout


def test_mosaico_app_exposes_gen_and_render():
    from mosaico import app
    assert "gen" in app._commands
    assert "render" in app._commands
