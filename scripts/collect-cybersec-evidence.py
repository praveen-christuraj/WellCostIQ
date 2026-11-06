#!/usr/bin/env python3
"""Collect traceable review snapshots outside the repository, never credentials."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def source_metadata() -> dict[str, object]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    worktree = subprocess.run(
        ["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    dirty = bool(worktree.stdout.strip())
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    return {
        "source_commit": commit.stdout.strip() if commit.returncode == 0 else "unknown",
        "source_worktree_dirty": dirty,
        "ci_run_id": run_id or None,
        "ci_run_url": f"{server}/{repository}/actions/runs/{run_id}" if run_id and repository else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--tools-bin", type=Path, help="Pinned security-tools virtualenv bin directory")
    parser.add_argument("--image", action="append", default=[], help="Built image name:tag; repeat for API/web")
    parser.add_argument("--pg-service", help="Existing pg_service.conf entry; never pass credentials")
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    if output == ROOT or ROOT in output.parents:
        parser.error("Save evidence outside the repository.")
    if args.pg_service and not re.fullmatch(r"[A-Za-z0-9_-]+", args.pg_service):
        parser.error("Use a simple pg_service.conf entry name.")
    output.mkdir(parents=True, exist_ok=True)
    statuses: list[dict[str, object]] = []
    expected_files = {"collection-status.json", "EXPECTED_FILES"}
    env = os.environ.copy()
    if args.tools_bin:
        env["PATH"] = str(args.tools_bin.resolve()) + os.pathsep + env.get("PATH", "")
    provenance = source_metadata()

    def collect(filename: str, command: list[str], cwd: Path = ROOT) -> None:
        expected_files.add(filename)
        expected_files.add(filename + ".metadata.json")
        executable = shutil.which(command[0], path=env.get("PATH"))
        metadata: dict[str, object] = {
            **provenance,
            "file": filename,
            "tool": command[0],
            "tool_version": None,
            "command": command,
            "working_directory": str(cwd),
            "exit_code": None,
            "collected_at_utc": utcnow(),
        }
        if not executable:
            statuses.append({
                **metadata,
                "status": "not-collected",
                "reason": command[0] + " is not installed",
            })
            return
        version = subprocess.run(
            [executable, "--version"], cwd=cwd, env=env, capture_output=True, text=True, check=False
        )
        version_text = (version.stdout or version.stderr).strip().splitlines()
        metadata["tool_version"] = version_text[0] if version_text else "unknown"
        result = subprocess.run([executable, *command[1:]], cwd=cwd, env=env, capture_output=True)
        metadata["exit_code"] = result.returncode
        metadata["collected_at_utc"] = utcnow()
        (output / filename).write_bytes(result.stdout)
        (output / (filename + ".metadata.json")).write_text(json.dumps(metadata, indent=2) + "\n")
        if result.stderr:
            stderr_name = filename + ".stderr.txt"
            (output / stderr_name).write_bytes(result.stderr)
            expected_files.add(stderr_name)
        statuses.append({
            **metadata,
            "status": "collected" if result.returncode == 0 else "review-required",
        })

    collect("npm-audit-report.json", ["npm", "audit", "--json"], ROOT / "frontend")
    collect("npm-outdated-q.txt", ["npm", "outdated"], ROOT / "frontend")
    collect("pip-audit-report.json", ["pip-audit", "-r", str(ROOT / "backend/requirements.txt"), "-f", "json"])
    collect("vscode-extensions.txt", ["code", "--list-extensions", "--show-versions"])
    if args.pg_service:
        collect(
            "postgresql-inventory.txt",
            ["psql", "service=" + args.pg_service, "-X", "-v", "ON_ERROR_STOP=1", "-f", str(ROOT / "scripts/postgres-inventory.sql")],
        )
    else:
        statuses.append({
            **provenance,
            "file": "postgresql-inventory.txt",
            "tool": "psql",
            "tool_version": None,
            "command": None,
            "exit_code": None,
            "status": "not-collected",
            "reason": "No live PostgreSQL service was supplied.",
            "collected_at_utc": utcnow(),
        })
        expected_files.add("postgresql-inventory.txt")
        expected_files.add("postgresql-inventory.txt.metadata.json")
    for number, image in enumerate(args.image, 1):
        collect(
            f"image-{number}-identifier.txt",
            ["docker", "image", "inspect", "--format", "{{.Id}} {{json .RepoDigests}}", image],
        )
        collect(
            f"image-{number}-packages.txt",
            [
                "docker", "run", "--rm", "--network=none", "--entrypoint", "sh", image, "-c",
                "if command -v dpkg >/dev/null; then dpkg -l; elif command -v apk >/dev/null; "
                "then apk --no-network info -vv; else exit 2; fi",
            ],
        )

    (output / "EXPECTED_FILES").write_text("".join(name + "\n" for name in sorted(expected_files)))
    missing = sorted(
        name for name in expected_files
        if name != "collection-status.json" and not (output / name).is_file()
    )
    status = {
        **provenance,
        "collected_at_utc": utcnow(),
        "scope": "This host and explicitly supplied images/database only; no hosted dashboard evidence.",
        "expected_files": sorted(expected_files),
        "missing_expected_files": missing,
        "results": statuses,
    }
    (output / "collection-status.json").write_text(json.dumps(status, indent=2) + "\n")

    # Keep the checksum manifest outside the delivered evidence directory so an
    # omitted artifact is visible against EXPECTED_FILES. Sign this separate file
    # with the organisation's release key; do not store that key in the bundle.
    manifest = output.parent / (output.name + ".SHA256SUMS")
    lines = []
    for path in sorted(item for item in output.rglob("*") if item.is_file()):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {output.name}/{path.relative_to(output)}\n")
    manifest.write_text("".join(lines))
    print(f"Evidence saved to {output}; checksum manifest: {manifest}")
    print("Review collection-status.json for missing evidence and nonzero scan results.")
    return 1 if missing or any(item["status"] == "review-required" for item in statuses) else 0


if __name__ == "__main__":
    raise SystemExit(main())
