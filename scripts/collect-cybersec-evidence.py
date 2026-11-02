#!/usr/bin/env python3
"""Collect review snapshots outside the repository without printing credentials."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--tools-bin', type=Path, help='Pinned security-tools virtualenv bin directory')
    parser.add_argument('--image', action='append', default=[], help='Built image name:tag; repeat for API/web')
    parser.add_argument('--pg-service', help='Existing pg_service.conf entry; never pass credentials')
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    if output == ROOT or ROOT in output.parents:
        parser.error('Save evidence outside the repository.')
    if args.pg_service and not re.fullmatch(r'[A-Za-z0-9_-]+', args.pg_service):
        parser.error('Use a simple pg_service.conf entry name.')
    output.mkdir(parents=True, exist_ok=True)
    statuses = []
    env = os.environ.copy()
    if args.tools_bin:
        env['PATH'] = str(args.tools_bin.resolve()) + os.pathsep + env.get('PATH', '')

    def collect(filename, command, cwd=ROOT):
        executable = shutil.which(command[0], path=env.get('PATH'))
        if not executable:
            statuses.append({'file': filename, 'status': 'not-collected', 'reason': command[0] + ' is not installed'})
            return
        result = subprocess.run([executable, *command[1:]], cwd=cwd, env=env, capture_output=True)
        (output / filename).write_bytes(result.stdout)
        if result.stderr:
            (output / (filename + '.stderr.txt')).write_bytes(result.stderr)
        statuses.append({'file': filename, 'status': 'collected' if result.returncode == 0 else 'review-required', 'exit_code': result.returncode})

    collect('npm-audit-report.json', ['npm', 'audit', '--json'], ROOT / 'frontend')
    collect('npm-outdated-q.txt', ['npm', 'outdated'], ROOT / 'frontend')
    collect('pip-audit-report.json', ['pip-audit', '-r', str(ROOT / 'backend/requirements.txt'), '-f', 'json'])
    collect('vscode-extensions.txt', ['code', '--list-extensions', '--show-versions'])
    if args.pg_service:
        collect('postgresql-inventory.txt', ['psql', 'service=' + args.pg_service, '-X', '-v', 'ON_ERROR_STOP=1', '-f', str(ROOT / 'scripts/postgres-inventory.sql')])
    else:
        statuses.append({'file': 'postgresql-inventory.txt', 'status': 'not-collected', 'reason': 'No live PostgreSQL service was supplied.'})
    for number, image in enumerate(args.image, 1):
        collect(f'image-{number}-identifier.txt', ['docker', 'image', 'inspect', '--format', '{{.Id}} {{json .RepoDigests}}', image])
        collect(f'image-{number}-packages.txt', ['docker', 'run', '--rm', '--network=none', '--entrypoint', 'sh', image, '-c', 'if command -v dpkg >/dev/null; then dpkg -l; elif command -v apk >/dev/null; then apk --no-network info -vv; else exit 2; fi'])
    status = {'collected_at_utc': datetime.now(timezone.utc).isoformat(), 'scope': 'This host and explicitly supplied images/database only.', 'results': statuses}
    (output / 'collection-status.json').write_text(json.dumps(status, indent=2) + '\n')
    print('Evidence saved to ' + str(output) + '. Review collection-status.json for missing evidence and nonzero scan results.')
    return 1 if any(s['status'] == 'review-required' for s in statuses) else 0


if __name__ == '__main__':
    raise SystemExit(main())
