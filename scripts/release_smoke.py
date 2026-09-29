"""Keep smoke tests on the published driver versions selected at job start."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from importlib import metadata
from pathlib import Path

DRIVERS = ("pycubrid", "sqlalchemy-cubrid")
PACKAGES = (*DRIVERS, "cubrid-mcp-server")
MANUAL_LATEST = "latest"  # workflow_dispatch default: no pinned release.
RELEASE_TAG = re.compile(r"v(0|[1-9][0-9]*)[.](0|[1-9][0-9]*)[.](0|[1-9][0-9]*)")


def read_request(event_name: str, event_path: Path | None) -> dict[str, str] | None:
    """Validate an upstream release dispatch or a pinned manual release run.

    Both sources are read from the event JSON, so request fields never enter shell code.
    A manual run without a package keeps the ordinary latest-release smoke behavior.
    """
    if event_name not in ("repository_dispatch", "workflow_dispatch"):
        return None
    if event_path is None or not event_path.is_file():
        raise ValueError("Release request requires an event JSON file")
    event = json.loads(event_path.read_text(encoding="utf-8"))
    if not isinstance(event, dict):
        raise ValueError("Release request event JSON must be an object")
    if event_name == "repository_dispatch":
        payload = event.get("client_payload")
        if not isinstance(payload, dict) or payload.get("package") not in PACKAGES:
            raise ValueError("Release dispatch package is not in the upstream allowlist")
        ref = payload.get("ref")
        if not isinstance(ref, str) or RELEASE_TAG.fullmatch(ref) is None:
            raise ValueError("Release dispatch ref must be canonical vMAJOR.MINOR.PATCH")
        return {"package": payload["package"], "ref": ref, "version": ref[1:]}
    inputs = event.get("inputs")
    if inputs is None:
        inputs = {}
    if not isinstance(inputs, dict):
        raise ValueError("Manual release inputs must be an object")
    package = inputs.get("package")
    version = inputs.get("version")
    if package in (None, "", MANUAL_LATEST):
        if version in (None, ""):
            return None
        raise ValueError("Manual release version requires a non-latest package")
    if package not in PACKAGES:
        raise ValueError("Manual release package must be one of " + ", ".join(PACKAGES))
    if not isinstance(version, str) or not version:
        raise ValueError("Manual release run requires a version such as 1.8.0 or v1.8.0")
    ref = version if version.startswith("v") else "v" + version
    if RELEASE_TAG.fullmatch(ref) is None:
        raise ValueError("Manual release version must be MAJOR.MINOR.PATCH or vMAJOR.MINOR.PATCH")
    return {"package": package, "ref": ref, "version": ref[1:]}


def request_source(event_name: str) -> str:
    return "manual release run" if event_name == "workflow_dispatch" else "release dispatch"


def indexed_package(name: str) -> dict[str, str | None]:
    dist = metadata.distribution(name)
    direct_url = dist.read_text("direct_url.json")
    if direct_url is not None:
        raise ValueError(f"{name} must be installed from the package index, not a direct URL")
    return {"version": dist.version, "direct_url": direct_url}


def verify_request(request: dict[str, str]) -> None:
    installed = indexed_package(request["package"])
    if installed["version"] != request["version"]:
        raise ValueError(
            f"Installed {request['package']} {installed['version']} differs from requested "
            f"release {request['version']}"
        )


def select_releases(
    event_name: str,
    event_path: Path | None,
    constraints: Path,
    attempts: int = 6,
    delay: int = 10,
    timeout: int = 60,
) -> None:
    request = read_request(event_name, event_path)
    bootstrap = [sys.executable, "-m", "pip", "install", *DRIVERS, "sqlalchemy"]
    if request is not None:
        requirement = f"{request['package']}=={request['version']}"
        constraints.write_text(requirement + "\n", encoding="utf-8")
        command = [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--index-url",
            "https://pypi.org/simple",
            "--constraint",
            str(constraints.resolve()),
            requirement,
        ]
        for attempt in range(1, attempts + 1):
            try:
                subprocess.run(command, check=True, timeout=timeout)
                break
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
                if attempt == attempts:
                    raise ValueError(
                        f"Requested release {requirement} unavailable after {attempts} attempts"
                    ) from error
                print(
                    f"Waiting for {requirement} publication ({attempt}/{attempts})", file=sys.stderr
                )
                time.sleep(delay)
        verify_request(request)
        bootstrap.extend(["--constraint", str(constraints.resolve())])
    subprocess.check_call(bootstrap)


def installed_drivers() -> dict[str, dict[str, str | None]]:
    result = {}
    for name in DRIVERS:
        result[name] = indexed_package(name)
    return result


def freeze(state: Path, constraints: Path, request: dict[str, str] | None = None) -> None:
    selected = installed_drivers()
    if request is not None:
        verify_request(request)
    state.write_text(
        json.dumps({"drivers": selected, "requested": request}, indent=2) + "\n", encoding="utf-8"
    )
    pins = {name: selected[name]["version"] for name in DRIVERS}
    if request is not None:
        pins[request["package"]] = request["version"]
    constraints.write_text(
        "".join(f"{name}=={version}\n" for name, version in pins.items()),
        encoding="utf-8",
    )


def verify(state: Path) -> None:
    selected = json.loads(state.read_text(encoding="utf-8"))
    installed = installed_drivers()
    drivers = selected.get("drivers", selected)  # Read older ephemeral snapshots as well.
    if installed != drivers:
        raise ValueError(
            f"Smoke driver versions changed: selected {drivers}, installed {installed}"
        )
    if selected.get("requested") is not None:
        verify_request(selected["requested"])


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


def install_mcp(state: Path) -> None:
    selected = json.loads(state.read_text(encoding="utf-8"))
    request = selected.get("requested")
    if request is not None and request["package"] == "cubrid-mcp-server":
        # Already installed exactly from PyPI; never substitute a git artifact.
        verify_request(request)
        return
    command = [sys.executable, "-m", "pip", "install"]
    try:
        subprocess.check_call([*command, "cubrid-mcp-server"])
    except subprocess.CalledProcessError:
        # Preserve the existing fallback when MCP is not the requested release.
        subprocess.check_call(
            [*command, "git+https://github.com/cubrid-lab/cubrid-mcp-server.git@v0.4.0"]
        )


def report() -> None:
    print("### Tested upstream versions\n")
    print("| Package | Version |")
    print("| --- | --- |")
    for name in (*DRIVERS, "cubrid-mcp-server"):
        print(f"| {name} | {metadata.version(name)} |")


def summary(
    event_name: str,
    event_path: Path | None,
    state: Path,
    commit: str,
    server: str,
    result: str,
) -> None:
    """Report facts even if selection, publication or validation failed."""
    request = None
    valid_request = True
    validation = "none (latest releases; not a release verification)"
    try:
        request = read_request(event_name, event_path)
        if request is not None:
            validation = f"{request_source(event_name)}: {request['package']} {request['ref']}"
    except (ValueError, OSError) as error:
        validation = f"invalid release request: {error}"
        valid_request = False
    verification = "unavailable"
    if state.is_file():
        try:
            verify(state)
            if request is not None:
                verify_request(request)
            verification = "passed"
        except (ValueError, OSError, metadata.PackageNotFoundError):
            verification = "failed"
    if not valid_request:
        verification = "failed"
    invalid_success = result == "success" and verification != "passed"
    if invalid_success:
        result = "failure"
    print("### Release smoke result\n")
    print("| Field | Actual |\n| --- | --- |")
    for name, value in (
        ("Request", validation),
        ("Verification commit", commit),
        ("CUBRID server", server),
        ("Verification", verification),
        ("Result", result),
    ):
        print(f"| {name} | {value or 'unavailable'} |")
    print("\n| Package | Requested | Installed | Origin |\n| --- | --- | --- | --- |")
    for name in PACKAGES:
        version = origin = "unavailable"
        try:
            dist = metadata.distribution(name)
            version = dist.version
            origin = (
                "package index" if dist.read_text("direct_url.json") is None else "direct URL / VCS"
            )
        except metadata.PackageNotFoundError:
            pass
        expected = (
            request["version"]
            if request is not None and request["package"] == name
            else "not requested"
        )
        print(f"| {name} | {expected} | {version} | {origin} |")
    if invalid_success:
        raise ValueError("A successful smoke result requires final version and origin verification")


def event_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--event-name", default=os.environ.get("GITHUB_EVENT_NAME", ""))
    parser.add_argument("--event-path", type=Path, default=os.environ.get("GITHUB_EVENT_PATH"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    select = commands.add_parser("select")
    event_arguments(select)
    select.add_argument("--constraints", type=Path, required=True)
    snapshot = commands.add_parser("freeze")
    event_arguments(snapshot)
    snapshot.add_argument("--state", type=Path, required=True)
    snapshot.add_argument("--constraints", type=Path, required=True)
    install = commands.add_parser("install-examples")
    install.add_argument("--root", type=Path, default=Path("."))
    install.add_argument("--constraints", type=Path, required=True)
    mcp = commands.add_parser("install-mcp")
    mcp.add_argument("--state", type=Path, required=True)
    check = commands.add_parser("verify")
    check.add_argument("--state", type=Path, required=True)
    check.add_argument("--report", action="store_true")
    final = commands.add_parser("summary")
    event_arguments(final)
    final.add_argument("--state", type=Path, required=True)
    final.add_argument("--commit", default=os.environ.get("GITHUB_SHA", ""))
    final.add_argument("--server", default=os.environ.get("CUBRID_SERVER_VERSION", "unavailable"))
    final.add_argument("--result", required=True)
    args = parser.parse_args()
    try:
        if args.command == "select":
            select_releases(args.event_name, args.event_path, args.constraints)
        elif args.command == "freeze":
            freeze(args.state, args.constraints, read_request(args.event_name, args.event_path))
        elif args.command == "install-examples":
            install_examples(args.root, args.constraints)
        elif args.command == "install-mcp":
            install_mcp(args.state)
        elif args.command == "verify":
            verify(args.state)
            if args.report:
                report()
        else:
            summary(
                args.event_name, args.event_path, args.state, args.commit, args.server, args.result
            )
    except (ValueError, OSError, metadata.PackageNotFoundError) as error:
        parser.exit(1, f"Release smoke check failed: {error}\n")


if __name__ == "__main__":
    main()
