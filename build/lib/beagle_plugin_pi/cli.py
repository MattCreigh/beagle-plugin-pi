"""pi+beagle — launch the vendored pi coding-agent frontend as a plugin.

Port of beagle/cli/commands/pi.py with all three WP-4 defects fixed at port
time: the argument contract (D-12), the unreachable resolver branches (D-13),
and the environment filtering (WP-4 instruction: never forward the whole
parent environment to a vendored third-party binary).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from importlib.resources import files
from pathlib import Path
from typing import Annotated

import typer

pi_app = typer.Typer(name="pi", help="pi+beagle coding-agent frontend")

_VENDOR_SUBPATH = Path("pi-prebuild")

# Only these parent-environment keys reach the vendored node process. The
# plugin is third-party MIT code: an unfiltered env would forward API keys,
# tokens and any secret the host holds to a binary the operator did not audit.
_FORWARD_ENV_KEYS = (
    "PATH",
    "HOME",
    "LANG",
    "LC_ALL",
    "TERM",
    "USER",
    "TMPDIR",
    "SHELL",
    "NODE_OPTIONS",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
    "XDG_CACHE_HOME",
    "DISPLAY",
    "WAYLAND_DISPLAY",
    "SSH_AUTH_SOCK",
    "NO_COLOR",
    "FORCE_COLOR",
)


def _bundle_dir() -> Path:
    """Resolve the vendored pi bundle directory.

    Uses ``importlib.resources``, which is correct for both an installed
    wheel and an editable install — the class of defect the removed fallback
    branches embodied (D-13: a five-parent walk to a path that never existed).
    """
    vendor = files("beagle_plugin_pi") / "vendor"
    # files() returns a Traversable; the bundle needs a real filesystem path
    # to hand to node, and the wheel ships it as real files (not zipped).
    bundle = Path(str(vendor)) / "pi-prebuild"
    if (bundle / "dist" / "bundle" / "cli.js").is_file():
        return bundle
    typer.echo(
        "pi frontend bundle not found. Reinstall beagle-plugin-pi "
        "(the bundle ships in the wheel).",
        err=True,
    )
    raise typer.Exit(1)


def _mcp_server_script() -> Path | None:
    """Locate Beagle's MCP server entry point in the host environment."""
    try:
        import beagle.infrastructure.mcp_beagle_server as _srv

        return Path(_srv.__file__)
    except (ImportError, OSError):
        return None


@pi_app.command()
def pi(
    args: Annotated[
        list[str] | None,
        typer.Argument(help="Arguments forwarded to the pi CLI."),
    ] = None,
    mcp: Annotated[
        bool,
        typer.Option(
            "--mcp",
            help="Start Beagle's MCP server so pi can call Beagle workflows.",
        ),
    ] = False,
) -> None:
    """Launch the vendored pi coding agent frontend."""
    forwarded = list(args or [])
    node = shutil.which("node")
    if not node:
        # Single source for the floor: the vendored manifest, per 625a03f.
        from beagle_plugin_pi.launcher import _required_node_version

        declared = _required_node_version()
        requirement = f" ({declared})" if declared else ""
        typer.echo(
            f"Node.js{requirement} is required to run the pi frontend. "
            "Install Node or add it to PATH.",
            err=True,
        )
        raise typer.Exit(1)

    bundle = _bundle_dir() / "dist" / "bundle" / "cli.js"

    env = {k: os.environ[k] for k in _FORWARD_ENV_KEYS if k in os.environ}
    if mcp:
        script = _mcp_server_script()
        if script is None:
            typer.echo("Beagle MCP server not found.", err=True)
            raise typer.Exit(1)
        env["BEAGLE_MCP_SERVER"] = str(script)

    cmd = [node, str(bundle), *forwarded]
    try:
        raise typer.Exit(subprocess.call(cmd, env=env))
    except KeyboardInterrupt:
        raise typer.Exit(130) from None


app = pi_app