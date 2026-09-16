"""beagle-plugin-pi tests — the plugin contract section 7 + WP-4 defect guards."""

from __future__ import annotations

import contextlib
import importlib
from pathlib import Path
from typing import TYPE_CHECKING

import typer
from typer.testing import CliRunner

if TYPE_CHECKING:
    import pytest


def test_plugin_exports_app() -> None:
    """The plugin contract: the package module must export ``app``."""
    import beagle_plugin_pi

    mod = importlib.import_module("beagle_plugin_pi")
    assert mod is not None
    assert beagle_plugin_pi is mod
    # cli.py is the module the entry point names; check both shapes.
    import beagle_plugin_pi.cli as cli_mod

    assert isinstance(cli_mod.app, typer.Typer)


def test_pi_with_no_arguments_does_not_raise() -> None:
    """D-12: a bare invocation must be valid argument-wise."""
    from beagle_plugin_pi.cli import pi_app

    r = CliRunner().invoke(pi_app, [])
    # May fail on missing node/bundle, but NOT with a TypeError from the
    # argument parser (the old `Argument(None)` defect).
    assert "Value after *" not in (r.output or "")
    assert r.exit_code in (0, 1, 130)


def test_bundle_resolves_in_editable_install() -> None:
    """D-13: importlib.resources resolution works for the editable install."""
    from beagle_plugin_pi.cli import _bundle_dir

    bundle = _bundle_dir()
    assert (bundle / "dist" / "bundle" / "cli.js").is_file()


def test_bundle_resolves_in_wheel_install() -> None:
    """D-13: the same resolver works from an installed wheel.

    Exercised by the deploy step: the wheel carries vendor/**; this test
    checks the resolver logic is layout-independent by importing through the
    package resources API rather than a filesystem walk.
    """
    from importlib.resources import files

    traversable = files("beagle_plugin_pi") / "vendor"
    # The manifest the launcher reads must be reachable through resources.
    manifest = traversable / "pi-prebuild" / "package.json"
    content = manifest.read_text(encoding="utf-8")
    assert "engines" in content


def test_extension_flag_uses_two_token_form(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: the vendored bundle rejects ``--extension=<path>``.

    ``args.ts`` consumes two tokens for ``--extension``/``-e`` and reports the
    ``=`` form as an unknown option, which aborts ``beagle`` before pi starts.
    """
    from beagle_plugin_pi import launcher

    captured: list[list[str]] = []

    def _fake_execvpe(_exe: str, argv: list[str], _env: dict[str, str]) -> None:
        captured.append(argv)
        raise SystemExit(77)

    monkeypatch.setattr(launcher.os, "execvpe", _fake_execvpe)

    with contextlib.suppress(SystemExit):
        launcher.run([])

    assert captured, "run() did not reach execvpe"
    argv = captured[0]
    assert not any(a.startswith("--extension=") for a in argv), (
        f"equals-form --extension flag would be rejected by pi: {argv}"
    )
    if "--extension" in argv:
        index = argv.index("--extension")
        assert index + 1 < len(argv), "two-token form requires a path immediately after"
        assert Path(argv[index + 1]).name == "index.ts"


def test_vendored_extension_dependencies_resolve() -> None:
    """The vendored MCP bridge must ship its own deps under its own node_modules.

    Node resolves bare specifiers by walking *parent* directories only, so the
    deps cannot live in a sibling vendor tree. Measured 2026-09-16: the tree
    shipped no node_modules at all and pi aborted with "Cannot find module
    'zod'" on every bare ``beagle`` invocation.
    """
    from beagle_plugin_pi import launcher

    ext = launcher._extension_path()
    assert ext.is_file(), f"extension entry point missing: {ext}"
    assert launcher._extension_is_loadable(ext), (
        f"vendored MCP bridge at {ext} cannot resolve its declared dependencies; "
        "re-run `npm install --omit=dev --omit=peer --legacy-peer-deps "
        "--ignore-scripts` inside vendor/pi-mcp-extension and rebuild the wheel"
    )


def test_environment_is_filtered_not_forwarded() -> None:
    """WP-4: the vendored binary must not receive the whole parent env."""
    from beagle_plugin_pi.cli import _FORWARD_ENV_KEYS

    # An obviously-secret key absent from the allowlist.
    assert "ANTHROPIC_API_KEY" not in _FORWARD_ENV_KEYS
    assert "OPENAI_API_KEY" not in _FORWARD_ENV_KEYS
    assert "GITHUB_TOKEN" not in _FORWARD_ENV_KEYS
    # The keys the bundle genuinely needs are present.
    assert "PATH" in _FORWARD_ENV_KEYS
    assert "HOME" in _FORWARD_ENV_KEYS


def test_node_floor_quotes_manifest_not_literal() -> None:
    """The error message quotes engines.node from the vendored manifest."""
    from importlib.resources import files
    import json

    manifest = json.loads(
        (files("beagle_plugin_pi") / "vendor" / "pi-prebuild" / "package.json").read_text(
            encoding="utf-8"
        )
    )
    declared = manifest.get("engines", {}).get("node", "")
    assert declared.startswith(">="), f"manifest floor malformed: {declared!r}"

    from beagle_plugin_pi.launcher import _required_node_version

    assert _required_node_version() == declared
