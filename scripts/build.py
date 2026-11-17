"""Build the distributable Python package, viewer included.

    uv run python scripts/build.py              # viewer, then wheel + sdist into dist/
    uv run python scripts/build.py --no-viewer   # reuse an existing viewer build

The wheel carries the built viewer, so `pip install agent-xray` needs no Node.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VIEWER = ROOT / "viewer"
PYTHON = ROOT / "python"
STATIC = PYTHON / "agent_xray" / "static"


def run(cmd: list[str], cwd: Path) -> None:
    print(f"$ {' '.join(cmd)}   (in {cwd.relative_to(ROOT) or '.'})", flush=True)
    # shutil.which finds pnpm.cmd on Windows
    resolved = shutil.which(cmd[0])
    subprocess.run([resolved or cmd[0], *cmd[1:]], cwd=cwd, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-viewer", action="store_true", help="skip building the viewer")
    parser.add_argument("--out", default=str(ROOT / "dist"))
    args = parser.parse_args()

    if not args.no_viewer:
        if not (VIEWER / "node_modules").is_dir():
            run(["pnpm", "install", "--frozen-lockfile"], VIEWER)
        run(["pnpm", "build"], VIEWER)  # writes python/agent_xray/static
    if not (STATIC / "index.html").is_file():
        sys.exit(f"the viewer is not built: {STATIC / 'index.html'} is missing")

    # PyPI shows the readme and licence of the package directory
    shutil.copyfile(ROOT / "README.md", PYTHON / "README.md")
    shutil.copyfile(ROOT / "LICENSE", PYTHON / "LICENSE")

    out = Path(args.out)
    shutil.rmtree(out, ignore_errors=True)
    run(["uv", "build", str(PYTHON), "--out-dir", str(out)], ROOT)
    print("\nbuilt:", *sorted(p.name for p in out.iterdir()), sep="\n  ")


if __name__ == "__main__":
    main()
