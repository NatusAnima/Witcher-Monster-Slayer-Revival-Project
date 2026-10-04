#!/usr/bin/env python3
"""Apply one panel-validated catalogue while the task-enabled game process is stopped.

The catalogue lock is the same Unix advisory lock used by TaskCatalog's FileShare.None.
No identity index, key or profile is read or changed. Backups and receipts stay private.
"""
import argparse
import contextlib
import datetime
import fcntl
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

NAMES = ('daily.json', 'hunt.json', 'timed.json', 'trinkets.json')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def atomic(path, data):
    descriptor, pending = tempfile.mkstemp(prefix='.'+path.name+'.', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(pending, path)
    finally:
        if os.path.exists(pending): os.unlink(pending)


def apply(admin, tasks, profiles, operation):
    if not re.fullmatch(r'\d{8}T\d{13}-[a-f0-9]{12}', operation):
        raise ValueError('Invalid operation ID.')
    receipt_path = admin/'receipts'/(operation+'.json')
    receipt = json.loads(receipt_path.read_text())
    if receipt['id'] != operation or receipt['action'] != 'task-catalogue' or receipt['outcome'] != 'staged':
        raise ValueError('The operation is not an unapplied staged catalogue.')
    stage = admin/'staged'/operation
    manifest = json.loads((stage/'manifest.json').read_text())
    candidate_bytes = (stage/'catalogue.json').read_bytes()
    if manifest['operation'] != operation or manifest['catalogueSha256'] != digest(candidate_bytes) or receipt['after'] != digest(candidate_bytes):
        raise ValueError('Staged catalogue identity mismatch.')
    candidate = json.loads(candidate_bytes)
    if set(candidate) != {'daily', 'hunt', 'timed', 'trinkets'} or set(manifest['before']) != set(NAMES):
        raise ValueError('Invalid staged manifest.')
    # Open only the known lock, never the identity key or saved profile data.
    with (profiles/'tasks-catalogue.lock').open('r+b') as lock:
        try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: raise ValueError('Stop the task-enabled game service before applying a catalogue.') from None
        previous = {name: (tasks/name).read_bytes() for name in NAMES}
        if any(digest(previous[name]) != manifest['before'][name] for name in NAMES):
            raise ValueError('Active task files changed since review; stage a fresh catalogue.')
        backup = admin/'backups'/(operation+'-tasks')
        backup.mkdir(mode=0o700, exist_ok=False)
        for name in NAMES: atomic(backup/name, previous[name])
        changed = []
        try:
            for name in NAMES:
                atomic(tasks/name, (json.dumps(candidate[name[:-5]], ensure_ascii=False, indent=2)+'\n').encode())
                changed.append(name)
            receipt.update(outcome='applied', effect='Catalogue files applied during maintenance. Restart server and LAB to load the new definitions.',
                           at=datetime.datetime.now(datetime.timezone.utc).isoformat())
            atomic(receipt_path, (json.dumps(receipt, ensure_ascii=False, indent=2)+'\n').encode())
        except BaseException:
            for name in changed: atomic(tasks/name, previous[name])
            raise
    return {'status':'applied', 'operation':operation, 'files':len(NAMES), 'restartRequired':True}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--admin-directory', required=True, type=Path)
    parser.add_argument('--tasks-directory', required=True, type=Path)
    parser.add_argument('--profiles-directory', required=True, type=Path)
    parser.add_argument('--operation-id', required=True)
    args=parser.parse_args()
    try:
        result=apply(args.admin_directory.resolve(strict=True), args.tasks_directory.resolve(strict=True),
                     args.profiles_directory.resolve(strict=True),args.operation_id)
    except (OSError, ValueError, KeyError) as error:
        print(json.dumps({'status':'refused','reason':str(error) if isinstance(error, ValueError) else type(error).__name__}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == '__main__': raise SystemExit(main())
