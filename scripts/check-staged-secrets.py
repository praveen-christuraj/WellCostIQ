#!/usr/bin/env python3
"""Check the actual staged bytes, without an automatic suppression baseline."""
from pathlib import Path
import subprocess
import tempfile

names = subprocess.check_output(['git', 'diff', '--cached', '--name-only', '--diff-filter=ACMR', '-z']).decode().split('\0')
with tempfile.TemporaryDirectory(prefix='wellcostiq-secrets-') as folder:
    files = []
    for name in filter(None, names):
        target = Path(folder) / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(subprocess.check_output(['git', 'show', ':' + name]))
        files.append(str(target))
    if files:
        raise SystemExit(subprocess.run(['detect-secrets-hook', *files]).returncode)
