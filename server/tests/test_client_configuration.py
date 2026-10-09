"""Opt-in driving-warning settings over both preload transports, with synthetic temporary data only."""
import gzip
import hashlib
import json
import tempfile
import unittest
import urllib.request
from pathlib import Path

from test_prototype import Client, I, Reader, Server


DEFAULT_ROWS = [
    {'id': 1, 'param_name': 'nestClearingExp', 'param_value': '500'},
    {'id': 2, 'param_name': 'nestDailyLimit', 'param_value': '3'},
    {'id': 3, 'param_name': 'nestPlayerMinimalLevel', 'param_value': '10'},
    {'id': 4, 'param_name': 'inventoryIncrement', 'param_value': '50'},
]
DRIVING_PARAMETERS = {'drivingWarningCooldown', 'drivingWarningMinSamples', 'drivingWarningMinSpeed'}


class ClientConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def start(self, configuration=None, name='synthetic-driving-settings'):
        server = Server(self.directory, name, configuration)
        self.addCleanup(server.stop)
        return server

    def containers(self, server):
        with urllib.request.urlopen(f'http://127.0.0.1:{server.http}/staticdata', timeout=3) as response:
            http = json.loads(gzip.decompress(response.read()))
        client = Client(server, auth=False)
        self.addCleanup(client.close)
        client.send(4, I(1) + I(0))
        channel, payload = client.receive()
        reader = Reader(payload)
        self.assertEqual((channel, reader.integer()), (4, 1))
        tcp = json.loads(gzip.decompress(reader.take(reader.integer())))
        self.assertEqual(reader.pos, len(payload))
        self.assertEqual(tcp, http)
        return http

    def test_unconfigured_defaults_add_no_driving_rows(self):
        data = self.containers(self.start())
        self.assertEqual(data['game_configuration'], DEFAULT_ROWS)
        self.assertFalse(DRIVING_PARAMETERS.intersection(row['param_name'] for row in data['game_configuration']))

    def test_overrides_match_between_http_and_tcp_and_preserve_other_tables(self):
        baseline = self.containers(self.start(name='synthetic-driving-baseline'))
        configured = self.containers(self.start({
            'Client__DrivingWarningCooldown': '120',
            'Client__DrivingWarningMinSamples': '12',
            'Client__DrivingWarningMinSpeedKmh': '40',
        }))
        rows = configured['game_configuration']
        self.assertEqual(rows[:len(DEFAULT_ROWS)], DEFAULT_ROWS)
        self.assertEqual({row['param_name']: row['param_value'] for row in rows[len(DEFAULT_ROWS):]}, {
            'drivingWarningCooldown': '120', 'drivingWarningMinSamples': '12', 'drivingWarningMinSpeed': '40',
        })
        self.assertEqual(len({row['id'] for row in rows}), len(rows))
        configured['game_configuration'] = rows[:len(DEFAULT_ROWS)]
        self.assertEqual(configured, baseline)

    def test_partial_configuration_leaves_unspecified_native_values_absent(self):
        data = self.containers(self.start({'Client__DrivingWarningMinSamples': '2'}))
        self.assertEqual(data['game_configuration'][:len(DEFAULT_ROWS)], DEFAULT_ROWS)
        self.assertEqual(data['game_configuration'][len(DEFAULT_ROWS):], [
            {'id': 1002, 'param_name': 'drivingWarningMinSamples', 'param_value': '2'},
        ])

    def test_snapshot_bytes_revision_and_https_bootstrap_agree(self):
        server = self.start({'Http__StaticDataUrl': 'https://game.example.test/staticdata',
                             'Reconstruction__ResolveFloorPercentPerRank': '5'})
        client = Client(server, auth=False)
        self.addCleanup(client.close)
        client.send(4, I(2) + I(0))
        channel, payload = client.receive()
        reader = Reader(payload)
        self.assertEqual((channel, reader.integer()), (4, 2))
        self.assertEqual(reader.string(), 'https://game.example.test/staticdata')
        with urllib.request.urlopen(f'http://127.0.0.1:{server.http}/staticdata') as response:
            body = response.read()
            etag = response.headers['ETag']
            self.assertEqual(etag, '"' + hashlib.sha256(body).hexdigest() + '"')
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
        # This native downloader has no proven conditional-response support.
        request = urllib.request.Request(f'http://127.0.0.1:{server.http}/staticdata', headers={'If-None-Match': etag})
        with urllib.request.urlopen(request) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.read(), body)
        client.send(4, I(1) + I(0))
        channel, payload = client.receive()
        reader = Reader(payload)
        self.assertEqual((channel, reader.integer()), (4, 1))
        self.assertEqual(reader.take(reader.integer()), body)

    def test_invalid_advertised_url_fails_before_player_storage(self):
        for index, value in enumerate(['http://game.example.test/staticdata',
                                      'https://' + 'synthetic-user' + ':' + 'synthetic-password@example.test/staticdata',
                                      'https://game.example.test/staticdata?key=invalid',
                                      'https://game.example.test/prototype/state']):
            with self.subTest(index=index):
                directory = self.directory / ('url-' + str(index)); directory.mkdir()
                with self.assertRaisesRegex(RuntimeError, 'Http:StaticDataUrl'):
                    Server(directory, 'synthetic-invalid-url', {'Http__StaticDataUrl': value})
                self.assertFalse((directory / 'profiles').exists())

    def test_invalid_configuration_fails_before_creating_player_data(self):
        invalid = {
            'Client__DrivingWarningCooldown': ['0', '-1', '', 'many', '1.5', '2147483648'],
            'Client__DrivingWarningMinSamples': ['0', '1', '-2', '3.0'],
            'Client__DrivingWarningMinSpeedKmh': ['0', '-20', 'slow'],
        }
        for key, values in invalid.items():
            for index, value in enumerate(values):
                with self.subTest(key=key, value=value):
                    directory = self.directory / (key + '-' + str(index))
                    directory.mkdir()
                    with self.assertRaisesRegex(RuntimeError, key.replace('__', ':')):
                        Server(directory, 'synthetic-invalid-driving-settings', {key: value})
                    self.assertFalse((directory / 'profiles').exists())


if __name__ == '__main__':
    unittest.main()
