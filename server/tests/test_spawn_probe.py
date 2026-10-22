"""The spawn rules' synthetic probe (tests/world_spawn_probe, C#): the 88/18/3 lottery, the occurrence rules from the Witcher
wiki's bestiary (natural environments off streets, rain roaming, day and night, the full moon, multiplying boosts), the
level gate, and pinned hashes of generated worlds. It needs no server, profile or network."""
import json
import subprocess
import unittest

from dev import ROOT, DOTNET, environment


class SpawnProbeTests(unittest.TestCase):
    def test_the_spawn_probe_passes(self):
        result = subprocess.run([str(DOTNET), 'run', '--project', str(ROOT / 'tests' / 'world_spawn_probe'), '-c', 'Release'],
                                capture_output=True, text=True, cwd=ROOT, env=environment(), timeout=900)
        self.assertEqual(result.returncode, 0, result.stdout[-3000:] + result.stderr[-3000:])
        self.assertEqual(json.loads(result.stdout.strip().splitlines()[-1])['status'], 'PASS')


if __name__ == '__main__':
    unittest.main()
