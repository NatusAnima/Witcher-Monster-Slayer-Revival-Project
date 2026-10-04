#!/usr/bin/env python3
"""Correct the known hound/leshen catalogue error and one false award offline.

Requires explicit directories, profile ID and reviewed hashes. Defaults to preview.
Only achievement 20002, its two catalogue species lists and the profile revision
can change. Backups and receipts contain private player data; never publish them.
"""
import argparse
import contextlib
import copy
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile

ACHIEVEMENT = 20002
SLUG = 'trophy_in_forest_dark'
OLD_SPECIES = [166, 30]
NEW_SPECIES = [31]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()


def regular(path, maximum=8*1024*1024):
    if path.absolute() != path.resolve(strict=True) or not path.is_file() or path.stat().st_size > maximum:
        raise ValueError('Expected a bounded regular file without symbolic links.')
    return path.read_bytes()


def atomic(path, data, mode):
    descriptor, pending = tempfile.mkstemp(prefix='.'+path.name+'.', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.replace(pending, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(directory)
        finally: os.close(directory)
    finally:
        if os.path.exists(pending): os.unlink(pending)


def corrected_definition(document):
    rows = document['trinkets']
    matches = [row for row in rows if row['id'] == ACHIEVEMENT or row['slug'] == SLUG]
    if len(matches) != 1:
        raise ValueError('Expected exactly one known trinket definition.')
    row = matches[0]
    if (row['id'], row['slug'], row['type'], row['target'], row.get('monsters')) != (ACHIEVEMENT, SLUG, 1, 1, OLD_SPECIES):
        raise ValueError('The catalogue is not the known erroneous definition.')
    row['monsters'] = NEW_SPECIES.copy()


def prepare(before, profile_id):
    source = {key: json.loads(value) for key, value in before.items()}
    after = copy.deepcopy(source)
    corrected_definition(after['trinkets'])
    corrected_definition(after['manifest']['trinkets'])
    profile = after['profile']
    if profile.get('SchemaVersion') != 2 or profile.get('ProfileId') != profile_id or type(profile.get('Revision')) is not int or not 0 <= profile['Revision'] < (1 << 63)-1:
        raise ValueError('Unexpected profile schema, identity or revision.')
    player = profile['Player']
    kills = player.get('Kills') or {}
    if any(kills.get(str(i), 0) > 0 for i in (31, 103)):
        raise ValueError('A leshen kill exists; refusing to remove a potentially earned award.')
    if sum(kills.get(str(i), 0) for i in OLD_SPECIES) < 1:
        raise ValueError('No hound kill supports the known erroneous award.')
    awards = player['Tasks']['Achievements']
    if str(ACHIEVEMENT) not in awards:
        raise ValueError('The selected profile does not have this award.')
    del awards[str(ACHIEVEMENT)]
    profile['Revision'] += 1
    # Prove that the selected player's complete remaining state is retained.
    compare = copy.deepcopy(profile)
    compare['Revision'] = source['profile']['Revision']
    compare['Player']['Tasks']['Achievements'][str(ACHIEVEMENT)] = source['profile']['Player']['Tasks']['Achievements'][str(ACHIEVEMENT)]
    if compare != source['profile']:
        raise ValueError('Unexpected player-state change.')
    return {key: encoded(value) for key, value in after.items()}


def repair(tasks, profiles, profile_id, backup, expected, *, apply=False):
    tasks, profiles, backup = map(Path, (tasks, profiles, backup))
    if not re.fullmatch(r'p[0-9a-f]{31}', profile_id):
        raise ValueError('Expected one explicit registry profile ID.')
    for path in (tasks, profiles):
        if path.absolute() != path.resolve(strict=True) or not path.is_dir():
            raise ValueError('Expected an existing directory without symbolic links.')
    paths = {'trinkets': tasks/'trinkets.json', 'manifest': profiles/'tasks-catalogue.json', 'profile': profiles/(profile_id+'.json')}
    if set(expected) != set(paths) or any(not re.fullmatch(r'[0-9a-f]{64}', v) for v in expected.values()):
        raise ValueError('All three reviewed SHA-256 values are required.')
    with contextlib.ExitStack() as stack:
        for name in ('tasks-catalogue.lock', profile_id+'.lock'):
            lock_path = profiles/name
            regular(lock_path, 1024)
            handle = stack.enter_context(lock_path.open('r+b'))
            try: fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError('Stop the task-enabled server and release the profile before repair.') from None
        before = {key: regular(path) for key, path in paths.items()}
        if any(digest(value) != expected[key] for key, value in before.items()):
            raise ValueError('A reviewed file changed; prepare a fresh preview.')
        after = prepare(before, profile_id)
        record = {'status': 'preview', 'achievement': ACHIEVEMENT, 'species_before': OLD_SPECIES, 'species_after': NEW_SPECIES,
                  'profile_changes': ['Revision', 'Player.Tasks.Achievements.20002'], 'unrelated_state_preserved': True,
                  'before_sha256': expected, 'after_sha256': {key: digest(value) for key, value in after.items()},
                  'at': datetime.datetime.now(datetime.timezone.utc).isoformat()}
        if not apply: return record
        parent = backup.parent
        if parent.absolute() != parent.resolve(strict=True) or not parent.is_dir() or backup.exists():
            raise ValueError('Backup must be a new directory below an existing non-symlink parent.')
        if any(backup == path or path in backup.parents or backup in path.parents for path in (tasks, profiles)):
            raise ValueError('Backup overlaps a repair target.')
        modes = {key: stat.S_IMODE(path.stat().st_mode) for key, path in paths.items()}
        backup.mkdir(mode=0o700)
        for key, value in before.items():
            atomic(backup/(key+'.before.json'), value, 0o600)
            if regular(backup/(key+'.before.json')) != value:
                raise ValueError('Backup verification failed before mutation.')
        record['original_modes'] = modes
        atomic(backup/'receipt.json', encoded(record), 0o600)
        changed = []
        try:
            if any(regular(paths[key]) != value for key, value in before.items()):
                raise ValueError('A repair target changed after backup.')
            for key, value in after.items():
                changed.append(key)
                atomic(paths[key], value, modes[key])
            if any(regular(paths[key]) != value for key, value in after.items()):
                raise ValueError('Repair verification failed.')
            record['status'] = 'applied'
            atomic(backup/'receipt.json', encoded(record), 0o600)
        except BaseException:
            for key in reversed(changed): atomic(paths[key], before[key], modes[key])
            record['status'] = 'rolled_back'
            atomic(backup/'receipt.json', encoded(record), 0o600)
            raise
        return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('tasks-directory', 'profiles-directory', 'backup-directory', 'expected-hashes'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--profile-id', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        result = repair(args.tasks_directory, args.profiles_directory, args.profile_id, args.backup_directory,
                        json.loads(regular(args.expected_hashes)), apply=args.apply)
    except (OSError, ValueError, KeyError, TypeError):
        print(json.dumps({'status': 'refused', 'reason': 'Input, lock, backup or validation check failed; no private values emitted.'}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == '__main__': raise SystemExit(main())
