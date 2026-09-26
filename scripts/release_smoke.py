"""Keep smoke tests on the published driver versions selected at job start."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from importlib import metadata
from pathlib import Path

DRIVERS = ("pycubrid", "sqlalchemy-cubrid")


def installed_drivers() -> dict[str, dict[str, str | None]]:
    result = {}
    for name in DRIVERS:
        dist = metadata.distribution(name)
        direct_url = dist.read_text("direct_url.json")
        if direct_url is not None:
            raise ValueError(f"{name} must be installed from the package index, not a direct URL")
        result[name] = {"version": dist.version, "direct_url": direct_url}
    return result


def freeze(state: Path, constraints: Path) -> None:
    selected = installed_drivers()
    state.write_text(json.dumps(selected, indent=2) + "\n", encoding="utf-8")
    constraints.write_text(
        "".join(f"{name}=={selected[name]['version']}\n" for name in DRIVERS),
        encoding="utf-8",
    )


def verify(state: Path) -> None:
    selected = json.loads(state.read_text(encoding="utf-8"))
    installed = installed_drivers()
    if installed != selected:
        raise ValueError(
            f"Smoke driver versions changed: selected {selected}, installed {installed}"
        )


def install_examples(root: Path, constraints: Path) -> None:
    if not constraints.is_file():
        raise ValueError(f"Missing release constraints: {constraints}")
    roots = sorted({p.parent for p in root.glob("**/expected") if p.is_dir()})
    for example in roots:
        if any(part.startswith(".") for part in example.relative_to(root).parts):
            continue
        requirements = example / "requirements.txt"
        if requirements.is_file():
            print(f"Installing example requirements: {requirements}", file=sys.stderr)
            subprocess.check_call(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "--constraint",
                    str(constraints.resolve()),
                    "-r",
                    str(requirements),
                ]
            )


def report() -> None:
    print("### Tested upstream versions\n")
    print("| Package | Version |")
    print("| --- | --- |")
    for name in (*DRIVERS, "cubrid-mcp-server"):
        print(f"| {name} | {metadata.version(name)} |")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    snapshot = commands.add_parser("freeze")
    snapshot.add_argument("--state", type=Path, required=True)
    snapshot.add_argument("--constraints", type=Path, required=True)
    install = commands.add_parser("install-examples")
    install.add_argument("--root", type=Path, default=Path("."))
    install.add_argument("--constraints", type=Path, required=True)
    check = commands.add_parser("verify")
    check.add_argument("--state", type=Path, required=True)
    check.add_argument("--report", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "freeze":
            freeze(args.state, args.constraints)
        elif args.command == "install-examples":
            install_examples(args.root, args.constraints)
        else:
            verify(args.state)
            if args.report:
                report()
    except (ValueError, metadata.PackageNotFoundError) as error:
        parser.exit(1, f"Release smoke check failed: {error}\n")


if __name__ == "__main__":
    main()
