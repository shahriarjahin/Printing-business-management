"""Offline restore; stop the application first. Preserves a pre-restore copy."""
import os
import re
import secrets
import shutil
import sqlite3
import sys
import zipfile
from pathlib import Path

root = Path(os.environ.get('DATA_DIR', '/data')).resolve()
if len(sys.argv) != 2:
    raise SystemExit('Usage: python restore_backup.py /path/to/digitxbd-backup.zip (application must be stopped)')
stage = root / ('restore-stage-' + secrets.token_hex(8))
stage.mkdir()
with zipfile.ZipFile(sys.argv[1]) as archive:
    names = archive.namelist()
    if len(names) != len(set(names)) or 'digitxbd.sqlite' not in names:
        raise SystemExit('Invalid backup structure.')
    for info in archive.infolist():
        if info.filename != 'digitxbd.sqlite' and not re.fullmatch(r'uploads/[a-f0-9]{40}\.[a-z0-9]+', info.filename):
            raise SystemExit('Unexpected backup path: ' + info.filename)
        target = (stage / info.filename).resolve()
        target.relative_to(stage.resolve())
        target.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(info) as source, target.open('wb') as destination:
            shutil.copyfileobj(source, destination)
conn = sqlite3.connect(stage / 'digitxbd.sqlite')
if conn.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
    raise SystemExit('Database integrity check failed; existing data has not been changed.')
required = {'customers', 'ledger', 'expenses', 'users', 'orders', 'files', 'settings', 'audit'}
tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
if not required.issubset(tables):
    raise SystemExit('Backup is not a compatible DigitXBD database.')
# A restored queue must never repeat old physical prints automatically.
if 'print_jobs' in tables:
    conn.execute("UPDATE print_jobs SET status='cancelled',claim_key=NULL,detail='Cancelled during backup restore; review before printing again.' WHERE status IN ('queued','claimed','uncertain')")
if 'print_agent' in tables:
    conn.execute('DELETE FROM print_agent')
conn.commit()
conn.close()
previous = root / ('pre-restore-' + secrets.token_hex(8))
previous.mkdir()
for name in ('digitxbd.sqlite', 'digitxbd.sqlite-wal', 'digitxbd.sqlite-shm', 'uploads'):
    current = (root / name).resolve()
    current.relative_to(root)
    if current.exists():
        if name=='uploads':
            # Preserve the mount point: uploads may be a folder on the host computer.
            (previous/'uploads').mkdir()
            for child in current.iterdir():
                shutil.move(str(child),str(previous/'uploads'/child.name))
        else:
            current.rename(previous / name)
(stage / 'digitxbd.sqlite').rename(root / 'digitxbd.sqlite')
if (stage / 'uploads').exists():
    (root/'uploads').mkdir(exist_ok=True)
    for child in (stage/'uploads').iterdir():
        shutil.move(str(child),str(root/'uploads'/child.name))
    (stage/'uploads').rmdir()
else:
    (root / 'uploads').mkdir(exist_ok=True)
stage.rmdir()
print('Restore complete. Previous files retained at', previous)
