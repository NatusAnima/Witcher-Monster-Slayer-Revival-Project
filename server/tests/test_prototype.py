"""Independent TCP/HTTP integration tests with synthetic identity bytes and temporary profiles.

These tests validate the implemented prototype contract, not an Android client's deserializers.
"""
import gzip
import collections
import concurrent.futures
import hashlib
import hmac
import http.server
import json
import math
import random
import re
import socket
import struct
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from dev import ROOT, DOTNET, DLL, environment

I = lambda value: struct.pack('>i', value)
Q = lambda value: struct.pack('>q', value)
S = lambda value: I(len(value.encode())) + value.encode()
THORSTEIN = 5124757777905877225
HORSE = 5124756197357912298
GRIFFIN = 5124757777905877227
MARKERS = ['SYNTHETIC_DEVICE_MARKER', 'SYNTHETIC_ACCOUNT_MARKER']
AUTH_API_VERSION = 25  # 1.1.116 ClientWorker.Run; connection/auth-layout-review/
BOMB_LOOKUP_FIXTURE = {
    'id': 401, 'slug': 'bomb_basic', 'priority': 0, 'delay': 0,
    'duration': 0, 'value': 0, 'radius': 0, 'explode_style': 0,
    'prefab_path': 'assets/_bundledassets/appearance/bomb/bomb_basic/prefab_bomb_basic.prefab',
}
GRIFFIN_MONSTER_FIXTURE = {
    'id': 9, 'family_id': 4, 'encounter_distance': 50, 'attack_animation_time': 2000,
    'rarity': 1, 'difficulty': 1, 'name': 'MONSTERS/BESTIARY/GRYPHON',
    'model': 'Assets/_bundledassets/characters/monsters/s00/gryphon/gryphon_lq/gryphon_lq.prefab',
    'image': 'Assets/_bundledassets/characters/monsters/s00/gryphon/gryphon_hq/gryphon_hq_presentation.prefab',
    'trophy': 'Assets/_bundledassets/ui/monster_trophies/trophy_gryphon.png', 'slug': 'gryphon',
}
# Inherited sample rows that the reconstruction (Reconstruction.cs) replaces; the historical digest
# checks restore them so they keep testing the unchanged remainder of the sample.
LEGACY_SKILLS = [
    {'id': 1, 'slug': 'fast_attack', 'cost': 1, 'required_level': 1},
    {'id': 2, 'slug': 'strong_attack', 'cost': 1, 'required_level': 1},
    {'id': 3, 'slug': 'parry', 'cost': 1, 'required_level': 2},
    {'id': 4, 'slug': 'muscle_memory', 'cost': 1, 'required_level': 3, 'parent_id': 1},
    {'id': 5, 'slug': 'strength_training', 'cost': 1, 'required_level': 3, 'parent_id': 2},
    {'id': 6, 'slug': 'hit_deflection', 'cost': 2, 'required_level': 4, 'parent_id': 3},
    {'id': 7, 'slug': 'precise_blows', 'cost': 2, 'required_level': 5, 'parent_id': 4},
    {'id': 8, 'slug': 'crushing_blows', 'cost': 2, 'required_level': 5, 'parent_id': 5},
]
LEGACY_SKILL_REQUIREMENTS = [
    {'skill_id': 4, 'required_skill_id': 1},
    {'skill_id': 5, 'required_skill_id': 2},
    {'skill_id': 6, 'required_skill_id': 3},
    {'skill_id': 7, 'required_skill_id': 4},
    {'skill_id': 8, 'required_skill_id': 5},
]
LEGACY_LEVEL_UPS = [
    {'id': 1, 'exp_threshold': 0, 'skill_points': 1},
    {'id': 2, 'exp_threshold': 100, 'skill_points': 1},
    {'id': 3, 'exp_threshold': 300, 'skill_points': 1},
    {'id': 4, 'exp_threshold': 600, 'skill_points': 1},
    {'id': 5, 'exp_threshold': 1000, 'skill_points': 1},
    {'id': 6, 'exp_threshold': 1500, 'skill_points': 1},
    {'id': 7, 'exp_threshold': 2100, 'skill_points': 1},
    {'id': 8, 'exp_threshold': 2800, 'skill_points': 1},
    {'id': 9, 'exp_threshold': 3600, 'skill_points': 1},
    {'id': 10, 'exp_threshold': 4500, 'skill_points': 1},
]
RECONSTRUCTED_EMPTY_BEFORE = ('effects', 'skill_to_effect', 'oils', 'oil_to_effect', 'potions', 'player_starting_skills', 'auto_equip',
                              'damage_types', 'bomb_damage_types', 'potion_to_effect', 'armor_to_effect', 'sword_to_effect',
                              'monster_vulnerabilities', 'herbs', 'lures', 'shop_lures', 'game_configuration',
                              'player_modifiers', 'player_modifier_to_effect',
                              # Alchemy and the shop (Economy.cs).
                              'ingredients', 'senses_potions', 'brewers', 'recipe_tiers', 'potion_recipes', 'oil_recipes',
                              'bomb_recipes', 'senses_potion_recipes', 'potion_recipe_ingredients', 'oil_recipe_ingredients',
                              'bomb_recipe_ingredients', 'senses_potion_recipe_ingredients', 'shop_bundles', 'shop_bundle_items',
                              'shop_bundles_layout_group_name_categories', 'auto_equip_items_prices',
                              # Oren packs priced in real money (Economy.OrenPacks).
                              'inapp_prices', 'inapp_price_shops', 'packs_types')
# Container arrays added after the inherited sample (always empty so far); the client needs the keys.
ADDED_CONTAINER_ARRAYS = ('shop_bundles_availability', 'shop_bundles_availability_data', 'daily_quest_contracts',
                          'daily_quest_rewards', 'event_rewards')
TUTORIAL_QUEST, TUTORIAL_NODES = 144, {228, 229, 230}
JOINT_VENTURE_QUEST, JOINT_VENTURE_NODES = 146, {287, 236, 9288, 9289, 9290, 9291, 9292}
# Season 1 story data as the server embeds it (server/story-1.1.116/season1_story.py).
# (A release validates with the copy packaged beside this file.)
SEASON1 = json.loads(next(path for path in (ROOT / 'WitcherRevival.Server/Story/season1-story.json',
                                            Path(__file__).resolve().parent / 'season1-story.json')
                          if path.exists()).read_text())
# World bestiary as the server embeds it (server/story-1.1.116/world_bestiary.py): every species the world spawns and
# the monster rows from id 101.
WORLD = json.loads(next(path for path in (ROOT / 'WitcherRevival.Server/Story/world-bestiary.json',
                                          Path(__file__).resolve().parent / 'world-bestiary.json')
                        if path.exists()).read_text())
RECONSTRUCTED_MONSTERS = {10, 11, 12, 13, 14, 15, 16} | {m['id'] for m in SEASON1['monsters']} | \
    {m['id'] for m in WORLD['monsters']}
# Devourer (tutorial exam); wraith, wraith_lvl2, gargoyle (A Joint Venture); endrega worker, warrior and drone (Good
# Money); the other season 1 story monsters.
RECONSTRUCTED_HORSE_OUTPUTS = {9, 10}  # dead_horse and 1ghoul_left of the horse node.
SEASON1_QUESTS = {q['id'] for q in SEASON1['quests']}
# Season 0 quest-log keys of the 1.1.116 Addressables catalog (assets/aa/catalog.json). JournalUI loads a
# quest's journal_log as given and waits for it; a key missing from the catalog blocks input for good.
JOURNAL_LOGS = {name: f'assets/_bundledassets/story/journal/s00/{path}.asset' for name, path in (
    ('tutorial', 'tutorial/log_tutorial'), ('prolog_01', 'prolog/log_prolog_01'), ('prolog_02', 'prolog/log_prolog_02'))}
GRIFFIN_DESCRIPTION_FIXTURES = [
    {'id': 25, 'monster_id': 9, 'level': 1, 'threshold': 1,
     'content': 'MONSTERS/DESCRIPTIONS/GRYPHON/INFO_1'},
    {'id': 26, 'monster_id': 9, 'level': 2, 'threshold': 5,
     'content': 'MONSTERS/DESCRIPTIONS/GRYPHON/INFO_2'},
    {'id': 27, 'monster_id': 9, 'level': 3, 'threshold': 10,
     'content': 'MONSTERS/DESCRIPTIONS/GRYPHON/INFO_3'},
]

def auth_body(device, account, api_version=AUTH_API_VERSION):
    # Opaque byte arrays, not strings. clientVersion is a synthetic fixture value.
    return I(1) + I(api_version) + Q(111600000) + I(len(device)) + device + I(len(account)) + account

def read_stage_events(log):
    return [(int(session), stage, int(expected), int(received), outcome)
            for session, stage, expected, received, outcome in re.findall(
                r'TCP read session=(\d+) stage=(magic|header|body) expected=(\d+) received=(\d+) outcome=(complete|eof)', log)]

class Reader:
    def __init__(self, data): self.data, self.pos = data, 0
    def take(self, size):
        result = self.data[self.pos:self.pos + size]
        if len(result) != size: raise ValueError('truncated fixture response')
        self.pos += size
        return result
    def byte(self): return self.take(1)[0]
    def integer(self): return struct.unpack('>i', self.take(4))[0]
    def long(self): return struct.unpack('>q', self.take(8))[0]
    def string(self): return self.take(self.integer()).decode()
    def ints(self): return [self.integer() for _ in range(self.integer())]
    def longs(self): return [self.long() for _ in range(self.integer())]
    def facts(self): return {self.integer(): self.integer() for _ in range(self.integer())}
    def weekly(self):
        # 1.1.116 Factory.Deserialize RVA 0x1e794a4: byte, date, reward, count, stamps.
        return {'success': self.byte(), 'last_stamp_date': self.integer(),
                'reward_id': self.integer(), 'stamps': self.ints()}
    def locations(self):
        locations = []
        for _ in range(self.integer()):
            locations.append((self.string(), self.take(8), self.ints()))
        return locations
    def nodes(self):
        nodes = []
        for _ in range(self.integer()):
            nodes.append({'instance': self.long(), 'node': self.integer(), 'place': self.string(),
                          'settings': self.string(), 'graph': self.string(), 'mode': self.integer()})
        return nodes
    def expiry(self): return {self.long(): self.integer() for _ in range(self.integer())}
    def quest(self):
        locations, nodes = self.locations(), self.nodes()
        if self.expiry(): raise ValueError('unexpected expiring nodes')
        return {'locations': locations, 'nodes': nodes}
    def end_graph(self):
        # Exact 1.1.116 Factory.Deserialize RVA 0x2481d74, not declaration order.
        result = {'success': self.byte() == 1}
        if result['success']:
            result.update(locations=self.locations(), nodes=self.nodes(),
                          exp=self.integer(), gold=self.integer())
            for name in ('potions', 'bombs', 'oils', 'lures', 'senses', 'bestiary', 'ingredients'):
                result[name] = self.facts()
            result.update(armors=self.ints(), swords=self.ints(), expiry=self.expiry())
        if self.pos != len(self.data): raise ValueError('unconsumed EndBehaviourGraph bytes')
        return result

def decode_batch(data):
    r, result = Reader(data), {}
    for _ in range(r.integer()):
        method, start = r.integer(), r.pos
        if method == 3:
            r.byte(); r.string(); r.take(14)
        elif method == 9:
            r.ints(); r.ints(); r.take(8)
        elif method == 5:
            for _ in range(9): r.facts()
            r.integer()
        elif method == 6:
            for _ in range(r.integer()): r.integer(); r.ints()
        elif method == 7: r.facts(); r.facts()
        elif method == 24: r.byte(); r.ints()
        elif method == 63: r.ints(); r.integer()
        elif method in (27, 117): r.take(5)
        elif method == 69:
            r.byte()
            for _ in range(r.integer()): r.take(24)   # Brewer: long instance, type, uses left, recipe, finish
        elif method in (79, 83): r.byte(); r.ints()
        elif method == 59: r.facts()
        elif method == 91: r.integer(); r.take(12 * r.integer())
        elif method == 70: r.integer(); r.ints(); r.integer(); r.ints()
        elif method == 60: r.quest()
        elif method == 20:
            r.take(13)
            for _ in range(r.integer()): r.integer(); r.ints()
        elif method == 94: r.weekly()
        elif method == 122:
            if r.byte() == 1:
                r.take(8)
                for _ in range(r.integer()): r.integer(); r.ints()
                r.ints(); r.integer()
        elif method == 43: r.byte(); r.longs()
        elif method == 56: r.longs()
        elif method == 112:
            for _ in range(r.integer()):
                r.take(24)
                for _ in range(r.integer()): r.take(13)
        else: raise ValueError(f'unrecognized batch fixture method {method}')
        result[method] = data[start:r.pos]
    if r.pos != len(data): raise ValueError('unconsumed initial batch bytes')
    return result

def decode_finished_quests(data):
    r = Reader(data)
    result = {'season': r.integer(), 'finished': r.ints(),
              'tracked': r.integer(), 'active': r.ints()}
    if r.pos != len(data): raise ValueError('unconsumed finished-quests bytes')
    return result

def previous_tracking_payload(data):
    # Only this four-byte fixture selection changed in RPC70; retain every other byte.
    if decode_finished_quests(data) != {'season': 0, 'finished': [], 'tracked': 145, 'active': [145]}:
        raise ValueError('unexpected quest-map bootstrap body')
    return data[:8] + I(-1) + data[12:]

def previous_player_name(data):
    # Before profiles per player, the unnamed player's placeholder name was the configured profile id; only that
    # string changed in GetPlayerInfo (3). Restore it for historical digest checks and refuse any other body.
    name = S('Unnamed')
    if data[:1] != b'\1' or data[1:1 + len(name)] != name:
        raise ValueError('unexpected player info body')
    return data[:1] + S('test-alpha') + data[1 + len(name):]

def previous_thorstein(data):
    # Before the hurt Thorstein, the prologue's first node used the standing season 1 figure; only that string
    # changed in the quest node lists (60). Restore it for historical digest checks.
    hurt, standing = (S('assets/_bundledassets/story/poi_settings/' + p) for p in
                      ('s00/prolog/thorstein_hurt_lq.asset', '_common/thorstein_lq.asset'))
    if data.count(hurt) > 1:
        raise ValueError('unexpected quest node list')
    return data.replace(hurt, standing)

def previous_batch(batch):
    parts = decode_batch(batch)
    if parts.pop(117) != b'\1' + I(0):
        raise ValueError('unexpected legacy Aura bootstrap timestamp')
    parts[3] = previous_player_name(parts[3])
    parts[60] = previous_thorstein(parts[60])
    return I(len(parts)) + b''.join(I(k) + v for k, v in parts.items())

def without_bomb_fixture(data):
    # Restore only the reviewed added row for historical sample digest checks.
    # Refuse other content so this helper cannot hide unreviewed bomb changes.
    if data.get('bombs') != [BOMB_LOOKUP_FIXTURE]:
        raise ValueError('unexpected structural bomb fixture')
    previous = dict(data)
    previous['bombs'] = []
    return previous

def without_griffin_combat_fixture(data):
    # Restore only the synthetic Griffin rows under test for canonical legacy-data digests.
    rows = data.get('monsters')
    descriptions = data.get('monster_descriptions')
    if not isinstance(rows, list) or rows.count(GRIFFIN_MONSTER_FIXTURE) != 1:
        raise ValueError('unexpected Griffin monster fixture')
    if not isinstance(descriptions, list) or any(descriptions.count(row) != 1 for row in GRIFFIN_DESCRIPTION_FIXTURES):
        raise ValueError('unexpected Griffin description fixtures')
    previous = dict(data)
    previous['monsters'] = [row for row in rows if row != GRIFFIN_MONSTER_FIXTURE]
    previous['monster_descriptions'] = [row for row in descriptions if row not in GRIFFIN_DESCRIPTION_FIXTURES]
    return previous

def without_reconstruction(data):
    # Restore the inherited sample for historical digest checks. Refuse missing reconstructed tables
    # so this helper cannot hide their removal; their content is tested separately.
    skills = data.get('skills')
    if not isinstance(skills, list) or [row['slug'] for row in skills if row['id'] <= 3] != ['fast_attack', 'strong_attack', 'parry']:
        raise ValueError('unexpected reconstructed skills')
    if any(not data.get(key) for key in RECONSTRUCTED_EMPTY_BEFORE):
        raise ValueError('missing reconstructed table')
    previous = dict(data)
    for key in ADDED_CONTAINER_ARRAYS: previous.pop(key)
    previous['difficulties'] = [{'id': n, 'slug': f'tier_{n}', 'player_attack_count': 3, 'enemy_attack_count': n}
                                for n in (1, 2, 3)]
    previous['swords'] = [row for row in data['swords'] if row['id'] <= 6]      # inherited rows 1-6 are unchanged
    previous['armors'] = [row for row in data['armors'] if row['id'] <= 6]
    previous['bombs'] = [BOMB_LOOKUP_FIXTURE] if any(row['id'] == 401 for row in data['bombs']) else []
    # Inherited monsters were named by their bestiary trivia term and had three description tiers.
    legacy = [dict(row, name=row['name'].replace('MONSTERS/NAMES/', 'MONSTERS/BESTIARY/'))
              for row in data['monsters'] if row['id'] not in RECONSTRUCTED_MONSTERS]
    # Restore the reviewed inherited rarity and difficulty fields for the historical digest. The current
    # world catalogue's native display tiers are tested separately, including the old Griffin discrepancy.
    inherited_difficulty = {1: 1, 2: 2, 3: 1, 4: 1, 5: 2, 6: 3, 7: 2, 8: 3, 9: 1}
    for row in legacy:
        if row['id'] == 6: row['rarity'] = 2
        row['difficulty'] = inherited_difficulty[row['id']]
    previous['monsters'] = legacy
    previous['monster_descriptions'] = [
        {'id': (row['id'] - 1) * 3 + tier, 'monster_id': row['id'], 'level': tier, 'threshold': threshold,
         'content': row['name'].replace('MONSTERS/BESTIARY/', 'MONSTERS/DESCRIPTIONS/') + f'/INFO_{tier}'}
        for row in legacy for tier, threshold in ((1, 1), (2, 5), (3, 10))]
    previous['skills'] = LEGACY_SKILLS
    previous['skill_requirements'] = LEGACY_SKILL_REQUIREMENTS
    previous['level_ups'] = LEGACY_LEVEL_UPS
    for key in RECONSTRUCTED_EMPTY_BEFORE:
        previous[key] = []
    tutorial_outputs = {row['id'] for row in data['quest_node_outputs']
                        if row['quest_node_id'] in TUTORIAL_NODES | JOINT_VENTURE_NODES}
    tutorial_outputs |= RECONSTRUCTED_HORSE_OUTPUTS
    season1_nodes = {row['id'] for row in data['quest_nodes'] if row['quest_id'] in SEASON1_QUESTS}
    tutorial_outputs |= {row['id'] for row in data['quest_node_outputs'] if row['quest_node_id'] in season1_nodes}
    previous['quests'] = [dict(row, journal_log='') if row['id'] == 145 else row for row in data['quests']
                          if row['id'] not in (TUTORIAL_QUEST, JOINT_VENTURE_QUEST) and row['id'] not in SEASON1_QUESTS]
    previous['quest_edges'] = [row for row in data['quest_edges'] if row['from_quest_id'] != TUTORIAL_QUEST]
    previous['quest_nodes'] = [row for row in data['quest_nodes']
                               if row['quest_id'] not in (TUTORIAL_QUEST, JOINT_VENTURE_QUEST) and row['quest_id'] not in SEASON1_QUESTS]
    previous['quest_node_outputs'] = [row for row in data['quest_node_outputs'] if row['id'] not in tutorial_outputs]
    previous['quest_node_edges'] = [row for row in data['quest_node_edges']
                                    if row['from_quest_node_output_id'] not in tutorial_outputs]
    return previous

def without_quest_map_fixture(data):
    previous = without_griffin_combat_fixture(without_bomb_fixture(without_reconstruction(data)))
    for key in ('quests', 'quest_nodes', 'quest_node_outputs', 'quest_node_edges'):
        previous[key] = []
    return previous

def identity_of(name):
    """The synthetic (device, account) identity of a test player."""
    return tuple(m if name == 'test-alpha' else f'{m}-{name}' for m in MARKERS)

def identity_key(directory, kind, identifier):
    key = bytes.fromhex((directory / 'profiles' / 'identity.key').read_text().strip())
    return hmac.new(key, kind + identifier.encode(), hashlib.sha256).hexdigest()

def profile_id(directory, identity):
    """The profile the server plays for an identity (ProfileRegistry): the account's when an account is sent, else
    the device's guest profile, looked up in players.json by their keyed identifiers."""
    index = json.loads((directory / 'profiles' / 'players.json').read_text())
    device, account = identity
    if account:
        return index['Accounts'][identity_key(directory, b'a', account)]['Profile']
    return index['Devices'][identity_key(directory, b'd', device)]['Profile']

def available_ports():
    # Reserve both together: releasing the first before choosing the second can return the same port.
    with socket.socket() as http, socket.socket() as tcp:
        http.bind(('127.0.0.1', 0))
        tcp.bind(('127.0.0.1', 0))
        return http.getsockname()[1], tcp.getsockname()[1]

class Server:
    def __init__(self, directory, profile, env_overrides=None):
        # Each test profile name stands for its own player and identity; the server names the profile after the
        # identity (ProfileRegistry), so the player keeps it across restarts.
        self.identity = identity_of(profile)
        self.http, self.tcp = available_ports()
        self.logpath = directory / (profile + '-' + str(self.http) + '.log')
        self.log = self.logpath.open('wb')
        server_env = environment()
        server_env.update(env_overrides or {})
        self.directory = directory
        self.process = subprocess.Popen([str(DOTNET), str(DLL), '--Http:Port', str(self.http), '--GameServer:Port', str(self.tcp),
            '--LocalProfile:DataDirectory', str(directory / 'profiles')],
            cwd=ROOT, env=server_env, stdout=self.log, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                self.log.close()
                raise RuntimeError('server failed to start: ' + self.logpath.read_text())
            try:
                if self.get('/health')['status'] == 'ready': return
            except (OSError, ValueError): time.sleep(.05)
        self.stop()
        raise RuntimeError('server startup timeout')
    def profile_id(self, identity=None):
        return profile_id(self.directory, identity or self.identity)
    def state(self, identity=None):
        return self.get('/prototype/state?profile=' + self.profile_id(identity))
    def get(self, path):
        with urllib.request.urlopen(f'http://127.0.0.1:{self.http}' + path, timeout=1) as response:
            data = response.read()
        return json.loads(data)
    def stop(self):
        if self.process.poll() is None:
            self.process.terminate()
            try: self.process.wait(timeout=5)
            except subprocess.TimeoutExpired: self.process.kill(); self.process.wait()
        self.log.close()

class Client:
    def __init__(self, server, auth=True, identity=None):
        self.sock = socket.create_connection(('127.0.0.1', server.tcp), timeout=2)
        # The client's request ids are random longs (RandomLong.Get); distinct clients never share one.
        self.sequence = random.getrandbits(40) << 8
        self.pushes = []
        if auth:
            device, account = identity or server.identity
            self.send(3, auth_body(device.encode(), account.encode()))
            assert self.receive() == (3, I(1) + b'\0')
    def close(self): self.sock.close()
    def send(self, channel, data):
        packet = bytes.fromhex('9043284a') + bytes([channel]) + I(len(data)) + data
        # Fragment headers as TCP is a byte stream, not a packet transport.
        self.sock.sendall(packet[:3]); self.sock.sendall(packet[3:])
    def read(self, count):
        result = bytearray()
        while len(result) < count:
            part = self.sock.recv(count - len(result))
            if not part: raise EOFError('session closed without a fabricated response')
            result.extend(part)
        return bytes(result)
    def receive(self):
        channel, length = struct.unpack('>Bi', self.read(5))
        return channel, self.read(length)
    def unanswered(self, method, data=b'', wait=.6):
        """Sends a request that must get no reply while the session stays open (no verified refusal body)."""
        self.sequence += 1
        self.send(1, b'\1\1' + I(0) + Q(self.sequence) + I(method) + data)
        self.sock.settimeout(wait)
        try:
            return self.sock.recv(1, socket.MSG_PEEK) == b'' and False
        except socket.timeout:
            return True
        finally:
            self.sock.settimeout(2)
    def rpc(self, method, data=b'', repeat=False):
        if not repeat: self.sequence += 1          # a repeat re-sends the last request id, as ClientWorker.HandleRetries does
        self.send(1, b'\1\1' + I(0) + Q(self.sequence) + I(method) + data)
        while True:
            channel, response = self.receive()
            r = Reader(response)
            assert channel == 1 and r.byte() == 1 and r.byte() == 2
            acked = r.longs()
            message, called = r.long(), r.integer()
            if not acked and message == 0:          # server push (no request acknowledged)
                self.pushes.append((called, r.take(len(response) - r.pos)))
                continue
            assert acked == [self.sequence]
            assert message == self.sequence and called == method
            return r.take(len(response) - r.pos)
    pushes = None

class TestPrototypeHelpers:
    @staticmethod
    def monster_placements(r):
        return [{'type': r.byte(), 'place': r.string(), 'spawn_ms': r.long(), 'ttl': r.integer(),
                 'monster': r.integer(), 'level': r.integer(), 'instance': r.long()} for _ in range(r.integer())]

class PrototypeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='twms-prototype-test-')
        self.directory = Path(self.temp.name)
        self.servers, self.clients = [], []
        self.server = self.start('test-alpha')
    def start(self, profile, env_overrides=None):
        server = Server(self.directory, profile, env_overrides); self.servers.append(server); return server
    def profile_file(self, name):
        return self.directory / 'profiles' / (profile_id(self.directory, identity_of(name)) + '.json')
    def client(self, server=None, auth=True, identity=None):
        client = Client(server or self.server, auth, identity); self.clients.append(client); return client
    def tearDown(self):
        for client in self.clients: client.close()
        for server in self.servers: server.stop()
        self.temp.cleanup()
    def test_thorstein_progress_batch_and_restart(self):
        c = self.client()
        q0 = c.rpc(60)
        self.assertEqual(Reader(q0).quest()['nodes'][0]['instance'], THORSTEIN)
        batch = decode_batch(c.rpc(115))
        self.assertEqual(len(batch), 21)
        self.assertEqual(batch[60], q0)
        self.assertEqual(Reader(batch[59]).facts(), {2: 1})
        # In-progress graph branch: not a completed tutorial.
        self.assertEqual(c.rpc(78, I(2) + I(10145) + I(8)), b'\1')
        self.assertEqual(Reader(c.rpc(60)).quest()['nodes'][0]['instance'], THORSTEIN)
        completion = {10145: 1, 95: 1, 107: 1, 77: 2, 123: 0, 113: 1}
        payload = Q(THORSTEIN) + S('thorstein') + I(len(completion)) + b''.join(I(k) + I(v) for k, v in completion.items())
        response = Reader(c.rpc(57, payload)).end_graph()
        self.assertTrue(response['success'])
        self.assertEqual(response['nodes'][0]['instance'], HORSE)
        self.assert_zero_completion_rewards(response)
        expected = {2: 1, **completion}
        self.assertEqual(Reader(c.rpc(58)).facts(), expected)
        self.assertEqual(Reader(c.rpc(59)).facts(), expected)
        q1 = c.rpc(60)
        quest = Reader(q1).quest()
        self.assertEqual(quest['nodes'][0]['instance'], HORSE)
        self.assertEqual(response['locations'], quest['locations'])
        self.assertEqual(response['nodes'], quest['nodes'])
        batch = decode_batch(c.rpc(115))
        self.assertEqual(batch[60], q1)
        self.assertEqual(Reader(batch[59]).facts(), expected)
        self.server.stop()
        restarted = self.start('test-alpha')
        c2 = self.client(restarted)
        self.assertEqual(Reader(c2.rpc(59)).facts(), expected)
        self.assertEqual(c2.rpc(60), q1)
        self.assertEqual(restarted.state()['revision'], 2)

    def test_configured_poznan_quest_location_is_consistent_across_responses(self):
        # Test-only coordinates for the Old Market probe. The server does not read
        # device GPS; systemd's per-unit environment uses the same .NET config keys.
        server = self.start('test-poznan-location', {
            'Tutorial__Latitude': '52.4082',
            'Tutorial__Longitude': '16.9340',
        })
        client = self.client(server)
        quest_bytes = client.rpc(60)
        quest = Reader(quest_bytes).quest()
        location, = quest['locations']
        latitude, longitude = struct.unpack('>ff', location[1])
        self.assertEqual(location[0], 'tut_thorstein')
        self.assertAlmostEqual(latitude, 52.4082, places=5)
        self.assertAlmostEqual(longitude, 16.9340, places=5)
        batch = decode_batch(client.rpc(115))
        self.assertEqual(batch[60], quest_bytes)

        completion = self.completion_body({901: 1}, output='2ghouls_left')
        response = Reader(client.rpc(57, completion)).end_graph()
        self.assertEqual(response['locations'], quest['locations'])
        self.assertEqual(Reader(client.rpc(60)).quest()['locations'], quest['locations'])
    def test_post_alghul_output_advances_to_griffin_and_survives_restart(self):
        c = self.client()
        body = self.completion_body({901: 5, 902: -3}, instance=9876543210, output='2ghouls_left')
        response = Reader(c.rpc(57, body)).end_graph()
        self.assertTrue(response['success'])
        node, = response['nodes']
        self.assertEqual((node['instance'], node['node'], node['place']), (GRIFFIN, 3, 'tut_thorstein'))
        self.assertEqual(node['settings'], 'assets/_bundledassets/story/poi_settings/s00/prolog/gryphon_lq.asset')
        self.assertEqual(node['graph'], 's00/prolog/prolog_01_griffin')
        self.assertEqual(self.server.state()['questStage'], 'griffin')
        active = c.rpc(60)
        self.assertEqual(Reader(active).quest()['nodes'], response['nodes'])
        self.assertEqual(decode_batch(c.rpc(115))[60], active)

        # A stale replayed Thorstein save may merge facts but cannot roll the stage back.
        replay = self.completion_body({903: 1}, instance=THORSTEIN, output='thorstein')
        replay_response = Reader(c.rpc(57, replay)).end_graph()
        self.assertEqual(replay_response['nodes'], response['nodes'])
        self.assertEqual(self.server.state()['questStage'], 'griffin')

        self.server.stop()
        restarted = self.start('test-alpha')
        c2 = self.client(restarted)
        self.assertEqual(c2.rpc(60), active)
        self.assertEqual(restarted.state()['questStage'], 'griffin')

    def test_legacy_profile_without_quest_stage_keeps_fact_based_successor(self):
        legacy = self.start('test-legacy')
        self.client(legacy).close()                                         # the player gets a profile id
        legacy.stop()
        path = self.profile_file('test-legacy')
        path.write_text(json.dumps({'SchemaVersion': 1, 'ProfileId': path.stem, 'Revision': 1,
                                    'Facts': {'2': 1, '10145': 1}}))
        legacy = self.start('test-legacy')
        node, = Reader(self.client(legacy).rpc(60)).quest()['nodes']
        self.assertEqual(node['instance'], HORSE)
        self.assertIsNone(legacy.state()['questStage'])
    RECONSTRUCTED = {'LocalProfile__NewProfileMode': 'reconstructed'}
    TUT_GHOUL, TUT_WITCHER, TUT_EXAM = 512475750302797027, 1271842437439635223, 1152921521786716389

    def reconstructed(self, profile='test-fresh'):
        server = self.start(profile, self.RECONSTRUCTED)
        return server, self.client(server)

    def player_info(self, c):
        r = Reader(c.rpc(3))
        return {'success': r.byte(), 'name': r.string(), 'gold': r.integer(), 'exp': r.integer(),
                'head': r.integer(), 'tutorial_finished': r.byte(), 'gender': r.byte()}

    def inventory(self, c):
        r = Reader(c.rpc(5))
        maps = [r.facts() for _ in range(9)]
        return {'ingredients': maps[0], 'bombs': maps[1], 'potions': maps[2], 'oils': maps[3], 'lures': maps[4],
                'senses': maps[5], 'scrolls': maps[8], 'bag': r.integer()}

    def test_reconstructed_profile_starts_at_level_one_in_the_tutorial(self):
        server, c = self.reconstructed()
        self.assertEqual({k: v for k, v in self.player_info(c).items() if k in ('gold', 'exp', 'tutorial_finished')},
                         {'gold': 0, 'exp': 0, 'tutorial_finished': 0})
        batch = decode_batch(c.rpc(115))
        skills = Reader(batch[63]); owned, points = skills.ints(), skills.integer()
        with urllib.request.urlopen(f'http://127.0.0.1:{server.http}/staticdata', timeout=1) as response:
            data = json.loads(gzip.decompress(response.read()))
        self.assertEqual(sorted(owned), sorted(row['id'] for row in data['player_starting_skills']))
        self.assertEqual(points, 0)
        self.assertEqual(decode_finished_quests(batch[70])['tracked'], 144)
        node, = Reader(c.rpc(60)).quest()['nodes']
        self.assertEqual((node['instance'], node['node'], node['graph']), (self.TUT_GHOUL, 228, 's00/tutorial/tut_ghoul'))
        self.assertEqual(node['settings'], 'assets/_bundledassets/story/poi_settings/s00/tutorial/ghoul_lq.asset')
        self.assertEqual(Reader(batch[59]).facts(), {})
        self.assertEqual(Reader(batch[7]).facts(), {})
        self.assertEqual(self.inventory(c)['oils'], {})

    def test_reconstructed_tutorial_exam_and_thorstein_rewards_are_granted_once(self):
        server, c = self.reconstructed()
        # tut_ghoul's won fight sets fact 91 before "tutorial_end": the ghoul joins the bestiary, once.
        step = Reader(c.rpc(57, self.completion_body({10144: 3, 91: 1}, instance=self.TUT_GHOUL, output='tutorial_end'))).end_graph()
        self.assertEqual(step['nodes'][0]['instance'], self.TUT_WITCHER)
        self.assertEqual(step['bestiary'], {1: 1})
        self.assert_zero_completion_rewards(step | {'bestiary': {}})
        again = Reader(c.rpc(57, self.completion_body({}, instance=self.TUT_GHOUL, output='tutorial_end'))).end_graph()
        self.assert_zero_completion_rewards(again)
        exam = Reader(c.rpc(57, self.completion_body({10144: 2}, instance=self.TUT_WITCHER, output='exam'))).end_graph()
        self.assertEqual(exam['nodes'][0]['graph'], 's00/tutorial/tut_gravehag')
        self.assertEqual((exam['oils'], exam['bombs'], exam['potions']), ({301: 1}, {402: 2}, {205: 1}))
        replay = Reader(c.rpc(57, self.completion_body({}, instance=self.TUT_WITCHER, output='exam'))).end_graph()
        self.assert_zero_completion_rewards(replay)
        self.assertEqual(self.inventory(c)['oils'], {301: 1})
        done = Reader(c.rpc(57, self.completion_body({3: 1, 2: 1}, instance=self.TUT_EXAM, output='exam_end'))).end_graph()
        self.assertEqual((done['exp'], done['gold']), (0, 0))      # the maintainer's reward list: the exam pays nothing
        self.assertEqual(done['nodes'][0]['instance'], THORSTEIN)
        # Thorstein lies hurt on the map until his first dialog (the standing figure is season 1's).
        self.assertEqual(done['nodes'][0]['settings'], 'assets/_bundledassets/story/poi_settings/s00/prolog/thorstein_hurt_lq.asset')
        info = self.player_info(c)
        self.assertEqual((info['exp'], info['gold'], info['tutorial_finished']), (0, 0, 1))
        self.assertEqual(decode_finished_quests(decode_batch(c.rpc(115))[70])['tracked'], 145)
        accepted = Reader(c.rpc(57, self.completion_body())).end_graph()
        self.assertEqual(accepted['oils'], {})          # prolog_01 gives nothing.
        self.assertEqual(accepted['nodes'][0]['instance'], HORSE)
        self.assertEqual(self.inventory(c)['oils'], {301: 1})
        # Still level 1, so no skill points yet.
        self.assertEqual(server.state()['player']['skillPoints'], 0)
        # Winning both horse fights ends with "dead_horse", which also leads to the griffin; Thorstein's
        # dialog after the fights hands over the Hybrid Oil once, whichever ending is replayed.
        horse = Reader(c.rpc(57, self.completion_body({94: -3}, instance=HORSE, output='dead_horse'))).end_graph()
        self.assertEqual(horse['nodes'][0]['instance'], GRIFFIN)
        self.assertEqual(horse['oils'], {306: 1})
        self.assertEqual(horse['bestiary'], {2: 2})     # fact 94 = -3: both alghouls fell
        self.assertEqual(server.state()['questStage'], 'griffin')
        replay = Reader(c.rpc(57, self.completion_body({}, instance=HORSE, output='2ghouls_left'))).end_graph()
        self.assertEqual((replay['oils'], replay['bestiary']), ({}, {}))
        # GetKilledMonsters: the tutorial ghoul, the exam's devourer and the two alghouls.
        self.assertEqual(Reader(c.rpc(7)).facts(), {1: 1, 10: 1, 2: 2})
        self.assertEqual(self.inventory(c)['oils'], {301: 1, 306: 1})

    def test_story_fights_kept_in_facts_count_once_per_result(self):
        # prolog_01_dead_horse: fact 94 = 1 means the first alghoul fell and the second fight was lost.
        server, c = self.reconstructed()
        lost = Reader(c.rpc(57, self.completion_body({94: 1}, instance=HORSE, output='1ghoul_left'))).end_graph()
        self.assertEqual((lost['oils'], lost['bestiary']), ({306: 1}, {2: 1}))
        self.assertEqual(Reader(c.rpc(7)).facts(), {2: 1})
        # A profile that won the tutorial ghoul before it was counted: fact 91 alone puts it in the bestiary.
        self.assertEqual(c.rpc(78, I(1) + I(91) + I(1)), b"\1")
        self.assertEqual(Reader(c.rpc(7)).facts(), {1: 1, 2: 1})

    def test_reconstructed_oils_are_consumed_only_when_owned(self):
        server, c = self.reconstructed()
        for instance, output in ((self.TUT_GHOUL, 'exam'),):
            c.rpc(57, self.completion_body({}, instance=instance, output=output))
        self.assertEqual(c.rpc(89, I(306) + I(0)), b'\0')      # Hybrid oil not owned yet.
        self.assertEqual(c.rpc(89, I(301) + I(1) + I(205)), b'\1')  # Exam oil and Swallow.
        self.assertEqual(self.inventory(c)['oils'], {})
        self.assertEqual(self.inventory(c)['potions'], {})
        self.assertEqual(c.rpc(89, I(301) + I(0)), b'\0')
        self.assertEqual(c.rpc(89, I(-1) + I(0)), b'\1')      # Empty loadout.

    def test_reconstructed_character_creation_and_bomb_throws(self):
        server, c = self.reconstructed()
        self.assertEqual(c.rpc(29, S('Geralt')), b'\1' + I(0))
        self.assertEqual(c.rpc(46, b'\1'), b'\1' + I(1))
        info = self.player_info(c)
        self.assertEqual((info['name'], info['gender']), ('Geralt', 1))
        self.assertEqual(c.rpc(29, S('')), b'\0' + I(0))
        c.rpc(57, self.completion_body({}, instance=self.TUT_WITCHER, output='exam'))
        self.assertEqual(c.rpc(39, I(402)), b'\1' + I(1))
        self.assertEqual(c.rpc(39, I(402)), b'\1' + I(0))
        self.assertEqual(c.rpc(39, I(401)), b'\1' + I(0))   # Graph-supplied bombs are not owned.
        self.assertEqual(self.inventory(c)['bombs'], {})

    @staticmethod
    def summoned_groups(r):
        groups = []
        for _ in range(r.integer()):
            group = {'type': r.integer(), 'item': r.integer(), 'start': r.integer(), 'despawn': r.integer(),
                     'lon': r.integer(), 'lat': r.integer()}
            group['monsters'] = [(r.integer(), r.long(), r.byte()) for _ in range(r.integer())]
            groups.append(group)
        return groups

    @staticmethod
    def combat_end(r):
        loot = r.ints()
        keys = ('base', 'combo', 'oil', 'time', 'parry', 'first', 'boosted', 'pack')
        result = dict(zip(keys, (r.integer() for _ in keys)), loot=loot)
        assert r.pos == len(r.data)
        return result

    def test_reconstructed_tutorial_summon_fights_and_bestiary(self):
        server, c = self.reconstructed()
        lon, lat = 16925168, 52406374  # Fictional marker values; must never reach the log.
        self.assertEqual(c.rpc(111, I(16) + I(2) + I(lon) + I(lat)), b'\0' + I(0))   # Scroll not owned.
        r = Reader(c.rpc(111, I(16) + I(1) + I(lon) + I(lat)))
        self.assertEqual(r.byte(), 1)
        group, = self.summoned_groups(r)
        self.assertEqual(r.pos, len(r.data))
        self.assertEqual((group['type'], group['item'], group['lon'], group['lat']), (16, 1, lon, lat))
        self.assertEqual(group['despawn'] - group['start'], 3601)
        self.assertLess(group['start'], time.time())
        self.assertEqual([(m, alive) for m, _, alive in group['monsters']], [(1, 1), (3, 1), (4, 1)])
        with urllib.request.urlopen(f'http://127.0.0.1:{server.http}/staticdata', timeout=1) as response:
            monsters = {row['id']: row for row in json.loads(gzip.decompress(response.read()))['monsters']}
        self.assertEqual([monsters[m]['difficulty'] for m, _, _ in group['monsters']], [1, 1, 1])
        # A repeated tutorial summon returns the same group; 112 lists it without a Result byte.
        again = Reader(c.rpc(111, I(16) + I(1) + I(lon) + I(lat))); again.byte()
        self.assertEqual(self.summoned_groups(again), [group])
        self.assertEqual(self.summoned_groups(Reader(c.rpc(112))), [group])
        ghoul, drowner = group['monsters'][0][1], group['monsters'][1][1]
        details = [0] * 13
        # PerfectAttacks (proper finishers, the client's critical hits), UsedProperOil, PerfectParries. The client never
        # increments CriticalHits (Details[9]), so it pays nothing.
        details[1], details[10], details[11], details[9] = 2, 1, 3, 5
        body = lambda win, surrendered=False: bytes([win]) + I(13) + b''.join(I(v) for v in details) + bytes([surrendered])
        self.assertEqual(c.rpc(113, Q(12345)), b'\0')
        self.assertEqual(c.rpc(113, Q(drowner)), b'\1')
        lost = self.combat_end(Reader(c.rpc(114, body(False))))
        self.assertEqual(sum(v for k, v in lost.items() if k != 'loot'), 0)
        self.assertEqual(c.rpc(113, Q(ghoul)), b'\1')
        won = self.combat_end(Reader(c.rpc(114, body(True))))
        self.assertEqual(won, {'base': 100, 'combo': 30, 'oil': 50, 'time': 0, 'parry': 45, 'first': 100,
                               'boosted': 0, 'pack': 0, 'loot': [103, 103, 104]})   # tissue ×2, necrophage remains
        self.assertEqual(self.player_info(c)['exp'], 325)
        self.assertEqual(c.rpc(113, Q(ghoul)), b'\0')    # Defeated monsters cannot be fought again.
        listed, = self.summoned_groups(Reader(c.rpc(112)))
        self.assertEqual([alive for _, _, alive in listed['monsters']], [0, 1, 1])
        self.assertEqual(Reader(c.rpc(7)).facts(), {1: 1})
        # No encounter: nothing is granted.
        self.assertEqual(sum(v for k, v in self.combat_end(Reader(c.rpc(114, body(True)))).items() if k != 'loot'), 0)
        self.assertEqual(c.rpc(117), b'\1' + I(0))   # The summoning skill was never used.
        self.assertEqual(decode_batch(c.rpc(115))[112], c.rpc(112))
        server.stop()
        text = server.logpath.read_text()
        self.assertNotIn(str(lon), text)
        self.assertNotIn(str(lat), text)
        # After a restart the saved group comes back with its point, in the batch and standalone,
        # and its living monsters can still be fought.
        restarted = self.start('test-fresh', self.RECONSTRUCTED)
        c = self.client(restarted)
        self.assertEqual(self.summoned_groups(Reader(decode_batch(c.rpc(115))[112])), [listed])
        self.assertEqual(c.rpc(113, Q(ghoul)), b'\0')
        self.assertEqual(c.rpc(113, Q(drowner)), b'\1')
        exp = self.player_info(c)['exp']
        first = c.rpc(114, body(True))
        # The client re-sends an unanswered request with the same id: the repeat gets the same answer, settled once.
        self.assertEqual(c.rpc(114, body(True), repeat=True), first)
        granted = self.combat_end(Reader(first))
        self.assertEqual(granted['first'], 100)
        self.assertEqual(self.player_info(c)['exp'], exp + sum(v for k, v in granted.items() if k not in ('loot', 'pack')))
        again = Reader(c.rpc(111, I(16) + I(1) + I(lon) + I(lat))); again.byte()
        restored, = self.summoned_groups(again)
        self.assertEqual((restored['start'], restored['lon'], [m[1] for m in restored['monsters']]),
                         (group['start'], lon, [m[1] for m in group['monsters']]))
        self.assertEqual([alive for _, _, alive in restored['monsters']], [0, 0, 1])
        self.assertEqual(Reader(c.rpc(7)).facts(), {1: 1, 3: 1})

    def playable_service(self, respond):
        """A fake playable-locations service; respond(ids, epoch) gives the JSON body."""
        requests = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                ids, epoch = query['ids'][0].split(','), int(query['epoch'][0])
                requests.append(ids)
                body = json.dumps(respond(ids, epoch)).encode()
                self.send_response(200); self.send_header('Content-Length', str(len(body))); self.end_headers()
                self.wfile.write(body)
            def log_message(self, *args): pass

        fake = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=fake.serve_forever, daemon=True).start()
        self.addCleanup(fake.server_close)
        self.addCleanup(fake.shutdown)
        return f'http://127.0.0.1:{fake.server_port}', requests

    def test_get_weather_answers_the_real_weather_of_a_coarse_cell(self):
        # GetWeather (67): [float lat][float lng] -> [int WeatherCode] (OpenWeatherMap groups). The server asks the
        # weather service with the position rounded to 0.1 degrees, caches the cell, and never logs positions.
        asked, codes = [], {'rain': 61}
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                asked.append((query['latitude'][0], query['longitude'][0], query['current'][0]))
                body = json.dumps({'current': {'weather_code': codes['rain']}}).encode()
                self.send_response(200); self.send_header('Content-Length', str(len(body))); self.end_headers()
                self.wfile.write(body)
            def log_message(self, *args): pass
        fake = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=fake.serve_forever, daemon=True).start()
        self.addCleanup(fake.server_close); self.addCleanup(fake.shutdown)
        server = self.start('test-weather', dict(self.RECONSTRUCTED, Weather__Url=f'http://127.0.0.1:{fake.server_port}/v1/forecast'))
        c = self.client(server)
        lat, lng = 12.3456, 45.6789
        self.assertEqual(c.rpc(67, struct.pack('>ff', lat, lng)), I(3))            # WMO 61 (rain) -> Rain
        self.assertEqual(asked, [('12.3', '45.7', 'weather_code')])
        codes['rain'] = 95
        self.assertEqual(c.rpc(67, struct.pack('>ff', lat - 0.02, lng)), I(3))    # same cell, cached
        self.assertEqual(len(asked), 1)
        self.assertEqual(c.rpc(67, struct.pack('>ff', 50.0, 19.9)), I(1))         # another cell: thunderstorm
        self.assertEqual(c.rpc(67), I(6))                                          # no position: Clear
        server.stop()
        text = server.logpath.read_text()
        for value in ('12.3', '45.7', '12.34', '45.67', '50.0', '19.9'):
            self.assertNotIn(value, text)
        # Without a weather source every answer is Clear.
        plain = self.client()
        self.assertEqual(plain.rpc(67, struct.pack('>ff', lat, lng)), I(6))

    def test_reconstructed_story_nodes_move_to_safe_places_around_the_loaded_cells(self):
        # Fictional origin; the fake playable-locations service offers one place per distance.
        origin = (10.0, 20.0)
        offsets = {'near': 100, 'griffin': 400, 'horse': 800, 'far': 2000}   # metres north of the origin
        places = [{'id': f'lab-test-{name}', 'lat': origin[0] + metres / 110540.0, 'lng': origin[1],
                   'biomes': [4], 'kind': 'path'} for name, metres in offsets.items()]
        url, requests = self.playable_service(lambda ids, epoch: {
            i: {'center': list(origin), 'places': places if n == 0 else []} for n, i in enumerate(ids)})
        env = dict(self.RECONSTRUCTED, Playable__Url=url)
        server = self.start('test-story', env)
        c = self.client(server)
        c.rpc(57, self.completion_body({3: 1}, instance=self.TUT_EXAM, output='exam_end'))
        c.rpc(57, self.completion_body())                                   # Thorstein: horse stage
        horse, = Reader(c.rpc(60)).quest()['nodes']
        self.assertEqual((horse['place'], horse['mode']), ('tut_thorstein', 2))   # No area loaded yet.
        cells = [0x4704440000000000 + (k << 40) for k in range(9)]
        self.assertEqual(c.rpc(88, I(9) + b''.join(Q(cell) for cell in cells)), b'\1')
        quest = Reader(c.rpc(60)).quest()
        horse, = quest['nodes']
        self.assertEqual((horse['place'], horse['mode']), ('lab-story-dead_horse', 1))
        place, = [loc for loc in quest['locations'] if loc[0] == 'lab-story-dead_horse']
        lat, lng = struct.unpack('>ff', place[1])
        self.assertAlmostEqual(lat, places[2]['lat'], places=4)
        self.assertEqual(place[2], [4])
        self.assertEqual(sorted(map(int, requests[0])), cells)
        griffin = Reader(c.rpc(57, self.completion_body({94: -3}, instance=HORSE, output='dead_horse'))).end_graph()
        self.assertEqual((griffin['nodes'][0]['place'], griffin['nodes'][0]['mode']), ('lab-story-griffin', 4))
        place, = [loc for loc in griffin['locations'] if loc[0] == 'lab-story-griffin']
        self.assertAlmostEqual(struct.unpack('>ff', place[1])[0], places[1]['lat'], places=4)
        # The chosen place is kept across restarts, before any cells are loaded again.
        server.stop()
        self.assertNotIn(f"{places[1]['lat']:.4f}", server.logpath.read_text())
        c = self.client(self.start('test-story', env))
        again, = Reader(c.rpc(60)).quest()['nodes']
        self.assertEqual((again['place'], again['mode']), ('lab-story-griffin', 4))
        # Beating the griffin closes the prologue (reward once) and offers quest node 287, whose graph the
        # client queued; it starts "A Joint Venture" and is followed by no node yet.
        done = Reader(c.rpc(57, self.completion_body({109: 1}, instance=GRIFFIN, output='griffin_1'))).end_graph()
        self.assertEqual((done['exp'], done['gold']), (250, 45))
        quests = decode_finished_quests(decode_batch(c.rpc(115))[70])
        self.assertEqual((quests['finished'], quests['tracked'], quests['active']), ([144, 145], 146, [146]))
        start, = done['nodes']
        self.assertEqual((start['node'], start['graph'], start['mode']), (287, 's00/prolog/prolog_02_map', 2))
        replay = Reader(c.rpc(57, self.completion_body({109: 2}, instance=GRIFFIN, output='griffin_2'))).end_graph()
        self.assertEqual((replay['exp'], [n['node'] for n in replay['nodes']]), (0, [287]))
        after = Reader(c.rpc(57, self.completion_body({10146: 1}, instance=start['instance'], output='empty'))).end_graph()
        self.assertEqual(after['nodes'], [])
        self.assertEqual(Reader(c.rpc(60)).quest()['nodes'], [])
        self.assertEqual(decode_finished_quests(decode_batch(c.rpc(115))[70])['tracked'], 146)

    def test_joint_venture_runs_from_the_map_to_the_figurine(self):
        # Fictional origin; the fake service offers places on four bearings at four distances.
        origin = (10.0, 20.0)
        metres = lambda a, b: math.hypot((a[0] - b[0]) * 110540.0, (a[1] - b[1]) * 111320.0 * math.cos(math.radians(a[0])))
        places = [{'id': f'lab-test-{r}-{k}', 'lat': origin[0] + dy * r / 110540.0,
                   'lng': origin[1] + dx * r / (111320.0 * math.cos(math.radians(origin[0]))), 'biomes': [4], 'kind': 'path'}
                  for r in (200, 350, 500, 650) for k, (dy, dx) in enumerate(((1, 0), (0, 1), (-1, 0), (0, -1)))]
        url, _ = self.playable_service(lambda ids, epoch: {
            i: {'center': list(origin), 'places': places if n == 0 else []} for n, i in enumerate(ids)})
        env = dict(self.RECONSTRUCTED, Playable__Url=url)
        server = self.start('test-venture', env)
        c = self.client(server)
        cells = [0x4704440000000000 + (k << 40) for k in range(9)]
        c.rpc(88, I(9) + b''.join(Q(cell) for cell in cells))
        c.rpc(57, self.completion_body({3: 1}, instance=self.TUT_EXAM, output='exam_end'))
        c.rpc(57, self.completion_body())
        c.rpc(57, self.completion_body({94: -3}, instance=HORSE, output='dead_horse'))
        c.rpc(57, self.completion_body({109: 2, 107: 2}, instance=GRIFFIN, output='griffin_1'))
        start = Reader(c.rpc(57, self.completion_body({10146: 1}, instance=5124758224582476011, output='empty'))).end_graph()
        self.assertEqual(start['nodes'], [])

        def step(output, facts=None, instance=0):
            result = Reader(c.rpc(57, self.completion_body(facts or {}, instance=instance, output=output))).end_graph()
            points = {name: struct.unpack('>ff', raw) for name, raw, _ in result['locations']}
            return result, {n['node']: points[n['place']] for n in result['nodes']}

        def keys(result):
            return [(n['node'], n['instance'], n['settings'].rsplit('/', 1)[-1], n['graph'], n['mode']) for n in result['nodes']]

        # The journal's "Examine" button (quest node 236) ends Thorstein's map dialog with "map": the obelisk.
        result, at = step('map', {107: 3, 10146: 2}, instance=5124758224582476012)
        self.assertEqual(keys(result), [(9288, 5124758224582476016, 'elven_obelisk.asset', 's00/prolog/prolog_02_obelisk', 1)])
        self.assertEqual((result['exp'], result['gold']), (0, 0))
        obelisk = at[9288]
        self.assertTrue(300 <= metres(obelisk, origin) <= 800)
        quests = decode_finished_quests(decode_batch(c.rpc(115))[70])
        self.assertEqual((quests['finished'], quests['tracked'], quests['active']), ([144, 145], 146, [146]))
        # The rune puzzle opens the three gifts, each on its own spot; the gargoyle waits for a gift.
        result, at = step('obelisk', {97: 1, 98: 1, 99: 1, 107: 4}, instance=5124758224582476016)
        self.assertEqual([k[:4] for k in keys(result)], [
            (9289, 5124758224582476014, 'stone_crown.asset', 's00/prolog/prolog_02_crown'),
            (9290, 5124758224582476015, 'stone_sword.asset', 's00/prolog/prolog_02_sword'),
            (9291, 5124758224582476013, 'stone_heart.asset', 's00/prolog/prolog_02_heart')])
        gifts = dict(at)
        for node, point in gifts.items():
            self.assertTrue(150 <= metres(point, origin) <= 600)
            self.assertGreaterEqual(metres(point, obelisk), 100)
            for other, elsewhere in gifts.items():
                if other != node: self.assertGreaterEqual(metres(point, elsewhere), 100)
        # A lost wraith fight keeps the crown for another try; the sword visit brings out the gargoyle.
        result, at = step('crown_fail', {97: 2}, instance=5124758224582476014)
        self.assertEqual(([n['node'] for n in result['nodes']], result['exp']), ([9289, 9290, 9291], 0))
        result, at = step('sword', {98: 0}, instance=5124758224582476015)
        self.assertEqual([n['node'] for n in result['nodes']], [9289, 9291, 9292])
        self.assertLessEqual(metres(at[9292], obelisk), 200)
        self.assertEqual({node: at[node] for node in (9289, 9291)}, {node: gifts[node] for node in (9289, 9291)})
        # The heart's wraith gives experience once; a wrong gift's wraith too; the gargoyle king more.
        result, _ = step('heart', {99: 3, 100: 1}, instance=5124758224582476013)
        self.assertEqual(([n['node'] for n in result['nodes']], result['exp']), ([9289, 9292], 250))
        self.assertEqual(result['bestiary'], {11: 1})                       # the heart's wraith joins the bestiary
        self.assertEqual([step('heart_again', instance=5124758224582476013)[0][k] for k in ('exp', 'bestiary')], [0, {}])
        self.assertEqual(step('wraith_won', instance=5124756678394249457)[0]['exp'], 250)
        result, _ = step('gargoyle', {100: 3, 112: 3}, instance=5124756678394249457)
        self.assertEqual(([n['node'] for n in result['nodes']], result['exp'], result['bestiary']), ([9289, 9292], 600, {13: 1}))
        # Story fights count in the bestiary: the griffin, two wraiths (heart, wrong gift) and the gargoyle.
        killed = Reader(decode_batch(c.rpc(115))[7]).facts()
        self.assertEqual({m: killed.get(m) for m in (9, 11, 13)}, {9: 1, 11: 2, 13: 1})
        # The figurine cutscene and Thorstein's dialog end the quest: 275 XP, no node left.
        result, _ = step('success_heart', {100: 4, 102: 3, 145: 2}, instance=5124756678394249457)
        self.assertEqual((result['nodes'], result['exp'], result['gold']), ([], 275, 0))
        quests = decode_finished_quests(decode_batch(c.rpc(115))[70])
        self.assertEqual((quests['finished'], quests['tracked'], quests['active']), ([144, 145, 146], -1, []))
        self.assertEqual(step('success', instance=5124756678394249457)[0]['exp'], 0)
        server.stop()
        c = self.client(self.start('test-venture', env))
        self.assertEqual(Reader(c.rpc(60)).quest()['nodes'], [])
        self.assertEqual(Reader(c.rpc(59)).facts()[100], 4)

    def test_prepare_to_combat_consumes_the_selected_owned_items(self):
        # PrepareToCombat (10): [int n][bomb…][int n][potion…][int oil]; response [byte Success].
        c = self.client(self.start('test-prepare', self.RECONSTRUCTED))
        self.assertEqual(c.rpc(10, I(0) + I(0) + I(-1)), b'\1')
        c.rpc(57, self.completion_body(instance=self.TUT_WITCHER, output='exam'))   # oil 301, bombs 402 ×2, potion 205
        self.assertEqual(c.rpc(10, I(1) + I(402) + I(1) + I(205) + I(301)), b'\1')
        self.assertEqual(c.rpc(10, I(0) + I(0) + I(301)), b'\0')                  # the oil is used up
        # A selected bomb stays in the inventory (the fight takes it with its quantity; throws spend it).
        self.assertEqual(c.rpc(10, I(1) + I(402) + I(0) + I(-1)), b'\1')
        self.assertEqual(self.inventory(c)['bombs'], {402: 2})
        self.assertEqual(c.rpc(10, I(1) + I(403) + I(0) + I(-1)), b'\0')           # not owned
        # BuyAutoEquipItems (98) has the same request; without shop prices the purchase is refused.
        self.assertEqual(c.rpc(98, I(0) + I(1) + I(205) + I(301)), b'\0')

    def test_shop_and_crafting_from_purchase_to_claimed_potion(self):
        server = self.start('test-economy', self.RECONSTRUCTED)
        c = self.client(server)
        with urllib.request.urlopen(f'http://127.0.0.1:{server.http}/staticdata', timeout=1) as response:
            data = json.loads(gzip.decompress(response.read()))
        # Static data: every referenced id exists; multi-item bundles keep client bundle ids (named ones).
        items = {1: {r['id'] for r in data['ingredients']}, 2: {r['id'] for r in data['bombs']},
                 3: {r['id'] for r in data['potions']}, 4: {r['id'] for r in data['oils']},
                 5: {r['id'] for r in data['lures']}, 6: {r['id'] for r in data['senses_potions']},
                 8: {r['id'] for r in data['armors']}, 9: {r['id'] for r in data['swords']},
                 12: {r['id'] for r in data['brewers']}, 10: {1}, 11: {1}}         # 10: gold, 11: a bag (ItemTypeIds)
        self.assertEqual((len(items[1]), len(items[12])), (13, 3))
        # Client ints only: time_coefficient is a percentage (AlchemyRecipeSlot.GetCraftingTimeText).
        self.assertEqual({r['slug']: r['time_coefficient'] for r in data['brewers']},
                         {'brewer_basic': 100, 'brewer_small': 50, 'brewer_big': 50})
        for table, rows in data.items():
            for row in rows:
                self.assertFalse([k for k, v in row.items() if isinstance(v, float)], table)
        for table in ('potion', 'oil', 'bomb', 'senses_potion'):
            recipes = {r['id']: r for r in data[f'{table}_recipes']}
            self.assertTrue(recipes)
            for row in data[f'{table}_recipe_ingredients']:
                self.assertIn(row['recipe_id'], recipes)
                self.assertIn(row['ingredient_id'], items[1])
        bundles = {r['id']: r for r in data['shop_bundles']}
        stacks = {}
        for row in data['shop_bundle_items']:
            self.assertIn(row['item_id'], items[row['item_type_id']])
            stacks.setdefault(row['shop_bundle_id'], []).append(row)
        self.assertEqual(set(stacks), set(bundles))
        self.assertEqual({b for b, rows in stacks.items() if len(rows) > 1}, {64, 65, 129})
        categories = {r['shop_bundle_id']: (r['layout_group_name_main_category'], r['layout_group_name_sub_category'])
                      for r in data['shop_bundles_layout_group_name_categories']}
        self.assertEqual(set(categories), set(bundles))
        self.assertLessEqual({tab for tab, _ in categories.values()}, {'Basic', 'Alchemy', 'Equipment'})
        self.assertEqual(categories[1205], ('Alchemy', 'Potions'))
        # Oren packs: gold bundles in the Gold group, priced in real money. DataManager.LoadShop needs a price row and
        # the per-store rows (StoreType names) for every inapp_price_id; GoldOfferWindow needs at least one of them.
        prices_in_app = {r['id']: r for r in data['inapp_prices']}
        per_store = {}
        for row in data['inapp_price_shops']:
            per_store.setdefault(row['inapp_price_id'], set()).add(row['shop_name'])
        packs = {b: r for b, r in bundles.items() if r['inapp_price_id'] is not None}
        self.assertEqual(sorted(packs), [77, 78, 79, 80, 81, 82])      # the client's "#0 gold coins" bundles
        for b, row in packs.items():
            self.assertEqual(categories[b], ('Basic', 'Gold'))
            self.assertEqual([(s['item_type_id'], s['item_id']) for s in stacks[b]], [(10, 1)])
            self.assertEqual(prices_in_app[row['inapp_price_id']]['product_type'], 'Consumable')
            self.assertEqual(per_store[row['inapp_price_id']], {'GooglePlay', 'AppStore'})
        self.assertEqual(set(prices_in_app), set(per_store))
        self.assertEqual(bundles[1205]['gold_price'], 60)                 # Swallow ×3 (TheGamer)
        prices = {(r['item_type_id'], r['item_id']): r['gold_price'] for r in data['auto_equip_items_prices']}
        self.assertEqual((prices[(4, 301)], prices[(3, 201)]), (25, 10))
        # The tutorial exam pays nothing (the maintainer's reward list), so a purse of 300 orens; today's deals; a stack of
        # potions and alchemy ingredients.
        c.rpc(57, self.completion_body({3: 1}, instance=self.TUT_EXAM, output='exam_end'))
        server.stop()
        path = self.profile_file('test-economy')
        profile = json.loads(path.read_text())
        profile['Player']['Gold'] = 300
        path.write_text(json.dumps(profile))
        server = self.start('test-economy', self.RECONSTRUCTED)
        c = self.client(server)
        self.assertEqual(self.player_info(c)['gold'], 300)
        deals = Reader(c.rpc(79)); self.assertEqual(deals.byte(), 1)
        daily = deals.ints()
        self.assertEqual(len(daily), 3)
        swallow = 45 if 1205 in daily else 60
        self.assertEqual(c.rpc(80, I(1205) + Q(777)), b'\1' + I(1))            # transaction not found yet
        bought = Reader(c.rpc(75, I(1205) + Q(777)))
        self.assertEqual((bought.byte(), bought.integer(), bought.integer()), (1, 1205, 300 - swallow))
        self.assertEqual(c.rpc(80, I(1205) + Q(777)), b'\1' + I(3))            # completed
        tissue_price = 50 * 75 // 100 if 1103 in daily else 50
        self.assertEqual(c.rpc(75, I(1103) + Q(1))[:5], b'\1' + I(1103))
        self.assertEqual(c.rpc(75, I(129) + Q(2))[:5], b'\1' + I(129))
        gold = 300 - swallow - tissue_price - 80
        self.assertEqual(self.player_info(c)['gold'], gold)
        # The 20-use station costs 300: more than is left, so nothing is bought or charged.
        self.assertLess(gold, 300)
        self.assertEqual(c.rpc(75, I(2202) + Q(3)), b'\0' + I(2202) + I(gold))
        self.assertEqual(self.player_info(c)['gold'], gold)
        self.assertEqual(c.rpc(75, I(99999) + Q(4)), b'\0' + I(99999) + I(gold))   # the unchanged balance
        # Oren packs are never bought with orens (75). Their purchase through the client's fake store (76) is free:
        # the pack's orens once per transaction, a repeat or another request for the same transaction answers
        # without paying again, and anything but an oren pack is refused.
        def in_app(bundle, stamp):
            receipt = b'fake receipt from fake system'
            return I(bundle) + S('GooglePlay') + I(len(receipt)) + receipt + Q(stamp) + S('USD') + I(1) + I(99)
        self.assertEqual(c.rpc(75, I(77) + Q(5)), b'\0' + I(77) + I(gold))
        self.assertEqual(c.rpc(76, in_app(77, 1001)), b'\1' + I(77) + I(gold + 50))
        self.assertEqual(c.rpc(76, in_app(77, 1001), repeat=True), b'\1' + I(77) + I(gold + 50))
        self.assertEqual(c.rpc(76, in_app(77, 1001)), b'\1' + I(77) + I(gold + 50))
        self.assertEqual(c.rpc(76, in_app(78, 1002)), b'\1' + I(78) + I(gold + 150))
        self.assertEqual(c.rpc(76, in_app(65, 1003)), b'\0' + I(65) + I(gold + 150))
        self.assertEqual(c.rpc(76, I(77)), b'\0' + I(0) + I(gold + 150))      # malformed: the verified refusal
        self.assertEqual(self.player_info(c)['gold'], gold + 150)
        gold += 150
        # The ledger settles a nonce once, whatever the RPC id: a repeat answers the purchase without paying again, a
        # nonce reused for another bundle is refused, and a declined nonce stays "not found" and declined.
        self.assertEqual(c.rpc(75, I(1205) + Q(777)), b'\1' + I(1205) + I(gold))
        self.assertEqual(c.rpc(75, I(1103) + Q(777)), b'\0' + I(1103) + I(gold))
        self.assertEqual(c.rpc(80, I(2202) + Q(3)), b'\1' + I(1))
        self.assertEqual(c.rpc(75, I(2202) + Q(3)), b'\0' + I(2202) + I(gold))
        self.assertEqual(self.player_info(c)['gold'], gold)
        inventory = self.inventory(c)
        self.assertEqual((inventory['potions'][205], inventory['ingredients']), (3, {101: 10, 102: 5, 103: 10}))
        # Stations: the unlimited basic station (-1 uses), every formula known.
        brewers = Reader(c.rpc(69)); self.assertEqual(brewers.byte(), 1)
        listed = [(brewers.long(), brewers.integer(), brewers.integer(), brewers.integer(), brewers.integer())
                  for _ in range(brewers.integer())]
        self.assertEqual(listed[0], (1, 1, -1, -1, 0))                      # idle: WorkingRecipe -1
        known = Reader(c.rpc(6))
        recipes = {known.integer(): set(known.ints()) for _ in range(known.integer())}
        self.assertEqual(set(recipes), {2, 3, 4, 6})
        self.assertIn(2101, recipes[3])
        # Thunderbolt: 3 tissue + 2 herbs, 10 minutes; a busy station takes nothing else.
        craft = Reader(c.rpc(4, Q(1) + I(2101) + I(3)))
        self.assertEqual((craft.byte(), craft.long(), craft.integer(), craft.integer()), (1, 1, -1, 2101))
        self.assertAlmostEqual(craft.integer(), time.time() + 600, delta=5)
        self.assertEqual(c.rpc(4, Q(1) + I(2102) + I(3))[:1], b'\0')
        self.assertEqual(self.inventory(c)['ingredients'], {101: 8, 102: 5, 103: 7})
        self.assertEqual(c.rpc(68, Q(1)), b'\0' + Q(1) + I(0))           # not ready yet
        # Ten minutes later (the saved finish time moved back), the potion is handed over.
        server.stop()
        path = self.profile_file('test-economy')
        profile = json.loads(path.read_text())
        player = profile.get('Player') or profile.get('player')
        for brewer in player.get('Brewers') or player.get('brewers'):
            for key in ('FinishTime', 'finishTime'):
                if key in brewer and brewer[key]: brewer[key] = int(time.time()) - 1
        path.write_text(json.dumps(profile))
        server = self.start('test-economy', self.RECONSTRUCTED)
        c = self.client(server)
        self.assertEqual(c.rpc(68, Q(1)), b'\1' + Q(1) + I(1) + I(3) + I(201))
        self.assertEqual(self.inventory(c)['potions'][201], 1)
        # The ledger outlives the restart: the completed nonce is still completed and is not bought again.
        self.assertEqual(c.rpc(80, I(1205) + Q(777)), b'\1' + I(3))
        gold_now = self.player_info(c)['gold']
        self.assertEqual(c.rpc(75, I(1205) + Q(777))[:5], b'\1' + I(1205))
        self.assertEqual(self.player_info(c)['gold'], gold_now)
        # The combat preparation's recommended purchase: one basic oil at its unit price.
        before = self.player_info(c)['gold']
        self.assertEqual(c.rpc(98, I(0) + I(0) + I(301)), b'\1')
        self.assertEqual((self.player_info(c)['gold'], self.inventory(c)['oils'][301]), (before - 25, 1))
        # Senses: free without a potion.
        self.assertEqual(c.rpc(42, I(0) + I(0)), b'\1')
        # The item window's remove button: owned amounts only; storages this server does not keep are refused.
        self.assertEqual(c.rpc(71, I(101) + I(3)), b'\1' + I(101) + I(3))
        self.assertEqual(c.rpc(71, I(101) + I(99)), b'\0' + I(101) + I(0))
        self.assertEqual(c.rpc(50, I(501) + I(1)), b'\0' + I(501) + I(0))
        self.assertEqual(self.inventory(c)['ingredients'][101], 5)
        # A graph's SetQuestObjective is kept for GetCurrentObjective.
        objective = 'QUESTS/OBJECTIVE/TEST'.encode()
        self.assertEqual(c.rpc(62, I(len(objective)) + objective), b'\1' + I(len(objective)) + objective)
        self.assertEqual(c.rpc(61), b'\1' + I(len(objective)) + objective)

    def test_bags_grow_the_inventory_and_a_full_one_leaves_loot_behind(self):
        # The client's bag bundles 95-99 (Bag, Small pouch, Medium-sized pouch, Spacious pouch, Set of saddlebags): bought
        # once, their bag item (type 11) adds its amount to the inventory size; the client counts every stack and station.
        server, c = self.reconstructed()
        with urllib.request.urlopen(f'http://127.0.0.1:{server.http}/staticdata', timeout=1) as response:
            data = json.loads(gzip.decompress(response.read()))
        bundles = {r['id']: r for r in data['shop_bundles']}
        bags = {r['shop_bundle_id']: r['amount'] for r in data['shop_bundle_items'] if r['item_type_id'] == 11}
        self.assertEqual(bags, {95: 50, 96: 50, 97: 100, 98: 200, 99: 400})
        self.assertEqual([(bundles[b]['gold_price'], bundles[b]['one_time']) for b in sorted(bags)],
                         [(500, 1), (500, 1), (1000, 1), (2000, 1), (4000, 1)])
        self.assertIn(('inventoryIncrement', '50'), [(r['param_name'], r['param_value']) for r in data['game_configuration']])
        self.assertEqual(self.inventory(c)['bag'], 200)
        def used(): return sum(sum(m.values()) for k, m in self.inventory(c).items() if k != 'bag') + 1   # + the basic station
        free = 200 - used()
        self.assertEqual(c.rpc(78, I(0)), b'\1')
        server.stop()
        path = self.profile_file('test-fresh')
        saved = json.loads(path.read_text())
        saved['Player']['Gold'] = 1000
        saved['Player']['Items'].setdefault('ingredients', {})['101'] = free - 3
        path.write_text(json.dumps(saved))
        server, c = self.reconstructed()
        self.assertEqual(used(), 197)
        # The summoned ghoul's three ingredients just fit; the drowner's are left behind, its experience is not.
        r = Reader(c.rpc(111, I(16) + I(1) + I(16925168) + I(52406374))); r.byte()
        group, = self.summoned_groups(r)
        ghoul, drowner = group['monsters'][0][1], group['monsters'][1][1]
        body = bytes([1]) + I(13) + I(0) * 13 + bytes([0])
        self.assertEqual(c.rpc(113, Q(ghoul)), b'\1')
        self.assertEqual(self.combat_end(Reader(c.rpc(114, body)))['loot'], [103, 103, 104])
        self.assertEqual(c.rpc(113, Q(drowner)), b'\1')
        full = self.combat_end(Reader(c.rpc(114, body)))
        self.assertEqual((full['loot'], full['base']), ([], 100))
        self.assertEqual(used(), 200)
        # Shop items that do not fit are refused unpaid; a bag makes room, once.
        self.assertEqual(c.rpc(75, I(1205) + Q(1)), b'\0' + I(1205) + I(1000))
        self.assertEqual(c.rpc(75, I(95) + Q(2)), b'\1' + I(95) + I(500))
        self.assertEqual(self.inventory(c)['bag'], 250)
        self.assertEqual(c.rpc(83), b'\1' + I(1) + I(95))
        self.assertEqual(c.rpc(75, I(95) + Q(3)), b'\0' + I(95) + I(500))
        self.assertEqual(c.rpc(75, I(1205) + Q(4))[:1], b'\1')

    def test_joint_venture_catches_up_a_missed_map_output_from_the_facts(self):
        # The map dialog's "map" output reached a server that did not know it; only its facts were saved.
        places = [{'id': f'lab-test-{n}', 'lat': 10.0 + dy / 110540.0, 'lng': 20.0 + dx / 109630.0, 'biomes': [4], 'kind': 'path'}
                  for n, (dy, dx) in enumerate(((500, 0), (-300, 0), (0, 300), (0, -300)))]
        url, _ = self.playable_service(lambda ids, epoch: {
            i: {'center': [10.0, 20.0], 'places': places if n == 0 else []} for n, i in enumerate(ids)})
        server = self.start('test-venture-catchup', dict(self.RECONSTRUCTED, Playable__Url=url))
        c = self.client(server)
        c.rpc(88, I(9) + b''.join(Q(0x4704440000000000 + (k << 40)) for k in range(9)))
        c.rpc(57, self.completion_body({3: 1}, instance=self.TUT_EXAM, output='exam_end'))
        c.rpc(57, self.completion_body())
        c.rpc(57, self.completion_body({94: -3}, instance=HORSE, output='dead_horse'))
        c.rpc(57, self.completion_body({109: 2}, instance=GRIFFIN, output='griffin_1'))
        c.rpc(57, self.completion_body({10146: 1}, instance=5124758224582476011, output='empty'))
        self.assertEqual(c.rpc(78, I(2) + I(107) + I(3) + I(10146) + I(2)), b'\1')
        self.assertEqual(server.state()['questStage'], 'joint_venture')
        obelisk, = Reader(c.rpc(60)).quest()['nodes']
        self.assertEqual((obelisk['node'], obelisk['place']), (9288, 'lab-story-obelisk'))
        self.assertEqual(server.state()['questStage'], 'jv_obelisk')
        # RelocateQuest (77) carries a quest giver's POI id; an active goal is refused with
        # empty lists and the node stays where it is.
        before = Reader(c.rpc(60)).quest()
        self.assertEqual(c.rpc(77, Q(obelisk['instance'])), b'\0' + I(0) * 3)
        self.assertEqual(Reader(c.rpc(60)).quest(), before)
        # The obelisk's facts arriving with an unknown output move the stage on as well.
        after = Reader(c.rpc(57, self.completion_body({107: 4}, instance=0, output='unknown'))).end_graph()
        self.assertEqual([n['node'] for n in after['nodes']], [9289, 9290, 9291])
        self.assertEqual(server.state()['questStage'], 'jv_gifts')

    @staticmethod
    def locations_by_cell(data):
        r = Reader(data)
        assert r.byte() == 1
        cells = {}
        for _ in range(r.integer()):
            cell = r.long()
            cells[cell] = [(r.string(), struct.unpack('>ff', r.take(8)), r.ints()) for _ in range(r.integer())]
        monsters = TestPrototypeHelpers.monster_placements(r)
        herbs = [{'type': r.byte(), 'place': r.string(), 'instance': r.long(), 'herb': r.integer(), 'spawn': r.integer()}
                 for _ in range(r.integer())]
        quests = [{'type': r.byte(), 'place': r.string(), 'instance': r.long(), 'node': r.integer(), 'at': r.string(),
                   'settings': r.string(), 'graph': r.string(), 'mode': r.integer()} for _ in range(r.integer())]
        nests = [{'type': r.byte(), 'place': r.string(), 'instance': r.long(), 'boss': r.integer(), 'state': r.integer()}
                 for _ in range(r.integer())]
        assert r.pos == len(r.data)
        return {'cells': cells, 'monsters': monsters, 'herbs': herbs, 'quests': quests, 'nests': nests}

    def test_nemeton_placement_metadata_reserves_one_anchor_and_suppresses_neighbors(self):
        cells = [0x4704440000000000 + (k << 40) for k in range(3)]
        def response(ids, epoch):
            result = {}
            for cell in ids:
                places = [dict(id=f'lab-{int(cell):016x}-{epoch}-{n}', lat=10.0+n/1000, lng=20.0,
                               biomes=[10], kind='path') for n in range(24)]
                row = dict(center=[10.0, 20.0], places=places)
                if int(cell) == cells[0]: row['nest_place_id'] = places[0]['id']
                if int(cell) == cells[1]: row['nest_place_id'] = None
                result[cell] = row
            return result
        url, _ = self.playable_service(response)
        server = self.start('nest-placement', dict(self.RECONSTRUCTED, Playable__Url=url))
        c = self.client(server)
        world = self.locations_by_cell(c.rpc(40, I(3)+b''.join(Q(i) for i in cells)))
        reserved = world['cells'][cells[0]][0][0]
        self.assertEqual(len(world['nests']), 2)  # explicit anchor + backward-compatible sidecar cell
        self.assertIn(reserved, {n['place'] for n in world['nests']})
        self.assertNotIn(reserved, {p['place'] for p in world['herbs']+world['monsters']})
        for cell in cells:
            partial = self.locations_by_cell(c.rpc(40, I(1)+Q(cell)))
            ids = {p[0] for p in world['cells'][cell]}
            self.assertEqual(partial['nests'], [n for n in world['nests'] if n['place'] in ids])

    def test_reconstructed_world_monsters_spawn_on_safe_places_and_can_be_fought(self):
        cells = [0x4704440000000000 + (k << 40) for k in range(3)]
        url, _ = self.playable_service(lambda ids, epoch: {i: {'center': [10.0, 20.0], 'places': [
            {'id': f'lab-{int(i):016x}-{epoch}-{n}', 'lat': 10.0 + n / 1000, 'lng': 20.0, 'biomes': [10], 'kind': 'path'}
            for n in range(24)]} for i in ids})
        server = self.start('test-world', dict(self.RECONSTRUCTED, Playable__Url=url))
        c = self.client(server)
        c.rpc(78, I(1) + I(10145) + I(1))                                    # saves the new profile
        server.stop()
        path = self.profile_file('test-world')
        profile = json.loads(path.read_text())
        player = profile.get('Player') or profile.get('player')
        player['Exp'], player['LevelAnnounced'] = 45000, 10                     # shared-world comparison against level one
        path.write_text(json.dumps(profile))
        server = self.start('test-world', dict(self.RECONSTRUCTED, Playable__Url=url))
        c = self.client(server)
        request = I(3) + b''.join(Q(cell) for cell in cells)
        world = self.locations_by_cell(c.rpc(40, request))
        self.assertEqual(sorted(world['cells']), cells)
        self.assertEqual(world['quests'], [])
        self.assertEqual(len(world['nests']), 3)                             # one nemeton per cell
        monsters = world['monsters']
        self.assertEqual(len(monsters), 54)                                  # eighteen per cell
        places = {place: cell for cell, rows in world['cells'].items() for place, _, _ in rows}
        # By water stand the species that may by the client's bestiary: not URBAN, and WATER when they name a habitat
        # (FOREST or WATER). Any time of day may hold.
        water = {s['monster_id']: s['difficulty'] for s in WORLD['species']
                 if 'URBAN' not in s['tags'] and ('WATER' in s['tags'] or 'FOREST' not in s['tags'])}
        self.assertLessEqual({3, 4}, set(water))
        now = int(time.time())
        for monster in monsters:
            self.assertIn(monster['monster'], water)
            self.assertEqual((monster['type'], monster['level']), (0, water[monster['monster']]))   # row difficulty
            self.assertIn(monster['place'], places)
            # Each lives 30 minutes and is on the map now.
            self.assertEqual(monster['ttl'], 1800)
            self.assertTrue(monster['spawn_ms'] // 1000 <= now < monster['spawn_ms'] // 1000 + 1800)
        # Monsters never share a place with each other, a herb or a nemeton.
        herb_places = {h['place'] for h in world['herbs']} | {n['place'] for n in world['nests']}
        self.assertEqual(len({m['place'] for m in monsters}), 54)
        self.assertFalse({m['place'] for m in monsters} & herb_places)
        # Three monsters occupy each of the six original expiry phases.
        for cell in cells:
            ends = sorted({(m['spawn_ms'] // 1000 + 1800) % 1800 for m in monsters if places[m['place']] == cell})
            self.assertEqual([b - a for a, b in zip(ends, ends[1:])], [300] * 5)
        self.assertEqual(self.locations_by_cell(c.rpc(40, request))['monsters'], monsters)   # stable
        self.assertEqual(self.locations_by_cell(c.rpc(40, I(0)))['cells'], {})
        # Ordinary world visibility does not depend on XP: a level-one witcher gets the same
        # monsters, identities, difficulty and lifetime as a level-ten witcher.
        young = self.client(server, identity=('SYNTHETIC_DEVICE_YOUNG', ''))
        seen = self.locations_by_cell(young.rpc(40, request))
        shared = monsters
        self.assertEqual(seen['monsters'], shared)
        self.assertEqual((seen['herbs'], seen['nests']), (world['herbs'], world['nests']))
        # An expired monster's place asks for the cell's current monsters.
        target = shared[0] if shared else monsters[0]
        respawn = Reader(c.rpc(87, I(1) + S(target['place'])))
        self.assertEqual(respawn.byte(), 0)
        again = TestPrototypeHelpers.monster_placements(respawn)
        self.assertEqual(again, [m for m in monsters if places[m['place']] == places[target['place']]])
        # Fight: unknown instances are refused; a won fight grants the published XP and removes the monster.
        self.assertEqual(c.rpc(41, Q(12345)), b'\0')
        self.assertEqual(c.rpc(41, Q(target['instance'])), b'\1')
        won = self.combat_end(Reader(c.rpc(8, b'\1' + I(13) + I(0) * 13 + b'\0')))
        base = {1: 100, 2: 250, 3: 600}[water[target['monster']]]                 # by the row's difficulty
        self.assertEqual((won['base'], won['first']), (base, 100))
        self.assertTrue(won['loot'])
        self.assertEqual(self.inventory(c)['ingredients'], dict(collections.Counter(won['loot'])))
        self.assertEqual(self.player_info(c)['exp'], 45000 + base + 100)
        self.assertEqual(Reader(c.rpc(56)).longs(), [target['instance']])
        self.assertEqual(Reader(decode_batch(c.rpc(115))[56]).longs(), [target['instance']])
        self.assertEqual(c.rpc(41, Q(target['instance'])), b'\0')
        left = self.locations_by_cell(c.rpc(40, request))['monsters']
        self.assertEqual(left, [m for m in monsters if m != target])
        if shared:                                                           # the kill is the killer's own
            self.assertIn(target, self.locations_by_cell(young.rpc(40, request))['monsters'])
        # A fight without an encounter grants nothing.
        self.assertEqual(self.combat_end(Reader(c.rpc(8, b'\1' + I(13) + I(0) * 13 + b'\0')))['base'], 0)
        # The shared lottery can select any rarity: tier 1 needs 3 common, 2 rare, or 1 legendary kill.
        points = server.state()['player']['skillPoints']
        kind = target['monster']
        rarity = next(s['rarity'] for s in WORLD['species'] if s['monster_id'] == kind)
        first_tier = int(rarity == 3)
        expected_claim = b'\1' + I(kind) + I(1) if first_tier else b'\0' + I(-1) + I(0)
        self.assertEqual(c.rpc(65, I(kind)), expected_claim)
        # A fresh second request cannot claim the same tier again, including legendary species.
        self.assertEqual(c.rpc(65, I(kind)), b'\0' + I(-1) + I(0))
        self.assertEqual(c.rpc(65, I(9)), b'\0' + I(-1) + I(0))
        self.assertEqual(server.state()['player']['skillPoints'], points + first_tier)
        killed = Reader(decode_batch(c.rpc(115))[7])
        self.assertEqual((killed.facts(), killed.facts()), ({kind: 1}, {kind: 1} if first_tier else {}))
        # Herbs: four per cell on the day's places, types from the herbs table, visible now (SpawnTime 0).
        herbs = world['herbs']
        self.assertEqual(len(herbs), 12)
        self.assertTrue(all(h['place'] in places and h['herb'] in range(1, 6) and h['spawn'] == 0 for h in herbs))
        # GatherHerb (19): [byte Success][int n][int loot × n][int RespawnTime][long id]; bundles of herbs (and
        # sometimes a root) into the inventory, the herb hidden for an hour; a second gathering is refused.
        herb = herbs[0]['instance']
        before = self.inventory(c)['ingredients']
        got = Reader(c.rpc(19, Q(herb)))
        self.assertEqual(got.byte(), 1)
        loot, respawn = got.ints(), got.integer()
        self.assertEqual(got.long(), herb)
        self.assertEqual(loot[:2], [101, 101])
        self.assertLessEqual(set(loot), {101, 102})
        self.assertAlmostEqual(respawn, time.time() + 3600, delta=5)
        after = self.inventory(c)['ingredients']
        self.assertEqual(after.get(101, 0) - before.get(101, 0), loot.count(101))
        self.assertEqual(c.rpc(19, Q(herb)), b'\0' + I(0) + I(0) + Q(herb))
        self.assertEqual(c.rpc(19, Q(12345)), b'\0' + I(0) + I(0) + Q(12345))
        hidden = {h['instance']: h['spawn'] for h in self.locations_by_cell(c.rpc(40, request))['herbs']}
        self.assertEqual(hidden[herb], respawn)
        others = {h['instance']: h['spawn'] for h in self.locations_by_cell(young.rpc(40, request))['herbs']}
        self.assertEqual(others[herb], 0)                                    # still there for the other player
        # The senses: a Falcon reveals the listed monsters, which GetSensedMonsters (43) keeps while they live;
        # a potion that would reveal nothing is not spent.
        c.rpc(57, self.completion_body({3: 1}, instance=self.TUT_EXAM, output='exam_end'))
        self.assertEqual(c.rpc(75, I(1601) + Q(9))[:5], b'\1' + I(1601))
        falcons = self.inventory(c)['senses'][601]
        sensed = [m['instance'] for m in left[:2]]
        self.assertEqual(c.rpc(42, I(601) + I(2) + b''.join(Q(i) for i in sensed)), b'\1')
        self.assertEqual(c.rpc(42, I(601) + I(0)), b'\0')
        self.assertEqual(self.inventory(c)['senses'].get(601, 0), falcons - 1)
        self.assertEqual(Reader(c.rpc(43)).byte(), 1)
        answer = Reader(c.rpc(43)); answer.byte()
        self.assertEqual(answer.longs(), sorted(sensed))
        self.assertEqual(decode_batch(c.rpc(115))[43], c.rpc(43))

    @staticmethod
    def nest_state(data):
        r = Reader(data)
        if r.byte() != 1:
            assert r.pos == len(r.data)
            return None
        result = {'id': r.long(), 'wins': r.integer(), 'limit': r.integer(), 'monsters': r.ints(), 'state': r.byte(),
                  'gold': r.integer(), 'exp': r.integer(), 'iteration': r.integer()}
        assert r.pos == len(r.data)
        return result

    @staticmethod
    def nest_end(data):
        r = Reader(data)
        if r.byte() != 1:
            assert r.pos == len(r.data)
            return None
        loot = r.ints()
        keys = ('gold', 'rarity', 'first', 'attacks', 'oil', 'duration', 'parries', 'clearing', 'boosted')
        result = dict(zip(keys, (r.integer() for _ in keys)), loot=loot)
        assert r.pos == len(r.data)
        return result

    @staticmethod
    def nest_combat(win, nest, bomb=0, details=((), (), ())):
        def block(values):
            values = list(values) + [0] * (13 - len(values))
            return I(len(values)) + b''.join(I(v) for v in values)
        return (b'\1' if win else b'\0') + Q(nest) + I(bomb) + b''.join(block(d) for d in details)

    def test_nemeta_fights_bonus_limit_and_baits(self):
        cells = [0x4704440000000000 + (k << 40) for k in range(4)]
        url, _ = self.playable_service(lambda ids, epoch: {i: {'center': [10.0, 20.0], 'places': [
            {'id': f'lab-{int(i):016x}-{epoch}-{n}', 'lat': 10.0 + n / 1000, 'lng': 20.0, 'biomes': [1], 'kind': 'path'}
            for n in range(6)]} for i in ids})
        env = dict(self.RECONSTRUCTED, Playable__Url=url)
        server = self.start('test-nest', env)
        c = self.client(server)
        request = I(len(cells)) + b''.join(Q(cell) for cell in cells)
        world = self.locations_by_cell(c.rpc(40, request))
        nests = world['nests']
        herb_places = {h['place'] for h in world['herbs']}
        places = {place for rows in world['cells'].values() for place, _, _ in rows}
        # Placement<Nest>: [byte 0][string PlaceId][long InstanceId][int BossType][int NestState]; one per cell on a
        # place of the day that no herb uses, Default at first, the same on every request.
        self.assertEqual(len(nests), 4)
        self.assertTrue(all(n['type'] == 0 and n['state'] == 1 and n['place'] in places - herb_places for n in nests))
        self.assertEqual(self.locations_by_cell(c.rpc(40, request))['nests'], nests)
        # Below level 10 a nest answers NotAllowed (5); unknown nests are refused.
        first = nests[0]['instance']
        locked = self.nest_state(c.rpc(52, Q(first)))
        self.assertEqual((locked['state'], locked['limit'], locked['gold'], locked['exp']), (5, 3, 50, 500))
        self.assertIsNone(self.nest_state(c.rpc(52, Q(12345))))
        # Level 10 (45000 XP) with two basic bombs and some baits.
        server.stop()
        path = self.profile_file('test-nest')
        profile = json.loads(path.read_text())
        player = profile.get('Player') or profile.get('player')
        player['Exp'], player['LevelAnnounced'] = 45000, 10
        player['Items'] = {'bombs': {'401': 2}, 'lures': {'507': 1, '502': 1}}
        path.write_text(json.dumps(profile))
        server = self.start('test-nest', env)
        c = self.client(server)
        nests = self.locations_by_cell(c.rpc(40, request))['nests']
        self.assertEqual(self.inventory(c)['lures'], {502: 1, 507: 1})
        encountered = self.nest_state(c.rpc(52, Q(first)))
        self.assertEqual((encountered['id'], encountered['wins'], encountered['state'], encountered['iteration']), (first, 0, 1, 0))
        monsters = encountered['monsters']
        self.assertEqual(len(monsters), 3)
        self.assertEqual(monsters[2], nests[0]['boss'])                      # BossType is the third monster
        # No bait before the nest is cleared; no fight result for a nest other than the encountered one.
        self.assertIsNone(self.nest_state(c.rpc(18, Q(first) + I(507))))
        self.assertIsNone(self.nest_end(c.rpc(53, self.nest_combat(True, nests[1]['instance']))))
        # A lost run spends the thrown bomb and changes nothing else.
        c.rpc(52, Q(first))
        lost = self.nest_end(c.rpc(53, self.nest_combat(False, first, 401, ((0,) * 12 + (1,), (), ()))))
        self.assertEqual(lost, dict(gold=0, rarity=0, first=0, attacks=0, oil=0, duration=0, parries=0, clearing=0,
                                    boosted=0, loot=[]))
        self.assertEqual(self.inventory(c)['bombs'], {401: 1})
        self.assertEqual(self.nest_state(c.rpc(52, Q(first)))['state'], 1)
        c.rpc(52, Q(first))
        # A won run: 50 gold, 25 XP per common monster, 100 per new kind, 15 per perfect attack (Details[1]) and
        # perfect parry, 50 per fight with the proper oil (Details[10]), 500 for the clearing; loot of the three
        # monsters; the nest becomes DefaultClear.
        before = self.player_info(c)
        won = self.nest_end(c.rpc(53, self.nest_combat(True, first, 401, ((0, 2) + (0,) * 8 + (1,), (), (0,) * 11 + (1,)))))
        kinds = len(set(monsters))
        self.assertEqual((won['gold'], won['rarity'], won['first'], won['attacks'], won['oil'], won['parries'], won['clearing']),
                         (50, 75, 100 * kinds, 30, 50, 15, 500))
        self.assertTrue(len(won['loot']) >= 6)
        after = self.player_info(c)
        self.assertEqual(after['gold'] - before['gold'], 50)
        self.assertEqual(after['exp'] - before['exp'], 75 + 100 * kinds + 30 + 50 + 15 + 500)
        state = server.state()['player']
        for monster in set(monsters):
            self.assertEqual(state['kills'][str(monster)], monsters.count(monster))
        cleared = self.nest_state(c.rpc(52, Q(first)))
        self.assertEqual((cleared['state'], cleared['wins'], cleared['iteration']), (2, 1, 1))
        self.assertIsNone(self.nest_end(c.rpc(53, self.nest_combat(True, first))))   # cleared: nothing to fight
        # Baits: an unowned one or one whose class no nemeton holds is refused and kept; a necrophage bait lures
        # two necrophages and an alghoul, and is spent.
        c.rpc(52, Q(first))
        self.assertIsNone(self.nest_state(c.rpc(18, Q(first) + I(508))))
        self.assertIsNone(self.nest_state(c.rpc(18, Q(first) + I(502))))
        lured = self.nest_state(c.rpc(18, Q(first) + I(507)))
        self.assertEqual((lured['state'], lured['monsters'][2]), (3, 2))
        self.assertLessEqual(set(lured['monsters'][:2]), {1, 3, 10})
        self.assertEqual(self.inventory(c)['lures'], {502: 1})
        self.assertEqual(self.nest_state(c.rpc(52, Q(first)))['monsters'], lured['monsters'])
        self.assertEqual(self.nest_end(c.rpc(53, self.nest_combat(True, first)))['gold'], 50)
        done = self.nest_state(c.rpc(52, Q(first)))
        self.assertEqual((done['state'], done['wins'], done['iteration']), (4, 2, 2))
        c.rpc(75, I(1501) + Q(1))                                        # not enough gold is fine either way
        self.assertIsNone(self.nest_state(c.rpc(18, Q(first) + I(501))))  # LuredClear: no more bait today
        # The bonus is paid for the first three clears of the day only; the experience is not limited.
        c.rpc(52, Q(nests[1]['instance']))
        self.assertEqual(self.nest_end(c.rpc(53, self.nest_combat(True, nests[1]['instance'])))['gold'], 50)
        c.rpc(52, Q(nests[2]['instance']))
        fourth = self.nest_end(c.rpc(53, self.nest_combat(True, nests[2]['instance'])))
        self.assertEqual((fourth['gold'], fourth['clearing']), (0, 500))
        self.assertEqual(self.nest_state(c.rpc(52, Q(nests[3]['instance'])))['wins'], 4)
        self.assertEqual([n['state'] for n in self.locations_by_cell(c.rpc(40, request))['nests']], [4, 2, 2, 1])
        # A new UTC day brings every nest back with its own monsters and a new bonus count.
        server.stop()
        profile = json.loads(path.read_text())
        player = profile.get('Player') or profile.get('player')
        player['Nests']['Day'] -= 1
        path.write_text(json.dumps(profile))
        server = self.start('test-nest', env)
        c = self.client(server)
        self.assertEqual([n['state'] for n in self.locations_by_cell(c.rpc(40, request))['nests']], [1, 1, 1, 1])
        self.assertEqual(self.nest_state(c.rpc(52, Q(first)))['wins'], 0)
        # Legacy profiles have no nests.
        legacy = self.client(self.start('test-nest-legacy'))
        self.assertEqual(legacy.rpc(52, Q(first)), b'\0')

    def test_bait_rows_shop_and_nest_configuration(self):
        server, c = self.reconstructed()
        c.rpc(3); c.rpc(3)      # the first request saves the profile after its answer; the second waits for that
        with urllib.request.urlopen(f'http://127.0.0.1:{server.http}/staticdata', timeout=1) as response:
            data = json.loads(gzip.decompress(response.read()))
        self.assertEqual([(row['id'], row['slug']) for row in data['lures']], [
            (501, 'lure_basic'), (502, 'lure_cursed'), (503, 'lure_draconid'), (504, 'lure_elemental'),
            (505, 'lure_hybrid'), (506, 'lure_insectoid'), (507, 'lure_necrophage'), (508, 'lure_ogroid'),
            (509, 'lure_relict'), (510, 'lure_specter'), (511, 'lure_vampire')])
        sold = [501, 503, 507, 508, 510]
        self.assertEqual(data['shop_lures'], [{'item_id': i, 'price': 200} for i in sold])
        self.assertEqual({row['param_name']: row['param_value'] for row in data['game_configuration']},
                         {'nestClearingExp': '500', 'nestDailyLimit': '3', 'nestPlayerMinimalLevel': '10',
                          'inventoryIncrement': '50'})
        baits = [row['shop_bundle_id'] for row in data['shop_bundles_layout_group_name_categories']
                 if row['layout_group_name_sub_category'] == 'Baits']
        self.assertEqual(baits, [1000 + i for i in sold])
        prices = {row['id']: row['gold_price'] for row in data['shop_bundles']}
        self.assertTrue(all(prices[b] == 200 for b in baits))
        items = [(row['item_type_id'], row['item_id'], row['amount']) for row in data['shop_bundle_items']
                 if row['shop_bundle_id'] in baits]
        self.assertEqual(items, [(5, i, 1) for i in sold])
        # A bought bait lands in the inventory's lure map, and can be dropped (DropLure 50).
        server.stop()
        path = self.profile_file('test-fresh')
        profile = json.loads(path.read_text())
        player = profile.get('Player') or profile.get('player')
        player['Gold'] = 500
        path.write_text(json.dumps(profile))
        server = self.start('test-fresh', self.RECONSTRUCTED)
        c = self.client(server)
        self.assertEqual(c.rpc(75, I(1507) + Q(1))[:5], b'\1' + I(1507))
        self.assertEqual(self.inventory(c)['lures'], {507: 1})
        self.assertEqual(self.player_info(c)['gold'], 300)
        self.assertEqual(c.rpc(50, I(507) + I(1)), b'\1' + I(507) + I(1))
        self.assertEqual(self.inventory(c)['lures'], {})

    def test_a_giver_stands_within_sight_of_where_the_game_says_the_player_is(self):
        # Without GPS from the hook a giver goes around the loaded area's centre, which can be out of the client's 350 m
        # sight. The game's weather request carries its own position: a giver not yet met is placed again around it.
        origin = (10.0, 20.0)
        metres = lambda a, b: math.hypot((a[0] - b[0]) * 110540.0, (a[1] - b[1]) * 111320.0 * math.cos(math.radians(a[0])))
        east = lambda m: (origin[0], origin[1] + m / (111320.0 * math.cos(math.radians(origin[0]))))
        places = [{'id': f'lab-test-{r}-{k}', 'lat': origin[0] + dy * r / 110540.0,
                   'lng': origin[1] + dx * r / (111320.0 * math.cos(math.radians(origin[0]))), 'biomes': [4], 'kind': 'path'}
                  for r in (200, 350, 500, 650, 750) for k, (dy, dx) in enumerate(((1, 0), (0, 1), (-1, 0), (0, -1)))]
        url, _ = self.playable_service(lambda ids, epoch: {
            i: {'center': list(origin), 'places': places if n == 0 else []} for n, i in enumerate(ids)})
        env = dict(self.RECONSTRUCTED, Playable__Url=url)
        server = self.start('test-sight', env)
        first = self.client(server); first.rpc(3); first.rpc(3)
        server.stop()
        path = self.profile_file('test-sight')
        profile = json.loads(path.read_text())
        profile['QuestStage'], profile['Facts'] = 'jv_done', {'100': 4}
        path.write_text(json.dumps(profile))
        c = self.client(self.start('test-sight', env))
        request = I(9) + b''.join(Q(0x4704440000000000 + (k << 40)) for k in range(9))
        c.rpc(88, request)

        def margit():
            world = self.locations_by_cell(c.rpc(40, request))
            giver, = [g for g in world['quests'] if g['node'] == 11491]
            return {name: point for rows in world['cells'].values() for name, point, _ in rows}[giver['place']]
        self.assertTrue(80 <= metres(margit(), origin) <= 300)            # no position known: around the area's centre
        player = east(650)
        c.rpc(67, struct.pack('>ff', *player))
        self.assertTrue(80 <= metres(margit(), player) <= 300)

    def test_good_money_runs_from_the_giver_to_the_payment(self):
        # Season 1 story engine: after "A Joint Venture" Margit is offered as a quest giver; her graph starts
        # quest 149, the cocoons follow, and her payment ends the quest.
        origin = (10.0, 20.0)
        metres = lambda a, b: math.hypot((a[0] - b[0]) * 110540.0, (a[1] - b[1]) * 111320.0 * math.cos(math.radians(a[0])))
        places = [{'id': f'lab-test-{r}-{k}', 'lat': origin[0] + dy * r / 110540.0,
                   'lng': origin[1] + dx * r / (111320.0 * math.cos(math.radians(origin[0]))), 'biomes': [4], 'kind': 'path'}
                  for r in (200, 350, 500, 650, 750) for k, (dy, dx) in enumerate(((1, 0), (0, 1), (-1, 0), (0, -1)))]
        url, _ = self.playable_service(lambda ids, epoch: {
            i: {'center': list(origin), 'places': places if n == 0 else []} for n, i in enumerate(ids)})
        env = dict(self.RECONSTRUCTED, Playable__Url=url)
        server = self.start('test-season1', env)
        c = self.client(server)
        cells = [0x4704440000000000 + (k << 40) for k in range(9)]
        request = I(9) + b''.join(Q(cell) for cell in cells)
        c.rpc(88, request)
        self.assertEqual(self.locations_by_cell(c.rpc(40, request))['quests'], [])      # before "A Joint Venture" ends
        # Static data: quest 149 hangs below the tutorial root with its activation criteria.
        with urllib.request.urlopen(f'http://127.0.0.1:{server.http}/staticdata', timeout=1) as response:
            data = json.loads(gzip.decompress(response.read()))
        quest, = [q for q in data['quests'] if q['id'] == 149]
        self.assertEqual((quest['season_id'], quest['activation_criteria'], quest['journal_log']),
                         (0, 'f100>=4', 'assets/_bundledassets/story/journal/s01/s01mq01_scholar/log_s01mq01.asset'))
        self.assertIn({'from_quest_id': 144, 'to_quest_id': 149}, data['quest_edges'])
        nodes = {n['id']: n for n in data['quest_nodes'] if n['quest_id'] == 149}
        self.assertEqual(sorted(nodes), [297, 11491, 11492, 11493])
        self.assertEqual(nodes[11491]['activation_criteria'], 'f53<1')
        targets = {e['to_quest_node_id'] for e in data['quest_node_edges']}
        self.assertEqual([n for n in nodes if n not in targets], [11491])                # the root: Margit
        ends = [o['name'] for o in data['quest_node_outputs'] if o['quest_node_id'] in nodes and o['endpoint']]
        self.assertEqual(ends, ['scholar_02'])
        # "A Joint Venture" is over and fact 100 says so: Margit stands in one of the loaded cells.
        c.rpc(3); c.rpc(3)
        server.stop()
        path = self.profile_file('test-season1')
        profile = json.loads(path.read_text())
        profile['QuestStage'] = 'jv_done'
        profile['Facts'] = {'100': 4}
        path.write_text(json.dumps(profile))
        server = self.start('test-season1', env)
        c = self.client(server)
        c.rpc(88, request)
        world = self.locations_by_cell(c.rpc(40, request))
        # Evil Never Sleeps and To the Rescue need no earlier quest either (Kienan shows beside the walking player).
        self.assertEqual({g['node']: g['mode'] for g in world['quests']}, {11491: 1, 16160: 1, 292: 7})
        giver = next(g for g in world['quests'] if g['node'] == 11491)
        self.assertEqual((giver['node'], giver['graph'], giver['settings'].rsplit('/', 2)[-2:], giver['mode']),
                         (11491, 's01/s01mq01_scholar/s01mq01_scholar_01', ['mq01', 'scholar_lq.asset'], 1))
        self.assertEqual(giver['place'], giver['at'])
        located = {name: point for rows in world['cells'].values() for name, point, _ in rows}
        margit = located[giver['place']]
        self.assertTrue(80 <= metres(margit, origin) <= 300)
        quests = decode_finished_quests(decode_batch(c.rpc(115))[70])
        self.assertEqual((quests['finished'], quests['tracked'], quests['active']), ([144, 145, 146], -1, []))

        def step(output, facts, instance):
            result = Reader(c.rpc(57, self.completion_body(facts, instance=instance, output=output))).end_graph()
            points = {name: struct.unpack('>ff', raw) for name, raw, _ in result['locations']}
            return result, {n['node']: points[n['place']] for n in result['nodes']}

        # Margit takes the figurine and pays 60 gold (fact 175); the endrega lair appears, the giver goes.
        result, at = step('scholar_01', {53: 1, 175: 60, 10149: 1}, giver['instance'])
        self.assertEqual(([n['node'] for n in result['nodes']], result['gold'], result['exp']), ([297], 60, 0))
        lair = at[297]
        self.assertTrue(300 <= metres(lair, origin) <= 800)
        # The started quest has a hidden relocation giver with a separate instance; the client hides it
        # through SetActiveQuestGivers but uses it when looking for a relocation destination.
        relocation, = [g for g in self.locations_by_cell(c.rpc(40, request))['quests'] if g['node'] == giver['node']]
        self.assertNotEqual(relocation['instance'], giver['instance'])
        self.assertEqual(c.rpc(72, I(149)), b'\1' + I(149))
        quests = decode_finished_quests(decode_batch(c.rpc(115))[70])
        self.assertEqual((quests['tracked'], quests['active']), (149, [149]))
        cocoon = result['nodes'][0]['instance']
        # Two endrega workers: fight experience and a bestiary entry once each; a lost fight keeps the lair.
        won = Reader(c.rpc(57, self.completion_body({1: 1}, instance=cocoon, output='endriagaworker_01'))).end_graph()
        self.assertEqual((won['exp'], won['bestiary'], [n['node'] for n in won['nodes']]), (100, {14: 1}, [297]))
        again = Reader(c.rpc(57, self.completion_body({1: 1}, instance=cocoon, output='endriagaworker_01'))).end_graph()
        self.assertEqual((again['exp'], again['bestiary']), (0, {}))
        lost = Reader(c.rpc(57, self.completion_body({}, instance=cocoon, output='one_left'))).end_graph()
        self.assertEqual([n['node'] for n in lost['nodes']], [297])
        c.rpc(57, self.completion_body({1: 2}, instance=cocoon, output='endriagaworker_02'))
        result, at = step('dehael', {1: 4, 53: 2, 10149: 2}, cocoon)
        self.assertEqual([n['node'] for n in result['nodes']], [11492])
        self.assertLessEqual(metres(at[11492], lair), 150)
        second = result['nodes'][0]['instance']
        self.assertEqual(Reader(c.rpc(57, self.completion_body({1: 5}, instance=second, output='endriagaworker'))).end_graph()['exp'], 100)
        tailed = Reader(c.rpc(57, self.completion_body({1: 6}, instance=second, output='endriagatailed'))).end_graph()
        self.assertEqual((tailed['exp'], tailed['bestiary']), (250, {15: 1}))
        result, at = step('embrions', {53: 3, 50: 1, 1: 7}, second)
        self.assertEqual([(n['node'], n['place']) for n in result['nodes']], [(11493, giver['place'])])
        # Her payment ends the quest: 250 XP and 40 gold (the maintainer's reward list), nothing left on the map.
        before = self.player_info(c)
        done = Reader(c.rpc(57, self.completion_body({53: 4, 1000: 1, 1001: 1, 1003: 1, 102: 4}, instance=result['nodes'][0]['instance'],
                                                    output='scholar_02'))).end_graph()
        # Nothing of Good Money is left; Lothar's map (Sword in the Stone) now waits invisible beside the player.
        self.assertEqual((done['exp'], done['gold'], [n['node'] for n in done['nodes']]), (250, 40, [399]))
        after = self.player_info(c)
        self.assertEqual((after['exp'] - before['exp'], after['gold'] - before['gold']), (250, 40))
        quests = decode_finished_quests(decode_batch(c.rpc(115))[70])
        self.assertEqual((quests['finished'], quests['tracked'], quests['active']), ([144, 145, 146, 149], -1, []))
        # Facts 1001 and 1003 open Pride Ain't Cheap, What Lurks in the Nemeta and The Dark Side of the Full Moon; Monster
        # Slayer waits for its troll trigger, Will o' the Wisp and The Great Mushrooming for their quests before.
        self.assertEqual({q['node'] for q in self.locations_by_cell(c.rpc(40, request))['quests']},
                         {16160, 292, 301, 18360, 289})
        state = server.state()['player']
        self.assertEqual((state['kills']['14'], state['kills']['15']), (3, 1))
        self.assertEqual(state['exp'], 100 * 3 + 250 + 250)
        # An output the node does not have changes nothing.
        unknown = Reader(c.rpc(57, self.completion_body({}, instance=result['nodes'][0]['instance'], output='nope'))).end_graph()
        self.assertEqual((unknown['exp'], [n['node'] for n in unknown['nodes']]), (0, [399]))

    def relocation_fixture(self, stage='jv_done', facts=None, started=None, done=None):
        area_a, area_b = 0x4704440000000000, 0x4804440000000000
        control = {'radii': (100, 150, 200, 250, 300, 350, 400, 500, 600, 700, 800, 900), 'origins': {}}
        def respond(ids, epoch):
            result = {}
            for cell in ids:
                origin = control['origins'].get(int(cell), (10.0 if int(cell) == area_a else 11.0, 20.0))
                result[cell] = {'center': origin, 'places': [
                    {'id': f'test-{cell}-{r}-{k}',
                     'lat': origin[0] + math.sin(k * math.pi / 8) * r / 110540,
                     'lng': origin[1] + math.cos(k * math.pi / 8) * r / (111320 * math.cos(math.radians(origin[0]))),
                     'biomes': [4], 'kind': 'path'} for r in control['radii'] for k in range(16)]}
            return result
        url, _ = self.playable_service(respond)
        env = dict(self.RECONSTRUCTED, Playable__Url=url)
        server = self.start('test-relocation', env)
        c = self.client(server); c.rpc(3); c.rpc(3)
        server.stop()
        path = self.profile_file('test-relocation')
        profile = json.loads(path.read_text())
        profile['QuestStage'], profile['Facts'] = stage, {str(k): v for k, v in (facts or {}).items()}
        profile['Player']['StoryDone'] = done or []
        profile['Player']['Story'] = {'Active': [], 'Started': started or [], 'Finished': [], 'Outputs': [],
                                      'Tracked': (started or [None])[0], 'Reached': {}, 'Clock': 0}
        if stage == 'jv_gifts':
            profile['Player']['StoryPlaces'] = {'obelisk': {'Id': 'lab-story-obelisk',
                'Lat': 10 + 500 / 110540, 'Lng': 20, 'Biomes': [4], 'CellId': area_a}}
        path.write_text(json.dumps(profile))
        server = self.start('test-relocation', env); c = self.client(server)
        c.rpc(88, I(1) + Q(area_a))
        old = c.rpc(60)
        return server, c, path, env, old, area_a, area_b, control

    def test_relocation_moves_goals_once_preserves_progress_and_survives_restart(self):
        # The leshen moves; the mushroom and the queued graphs stay beside the player, and a second active quest is untouched.
        server, c, path, env, old, a, b, _ = self.relocation_fixture(
            facts={100: 4, 56: 3, 53: 1, 58: 1}, started=[153, 149])
        old_world = self.locations_by_cell(c.rpc(40, I(1) + Q(a)))
        c.rpc(88, I(1) + Q(b))
        world = self.locations_by_cell(c.rpc(40, I(1) + Q(b)))
        root = next(n for n in SEASON1['nodes'] if n['quest'] == 153 and n['kind'] == 'giver')
        giver = next(g for g in world['quests'] if g['node'] == root['id'])
        previous = next(g for g in old_world['quests'] if g['node'] == root['id'])
        self.assertNotEqual((giver['instance'], giver['place']), (previous['instance'], previous['place']))
        self.assertEqual(c.rpc(60), old)  # Moving/loading cells alone never moves the goals.
        before = json.loads(path.read_text())
        # A reconnect can leave two sockets replaying the same request id at once.
        second_client = self.client(server)
        second_client.sequence = c.sequence = c.sequence + 1
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            replies = list(pool.map(lambda client: client.rpc(77, Q(giver['instance']), repeat=True),
                                    (c, second_client)))
        response = replies[0]
        self.assertEqual(replies[1], response)
        self.assertEqual(response[:1], b'\1')
        after = json.loads(path.read_text())
        self.assertEqual(after['Revision'], before['Revision'] + 1)
        for field in before['Player']:
            if field != 'StoryPlaces': self.assertEqual(after['Player'][field], before['Player'][field], field)
        self.assertEqual(after['Facts'], before['Facts'])
        moved = Reader(response[1:]).quest()
        old_nodes = {n['instance']: n for n in Reader(old).quest()['nodes']}
        leshen = next(n for n in SEASON1['nodes'] if n['key'] == 's01mq05_leshen')
        goal, = [n for n in moved['nodes'] if n['node'] == leshen['id']]
        positions = {key: struct.unpack('>ff', raw) for key, raw, _ in moved['locations']}
        self.assertNotEqual(goal['place'], old_nodes[goal['instance']]['place'])
        self.assertLess(abs(positions[goal['place']][0] - 11), .01)
        mushroom = next(n for n in SEASON1['nodes'] if n['key'] == 's01mq05_mushroom')
        self.assertEqual([(n['mode'], n['place']) for n in moved['nodes'] if n['node'] == mushroom['id']], [(7, 'tut_thorstein')])
        for node in moved['nodes']:
            if node is not goal: self.assertEqual(node, old_nodes[node['instance']])
        self.assertEqual(c.rpc(77, Q(giver['instance']), repeat=True), response)
        self.assertEqual(json.loads(path.read_text()), after)
        self.assertEqual(c.rpc(60), response[1:])
        self.assertEqual(c.rpc(77, Q(giver['instance'])), b'\0' * 13)
        self.assertEqual(json.loads(path.read_text()), after)
        server.stop()
        c = self.client(self.start('test-relocation', env))
        self.assertEqual(c.rpc(60), response[1:])
        self.assertEqual(json.loads(path.read_text()), after)

    def test_relocation_follows_map_deltas_without_another_load_cells(self):
        _, c, path, _, old, a, b, _ = self.relocation_fixture('dead_horse', {94: -3})
        old_giver, = self.locations_by_cell(c.rpc(40, I(1) + Q(a)))['quests']
        # PoiModule.LoadCells sends only new cells in RPC 40; RPC 88 belongs to bootstrap.
        # A teleport loads a fresh group, then movement adds a partial strip or no cells.
        fresh = [b + k * (1 << 32) for k in range(9)]
        body = lambda ids: I(len(ids)) + b''.join(Q(i) for i in ids)
        world = self.locations_by_cell(c.rpc(40, body(fresh)))
        giver, = world['quests']
        self.assertNotEqual(giver['instance'], old_giver['instance'])
        c.rpc(40, body([fresh[-1] + (1 << 32)]))
        c.rpc(40, I(0))
        self.assertEqual(c.rpc(60), old)
        before = json.loads(path.read_text())
        response = c.rpc(77, Q(giver['instance']))
        self.assertEqual(response[:1], b'\1')
        after = json.loads(path.read_text())
        self.assertEqual(after['Facts'], before['Facts'])
        self.assertEqual(after['Revision'], before['Revision'] + 1)
        self.assertNotEqual(after['Player']['StoryPlaces']['dead_horse']['CellId'], a)
        self.assertEqual(c.rpc(60), response[1:])
        # Returning to the original region must also use RPC 40, with a fresh giver identity.
        returning, = self.locations_by_cell(c.rpc(40, I(1) + Q(a)))['quests']
        self.assertNotEqual(returning['instance'], old_giver['instance'])
        self.assertEqual(c.rpc(77, Q(returning['instance']))[:1], b'\1')
        self.assertEqual(json.loads(path.read_text())['Player']['StoryPlaces']['dead_horse']['CellId'], a)

    def test_relocation_keeps_nearby_cells_during_partial_walk_updates(self):
        server, c, path, env, old, a, b, control = self.relocation_fixture('dead_horse', {94: -3})
        body = lambda ids: I(len(ids)) + b''.join(Q(i) for i in ids)
        # Bootstrap supplies a grid, but the first map reply can be only one column.
        grid = {}
        for x in range(3):
            for y in range(3):
                cell = b + (x * 3 + y) * (1 << 32)
                grid[x, y] = cell
                control['origins'][cell] = (11 + (y - 1) * 450 / 110540, 20 + (x - 1) * 450 / 109000)
        c.rpc(88, body(list(grid.values())))
        first_column = [grid[0, y] for y in range(3)]
        giver, = self.locations_by_cell(c.rpc(40, body(first_column)))['quests']
        self.assertEqual(c.rpc(60), old)
        # New neighboring columns and empty refreshes must retain this already-served destination.
        for x in (1, 2):
            newest, = self.locations_by_cell(c.rpc(40, body([grid[x, y] for y in range(3)])))['quests']
            self.assertNotEqual(newest['instance'], giver['instance'])
            c.rpc(40, I(0))
        # Even after restart, a still-nearest older giver remains a valid selection.
        server.stop()
        c = self.client(self.start('test-relocation', env))
        c.rpc(88, body(list(grid.values())))
        self.assertEqual(c.rpc(77, Q(giver['instance']))[:1], b'\1')
        moved = json.loads(path.read_text())['Player']['StoryPlaces']
        self.assertNotEqual(moved['dead_horse']['CellId'], a)
        self.assertEqual(moved['relocation-root-145']['Id'], giver['place'])
        # Continue walking with single-cell updates until the first destination is out of range.
        for step in range(1, 9):
            cell = b + (20 + step) * (1 << 32)
            control['origins'][cell] = (11, 20 + step * 450 / 109000)
            self.assertEqual(len(self.locations_by_cell(c.rpc(40, body([cell])))['quests']), 1)
        places = json.loads(path.read_text())['Player']['StoryPlaces']
        self.assertNotEqual(places['relocation-145']['Id'], giver['place'])
        # The same walk has not silently relocated the actual goal again.
        self.assertEqual(places['dead_horse'], moved['dead_horse'])
        before = path.read_bytes()
        self.assertEqual(c.rpc(77, Q(giver['instance'])), b'\0' * 13)
        self.assertEqual(path.read_bytes(), before)
        self.assertTrue(all(p['Id'] != giver['place'] for k, p in places.items() if k.startswith('relocation-145')))

    def test_relocation_diagnostics_distinguish_missing_and_retired_offers(self):
        server, c, path, _, old, a, b, _ = self.relocation_fixture('dead_horse', {94: -3})
        retired, = self.locations_by_cell(c.rpc(40, I(1) + Q(a)))['quests']
        current, = self.locations_by_cell(c.rpc(40, I(1) + Q(b)))['quests']
        before = path.read_bytes()
        cases = ((-1, 'client-missing-giver'), (0, 'client-zero-giver'),
                 (retired['instance'], 'retired-map-offer'),
                 (Reader(old).quest()['nodes'][0]['instance'], 'active-goal-instance'),
                 (0x6000000000000042, 'unknown-generated-giver'), (123, 'other-instance'))
        for instance, kind in cases:
            self.assertEqual(c.rpc(77, Q(instance)), b'\0' * 13)
            self.assertEqual(path.read_bytes(), before)
        # Diagnostics neither broaden admission nor affect a valid move or its reply.
        self.assertEqual(c.rpc(77, Q(current['instance']))[:1], b'\1')
        server.stop()
        log = server.logpath.read_text()
        for _, kind in cases:
            self.assertIn(f'Relocation lookup kind={kind} movable=1 offers=1 inArea=1', log)
        for offer in (retired, current):
            self.assertNotIn(str(offer['instance']), log)
            self.assertNotIn(offer['place'], log)

    def test_relocation_refusals_leave_entire_profile_unchanged(self):
        server, c, path, _, old, a, b, control = self.relocation_fixture(facts={100: 4, 53: 1}, started=[149])
        giver, = [g for g in self.locations_by_cell(c.rpc(40, I(1) + Q(a)))['quests'] if g['node'] == 11491]
        before = path.read_bytes()
        for data in (Q(-1), Q(Reader(old).quest()['nodes'][0]['instance']), Q(1) + b'\0'):
            self.assertEqual(c.rpc(77, data), b'\0' * 13)
            self.assertEqual(path.read_bytes(), before)
        c.rpc(88, I(1) + Q(b))
        self.assertEqual(c.rpc(77, Q(giver['instance'])), b'\0' * 13)  # stale giver, not served here
        self.assertEqual(path.read_bytes(), before)
        giver, = [g for g in self.locations_by_cell(c.rpc(40, I(1) + Q(b)))['quests'] if g['node'] == 11491]
        before = path.read_bytes()
        control['radii'] = (100,)  # A destination giver fits, but the active goal's band does not.
        self.assertEqual(c.rpc(77, Q(giver['instance'])), b'\0' * 13)
        self.assertEqual(path.read_bytes(), before)
        control['radii'] = ()
        self.assertEqual(c.rpc(77, Q(giver['instance'])), b'\0' * 13)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(c.rpc(60), old)  # The same socket remains usable after every refusal.
        other = self.client(server, identity=identity_of('other-relocation-player'))
        other.rpc(3); other.rpc(3)
        other_path = self.profile_file('other-relocation-player')
        other_before = other_path.read_bytes()
        other.rpc(88, I(1) + Q(b))
        self.assertEqual(other.rpc(77, Q(giver['instance'])), b'\0' * 13)
        self.assertEqual(other_path.read_bytes(), other_before)
        self.assertEqual(path.read_bytes(), before)

    def test_relocation_moves_goal_inside_the_estimated_area(self):
        # Only the client checks the 1000 m distance; a goal in a loaded cell must still move.
        _, c, _, _, old, a, _, _ = self.relocation_fixture('griffin', {94: -3})
        giver, = self.locations_by_cell(c.rpc(40, I(1) + Q(a)))['quests']
        response = c.rpc(77, Q(giver['instance']))
        self.assertEqual(response[:1], b'\1')
        self.assertNotEqual(Reader(response[1:]).quest()['nodes'][0]['place'], Reader(old).quest()['nodes'][0]['place'])

    def test_relocation_places_goals_around_the_gps_fix(self):
        # With the GPS collector (RPC 2001) reporting, the band is measured from the player, not the area.
        _, c, path, _, _, _, b, control = self.relocation_fixture('griffin', {94: -3})
        control['radii'] = tuple(range(300, 2600, 100))
        c.rpc(88, I(1) + Q(b))
        giver, = self.locations_by_cell(c.rpc(40, I(1) + Q(b)))['quests']
        now = int(time.time() * 1000)
        epoch = c.rpc(2001, struct.pack('>BBHIqq', 1, 1, 0, 7, 100000, now))[4:20]
        lat = 11 + 1500 / 110540  # 1.5 km north of the cell's centre: the two bands cannot overlap
        fix = struct.pack('>qqddfI', now, 100000, lat, 20.0, 5, 5)
        c.rpc(2001, struct.pack('>BBH16sqI', 1, 2, 0, epoch, 1, 1) + fix)
        self.assertEqual(c.rpc(77, Q(giver['instance']))[:1], b'\1')
        goal = json.loads(path.read_text())['Player']['StoryPlaces']['griffin']
        metres = math.hypot((goal['Lat'] - lat) * 110540, (goal['Lng'] - 20) * 111320 * math.cos(math.radians(11)))
        self.assertTrue(250 <= metres <= 700, metres)

    def test_relocation_moves_joint_venture_anchors_and_only_unfinished_goals(self):
        _, c, path, _, old, a, b, _ = self.relocation_fixture('jv_gifts', {107: 4}, done=['heart'])
        c.rpc(88, I(1) + Q(b))
        giver, = self.locations_by_cell(c.rpc(40, I(1) + Q(b)))['quests']
        before = json.loads(path.read_text())
        response = c.rpc(77, Q(giver['instance']))
        self.assertEqual(response[:1], b'\1')
        self.assertEqual(c.rpc(60), response[1:])
        self.assertEqual({n['node'] for n in Reader(response[1:]).quest()['nodes']}, {9289, 9290, 9292})
        after = json.loads(path.read_text())
        self.assertEqual(after['Player']['StoryDone'], ['heart'])
        for key in ('obelisk', 'crown', 'sword', 'gargoyle'):
            self.assertEqual(after['Player']['StoryPlaces'][key]['CellId'], b)
            self.assertNotEqual(after['Player']['StoryPlaces'][key]['Id'], before['Player']['StoryPlaces'][key]['Id'])

    def test_relocation_moves_prologue_goal_and_preserves_hunt_mode(self):
        _, c, _, _, _, a, b, _ = self.relocation_fixture('griffin', {94: -3})
        c.rpc(88, I(1) + Q(b))
        giver, = self.locations_by_cell(c.rpc(40, I(1) + Q(b)))['quests']
        response = c.rpc(77, Q(giver['instance']))
        self.assertEqual(response[:1], b'\1')
        self.assertEqual(c.rpc(60), response[1:])
        goal, = Reader(response[1:]).quest()['nodes']
        self.assertEqual((goal['instance'], goal['mode']), (GRIFFIN, 4))

    def test_relocation_preserves_near_and_return_to_giver_relationships(self):
        server, c, path, env, _, a, b, _ = self.relocation_fixture(facts={100: 4, 53: 2}, started=[149])
        c.rpc(88, I(1) + Q(b))
        giver, = [g for g in self.locations_by_cell(c.rpc(40, I(1) + Q(b)))['quests'] if g['node'] == 11491]
        response = c.rpc(77, Q(giver['instance']))
        self.assertEqual(response[:1], b'\1')
        self.assertEqual(c.rpc(60), response[1:])
        places = json.loads(path.read_text())['Player']['StoryPlaces']
        first, second = (places[f's01mq01_cocoon_{k}'] for k in (1, 2))
        distance = math.hypot((first['Lat'] - second['Lat']) * 110540,
                              (first['Lng'] - second['Lng']) * 111320 * math.cos(math.radians(11)))
        self.assertTrue(39 <= distance <= 151)
        # Next stage returns to the relocated giver, never to the old anchor.
        c.rpc(78, I(1) + I(53) + I(3))
        goal, = Reader(c.rpc(60)).quest()['nodes']
        self.assertEqual(goal['place'], giver['place'])
        server.stop(); c = self.client(self.start('test-relocation', env))
        self.assertEqual(Reader(c.rpc(60)).quest()['nodes'][0]['place'], giver['place'])

    def test_equipment_is_owned_equipped_bought_and_worn(self):
        # GetEquipment (9): [int n][sword ids][int n][armour ids][EquippedArmor][EquippedSword]. A new profile has
        # the Witcher's steel sword (7), the Kaer Morhen steel sword (13) and Adept's Armor (7).
        server, c = self.reconstructed('test-gear')
        def equipment():
            r = Reader(c.rpc(9))
            return {'swords': r.ints(), 'armors': r.ints(), 'armor': r.integer(), 'sword': r.integer()}
        self.assertEqual(equipment(), {'swords': [7, 13], 'armors': [7], 'armor': 7, 'sword': 7})
        self.assertEqual(decode_batch(c.rpc(115))[9], c.rpc(9))
        # Only owned items can be equipped (IntResponse [byte][int id]); the choice is kept.
        self.assertEqual(c.rpc(55, I(13)), b'\1' + I(13))
        self.assertEqual(c.rpc(11, I(6)), b'\0' + I(7))
        self.assertEqual(c.rpc(55, I(14)), b'\0' + I(13))
        self.assertEqual(equipment()['sword'], 13)
        # The shop sells equipment once (tab Equipment); a bought armour can be worn.
        with urllib.request.urlopen(f'http://127.0.0.1:{server.http}/staticdata', timeout=1) as response:
            data = json.loads(gzip.decompress(response.read()))
        tabs = {r['shop_bundle_id']: (r['layout_group_name_main_category'], r['layout_group_name_sub_category'])
                for r in data['shop_bundles_layout_group_name_categories']}
        bundles = {r['id']: r for r in data['shop_bundles']}
        feline = 3004
        self.assertEqual((tabs[feline], bundles[feline]['gold_price'], bundles[feline]['one_time']), (('Equipment', 'Armors'), 3400, 1))
        self.assertEqual(tabs[4008], ('Equipment', 'Silver_Swords'))
        path = self.profile_file('test-gear')
        server.stop()
        profile = json.loads(path.read_text()); profile['Player']['Gold'] = 5000; path.write_text(json.dumps(profile))
        server = self.start('test-gear', self.RECONSTRUCTED); c = self.client(server)
        bought = Reader(c.rpc(75, I(feline) + Q(1)))
        self.assertEqual((bought.byte(), bought.integer(), bought.integer()), (1, feline, 1600))
        self.assertEqual(Reader(c.rpc(75, I(feline) + Q(2))).byte(), 0)          # once only
        self.assertEqual(c.rpc(11, I(4)), b'\1' + I(4))
        self.assertEqual(equipment(), {'swords': [7, 13], 'armors': [7, 4], 'armor': 4, 'sword': 13})
        # The Kaer Morhen steel sword adds 10 % to the kill experience, reported as BoostedExp.
        r = Reader(c.rpc(111, I(16) + I(1) + I(16925168) + I(52406374))); self.assertEqual(r.byte(), 1)
        group, = self.summoned_groups(r)
        self.assertEqual(c.rpc(113, Q(group['monsters'][0][1])), b'\1')
        won = self.combat_end(Reader(c.rpc(114, b'\1' + I(13) + I(0) * 13 + b'\0')))
        self.assertEqual((won['base'], won['boosted']), (100, 10))

    def test_item_effects_keep_their_power_in_the_client_descriptions(self):
        # Effects.GetEffect (0x194E178) builds a Dummy with power 0 for these ids, so an item that used one read "0%" in its
        # description: Wolven armor said "Grants a 0% chance ... extra alchemy ingredients". 70 and 71 build a Dummy that keeps it.
        powerless = {0, *range(42, 56), 60, 62, 63, 66, 68, 73, 77, 78, 79, 81}
        with urllib.request.urlopen(f'http://127.0.0.1:{self.server.http}/staticdata', timeout=1) as response:
            data = json.loads(gzip.decompress(response.read()))
        combat = {row['id'] for row in data['effects'] if row['effect_type_id'] == 1}  # utility effects go to GetUtilityEffect
        for table in ('armor_to_effect', 'sword_to_effect', 'potion_to_effect', 'oil_to_effect', 'skill_to_effect'):
            for row in data[table]:
                with self.subTest(table=table, item=row['item_id'], effect=row['effect_id']):
                    self.assertIn(row['effect_id'], {r['id'] for r in data['effects']})
                    self.assertFalse(row['effect_id'] in combat and row['effect_id'] in powerless)
        wolven = [(row['effect_id'], row['power']) for row in data['armor_to_effect'] if row['item_id'] == 3]
        self.assertEqual(wolven, [(71, 50)])

    def test_dashboard_tuning_sets_fight_rewards_and_herbs(self):
        # world/tuning.json is what the dashboard saves; the server reads it again about once a second, here it is there from the start
        folder = self.directory / 'tuning-world'
        folder.mkdir()
        (folder / 'world.json').write_text('{"schemaVersion":1,"monsterSlotsPerCell":18}')
        (folder / 'tuning.json').write_text(json.dumps({'schemaVersion': 1, 'values': {
            'exp.percent': 300, 'loot.percent': 0, 'herbs.perCell': 2, 'herbs.respawnMinutes': 5}}))
        cells = [0x4704440000000000 + (k << 40) for k in range(3)]
        url, _ = self.playable_service(lambda ids, epoch: {i: {'center': [10.0, 20.0], 'places': [
            {'id': f'lab-{int(i):016x}-{epoch}-{n}', 'lat': 10.0 + n / 1000, 'lng': 20.0, 'biomes': [10], 'kind': 'path'}
            for n in range(24)]} for i in ids})
        server = self.start('test-tuning', dict(self.RECONSTRUCTED, Playable__Url=url, World__Directory=str(folder)))
        c = self.client(server)
        c.rpc(78, I(1) + I(10145) + I(1))
        world = self.locations_by_cell(c.rpc(40, I(3) + b''.join(Q(cell) for cell in cells)))
        self.assertEqual(len(world['herbs']), 2 * 3)                         # two a cell, not four
        target = world['monsters'][0]
        difficulty = next(s['difficulty'] for s in WORLD['species'] if s['monster_id'] == target['monster'])
        self.assertEqual(c.rpc(41, Q(target['instance'])), b'\1')
        won = self.combat_end(Reader(c.rpc(8, b'\1' + I(13) + I(0) * 13 + b'\0')))
        self.assertEqual((won['base'], won['first'], won['loot']), (3 * {1: 100, 2: 250, 3: 600}[difficulty], 300, []))
        got = Reader(c.rpc(19, Q(world['herbs'][0]['instance'])))
        self.assertEqual(got.byte(), 1)
        got.ints()
        self.assertAlmostEqual(got.integer(), time.time() + 300, delta=5)    # five minutes, not an hour

    def test_difficulty_tiers_give_story_scale_hp_and_damage(self):
        # PrepareFightNode.PrepareMechanic defaults: enemy HP = player_attack_count x SwordBasicDamage (75), enemy
        # damage = 2400 / enemy_attack_count. The tiers follow the client's story fights (EVIDENCE.md §6b).
        with urllib.request.urlopen(f'http://127.0.0.1:{self.server.http}/staticdata', timeout=1) as response:
            data = json.loads(gzip.decompress(response.read()))
        tiers = {row['id']: row for row in data['difficulties']}
        self.assertEqual(sorted(tiers), list(range(1, 9)))
        self.assertEqual({row['slug'] for row in tiers.values()}, {f'tier_{n}' for n in range(1, 9)})
        scale = {n: (row['player_attack_count'] * 75, 2400 / row['enemy_attack_count']) for n, row in tiers.items()}
        self.assertEqual(scale, {1: (3000, 300), 2: (5550, 400), 3: (11025, 800), 4: (7950, 800),
                                 5: (11025, 800), 6: (14550, 1200), 7: (16875, 1200), 8: (24525, 1200)})

    def test_world_monster_difficulty_uses_original_skull_assets_and_keeps_story_only_rows(self):
        with urllib.request.urlopen(f'http://127.0.0.1:{self.server.http}/staticdata', timeout=1) as response:
            data = json.loads(gzip.decompress(response.read()))
        monsters = {row['id']: row for row in data['monsters']}
        tiers = {row['id']: row for row in data['difficulties']}
        # Original 1.1.116 assets: EASY/no icon, MEDIUM/skull_03, HARD/skull_02, EXTREME/skull_01.
        # The selected tiers' numerical defaults are an explicit reconstruction policy.
        expected = {0: ('tier_1', 3000, 300), 1: ('tier_4', 7950, 800),
                    2: ('tier_6', 14550, 1200), 3: ('tier_8', 24525, 1200)}
        for species in WORLD['species']:
            with self.subTest(slug=species['slug']):
                tier = tiers[monsters[species['monster_id']]['difficulty']]
                self.assertEqual((tier['slug'], tier['player_attack_count'] * 75,
                                  2400 / tier['enemy_attack_count']), expected[species['skulls']])
        # Shared world/story species receive the corrected display. Story-only actors keep their fields;
        # client graph EnemyMaxHp/EnemyDamage overrides are independent of these static rows.
        world_ids = {species['monster_id'] for species in WORLD['species']}
        for row in SEASON1['monsters']:
            if row['id'] not in world_ids:
                self.assertEqual(monsters[row['id']]['difficulty'], row['difficulty'])
        self.assertEqual(monsters[9]['difficulty'], 4)  # Griffin's previous static tier was 1, metadata tier 3.

    def test_season1_rows_follow_the_client_quest_rules(self):
        # StoryGraph rules (BuildQuestMap, FillAvailableNodes, EvaluateSimpleExpression) over the served rows.
        with urllib.request.urlopen(f'http://127.0.0.1:{self.server.http}/staticdata', timeout=1) as response:
            data = json.loads(gzip.decompress(response.read()))
        quests = {q['id']: q for q in data['quests'] if q['id'] in SEASON1_QUESTS}
        self.assertEqual(len(quests), 12)
        for quest in quests.values():
            self.assertEqual(quest['season_id'], 0)
            self.assertIn({'from_quest_id': 144, 'to_quest_id': quest['id']}, data['quest_edges'])
        simple = re.compile(r'^(f\d+(<=|>=|<|>|=)-?\d+)?$')
        for row in list(quests.values()) + data['quest_nodes']:
            self.assertRegex(row['activation_criteria'], simple)
        nodes = {n['id']: n for n in data['quest_nodes'] if n['quest_id'] in SEASON1_QUESTS}
        outputs = {o['id']: o for o in data['quest_node_outputs'] if o['quest_node_id'] in nodes}
        self.assertEqual(len(nodes), len(SEASON1['nodes']))
        incoming = {e['to_quest_node_id'] for e in data['quest_node_edges'] if e['from_quest_node_output_id'] in outputs}
        for e in data['quest_node_edges']:
            if e['from_quest_node_output_id'] in outputs:
                self.assertEqual(nodes[outputs[e['from_quest_node_output_id']]['quest_node_id']]['quest_id'],
                                 nodes[e['to_quest_node_id']]['quest_id'])
        by_key = {n['key']: n for n in SEASON1['nodes']}
        for quest in quests:
            roots = [n for n in nodes.values() if n['quest_id'] == quest and n['id'] not in incoming]
            self.assertEqual(len(roots), 1, quest)
            root = by_key[roots[0]['name']]
            self.assertIn(root['kind'], ('giver', 'queued'))
            self.assertTrue(any(o['endpoint'] for o in outputs.values() if nodes[o['quest_node_id']]['quest_id'] == quest))
        # Givers stand well inside the client's giver hide distance (350 m on LAB 16).
        for node in SEASON1['nodes']:
            if node['kind'] == 'giver':
                self.assertLessEqual(node['max'], 320, node['key'])
        # Every reward refers to rows the client has: bestiary monsters, items, modifiers.
        monsters = {m['id']: m for m in data['monsters']}
        vulnerable = {v['monster_id'] for v in data['monster_vulnerabilities']}
        for output in SEASON1['outputs']:
            for monster in output['kills']:
                self.assertIn(int(monster), monsters)
                self.assertIn(int(monster), vulnerable)
            for kind, items in output['items'].items():
                ids = {row['id'] for row in data[kind]}
                self.assertLessEqual({int(i) for i in items}, ids)
        for row in SEASON1['monsters']:
            self.assertEqual(monsters[row['id']]['slug'], row['slug'])
        self.assertEqual([m['id'] for m in data['player_modifiers']], [1, 2, 3, 4, 5, 6, 7, 8, 901, 902])  # 901-902: debug tools

    def test_season1_original_output_alias_rows_preserve_donor_rows_and_edges(self):
        with urllib.request.urlopen(f'http://127.0.0.1:{self.server.http}/staticdata', timeout=1) as response:
            data = json.loads(gzip.decompress(response.read()))
        rows = data['quest_node_outputs']
        # Native BuildNodeQuestOutputMap uses Dictionary.Add(id); duplicate IDs would fail at preload.
        self.assertEqual(len(rows), len({row['id'] for row in rows}))
        by_id = {row['id']: row for row in rows}
        canonical = {o['id']: {'id': o['id'], 'quest_node_id': o['node'], 'name': o['name'],
                               'endpoint': int(o['endpoint'])} for o in SEASON1['outputs']}
        for output_id, row in canonical.items():
            self.assertEqual(by_id[output_id], row)
        expected = [
            {'id': 20001, 'quest_node_id': 18160, 'name': 'mushroom_start', 'endpoint': 0},
            {'id': 20002, 'quest_node_id': 403, 'name': 'mushroom_start', 'endpoint': 0},
        ]
        story_nodes = {n['id'] for n in SEASON1['nodes']}
        self.assertEqual([row for row in rows if row['quest_node_id'] in story_nodes
                          and row['id'] not in canonical], expected)
        # BuildQuestNodeMap groups every row by node; QuestEndRequestNode selects the literal name.
        for alias, output_id in zip(expected, (1216, 1234)):
            group = [row for row in rows if row['quest_node_id'] == alias['quest_node_id']]
            for name in ('mushroom_start', 'mushroom_timer_start'):
                matches = [row for row in group if row['name'] == name]
                self.assertEqual(len(matches), 1)
                self.assertEqual(matches[0]['endpoint'], canonical[output_id]['endpoint'])
        # Existing root edges retain their canonical IDs; the aliases add no alternate topology.
        edges = []
        for quest in SEASON1['quests']:
            nodes = [n for n in SEASON1['nodes'] if n['quest'] == quest['id']]
            root = next((n for n in nodes if n['kind'] == 'giver'), None)
            if root is None:
                root = next((n for n in nodes if n['kind'] == 'queued'), None)
            if root is not None:
                first = next(o for o in SEASON1['outputs'] if o['node'] == root['id'])
                edges.extend({'from_quest_node_output_id': first['id'], 'to_quest_node_id': n['id']}
                             for n in nodes if n['id'] != root['id'])
        self.assertEqual([edge for edge in data['quest_node_edges'] if edge['to_quest_node_id'] in story_nodes], edges)

    def test_season1_original_output_alias_rpc_replay_and_client_rollback(self):
        for node_id, output_id in ((18160, 1216), (403, 1234)):
            for first_name, second_name in (('mushroom_start', 'mushroom_timer_start'),
                                            ('mushroom_timer_start', 'mushroom_start')):
                with self.subTest(node=node_id, first=first_name):
                    name = f'test-output-alias-{node_id}-{first_name}'
                    server = self.start(name, self.RECONSTRUCTED)
                    c = self.client(server); c.rpc(3); c.rpc(3)
                    server.stop()
                    path = self.profile_file(name)
                    profile = json.loads(path.read_text())
                    profile['QuestStage'], profile['Facts'] = 'jv_done', {'100': 4}
                    profile['Player']['Story'] = {'Active': [], 'Started': [], 'Finished': [], 'Outputs': [],
                                                  'Tracked': None, 'Reached': {}, 'Clock': 0}
                    path.write_text(json.dumps(profile))
                    server = self.start(name, self.RECONSTRUCTED); c = self.client(server)
                    node = next(n for n in SEASON1['nodes'] if n['id'] == node_id)
                    other = next(n for n in SEASON1['nodes'] if n['quest'] != node['quest'] and n['kind'] == 'giver')
                    # An original spelling at another known node remains facts-only, never a global alias.
                    result = Reader(c.rpc(57, self.completion_body({70001: 7}, instance=other['instance'],
                                                                  output='mushroom_start'))).end_graph()
                    self.assert_zero_completion_rewards(result)
                    unknown = json.loads(path.read_text())
                    self.assertEqual(unknown['Facts']['70001'], 7)
                    self.assertEqual(unknown['Player']['Story'], profile['Player']['Story'])
                    result = Reader(c.rpc(57, self.completion_body({}, instance=node['instance'],
                                                                  output=first_name))).end_graph()
                    self.assertTrue(result['success'])
                    self.assert_zero_completion_rewards(result)
                    after = json.loads(path.read_text())
                    story = after['Player']['Story']
                    self.assertEqual(story['Started'], [node['quest']])
                    self.assertEqual(story['Finished'], [])
                    self.assertEqual(story['Outputs'], [output_id])
                    self.assertEqual(list(story['Reached']), [str(output_id)])
                    for field in ('Exp', 'Gold', 'Items', 'Kills'):
                        self.assertEqual(after['Player'][field], unknown['Player'][field])
                    # New request IDs, both spellings and a process restart all use the same saved receipt.
                    # Recognized story RPCs already increment the profile revision on replay. Compare the
                    # actual saved state, including the first-reached timestamp, independently of that counter.
                    saved = {key: value for key, value in after.items() if key != 'Revision'}
                    for spelling in (second_name, first_name, second_name):
                        result = Reader(c.rpc(57, self.completion_body({}, instance=node['instance'],
                                                                      output=spelling))).end_graph()
                        self.assert_zero_completion_rewards(result)
                        replayed = json.loads(path.read_text())
                        self.assertEqual({key: value for key, value in replayed.items() if key != 'Revision'}, saved)
                    server.stop()
                    server = self.start(name, self.RECONSTRUCTED); c = self.client(server)
                    result = Reader(c.rpc(57, self.completion_body({}, instance=node['instance'],
                                                                  output=second_name))).end_graph()
                    self.assert_zero_completion_rewards(result)
                    replayed = json.loads(path.read_text())
                    self.assertEqual({key: value for key, value in replayed.items() if key != 'Revision'}, saved)
                    server.stop()

    def test_season1_plays_through_every_quest(self):
        # The whole season on one profile, in the order of season1_quests.py: each quest's giver (or queued node)
        # is offered, every step of its walk-through gives the published reward once and shows the nodes the
        # walk-through expects, and the quest ends finished in RPC 70 with nothing of it left on the map.
        origin = (10.0, 20.0)
        cos = math.cos(math.radians(origin[0]))
        places = [{'id': f'lab-test-{r}-{k}', 'lat': origin[0] + math.sin(k * math.pi / 4) * r / 110540.0,
                   'lng': origin[1] + math.cos(k * math.pi / 4) * r / (111320.0 * cos), 'biomes': [4], 'kind': 'path'}
                  for r in (100, 150, 200, 250, 300, 400, 500, 600, 700) for k in range(8)]
        url, _ = self.playable_service(lambda ids, epoch: {
            i: {'center': list(origin), 'places': places if n == 0 else []} for n, i in enumerate(ids)})
        env = dict(self.RECONSTRUCTED, Playable__Url=url)
        server = self.start('test-season1-all', env)
        c = self.client(server)
        c.rpc(3); c.rpc(3)
        server.stop()
        path = self.profile_file('test-season1-all')
        profile = json.loads(path.read_text())
        profile['QuestStage'] = 'jv_done'
        profile['Facts'] = {'100': 4}
        path.write_text(json.dumps(profile))
        server = self.start('test-season1-all', env)
        c = self.client(server)
        cells = [0x4704440000000000 + (k << 40) for k in range(9)]
        request = I(9) + b''.join(Q(cell) for cell in cells)
        c.rpc(88, request)

        nodes = {n['id']: n for n in SEASON1['nodes']}
        by_key = {n['key']: n for n in SEASON1['nodes']}
        outputs = {(o['node'], o['name']): o for o in SEASON1['outputs']}
        served = Reader(c.rpc(60)).quest()['nodes']
        reached, finished = set(), [144, 145, 146]
        exp = server.state()['player']['exp']
        # An order the prerequisites allow (the maintainer's list, 10 October 2026): The Sins of Our Fathers before The Great
        # Mushrooming, Intruder after the five main quests; Monster Slayer opens on the server's troll trigger (test_season1
        # plays the fights; here the fact comes as the game would learn it).
        order = ['149', '104', '148', '150', '159', '147', '158', '161', '160', '152', '153', '154']
        self.assertEqual(sorted(order), sorted(SEASON1['walks']))
        for quest_id in order:
            steps, quest = SEASON1['walks'][quest_id], int(quest_id)
            if quest == 161:
                self.assertEqual(c.rpc(78, I(2) + I(1010) + I(1)), b'\1')
            root = next((n for n in SEASON1['nodes'] if n['quest'] == quest and n['kind'] == 'giver'), None)
            givers = {g['node']: g for g in self.locations_by_cell(c.rpc(40, request))['quests']}
            if root is not None:
                self.assertIn(root['id'], givers, f'quest {quest} is not offered')
            for step in steps:
                with self.subTest(quest=quest, step=step[:2]):
                    if step[0] == 'wait':
                        with urllib.request.urlopen(urllib.request.Request(
                                f'http://127.0.0.1:{server.http}/prototype/story/clock?add={step[1]}&profile={server.profile_id()}',
                                method='POST'), timeout=1):
                            pass
                        continue
                    if step[0] is None:
                        served = Reader(c.rpc(60)).quest()['nodes']
                    else:
                        node = by_key[step[0]]
                        if node['kind'] == 'giver':
                            instance = givers[node['id']]['instance']
                        elif node['kind'] == 'button':  # a journal button sends its graph's instance; without one, none
                            instance = 0 if node['instance'] == 5124760000000000000 + node['id'] else node['instance']
                        else:
                            instance = next(n['instance'] for n in served if n['node'] == node['id'])
                        facts = {int(k): v for k, v in step[2].items()}
                        result = Reader(c.rpc(57, self.completion_body(facts, instance=instance, output=step[1]))).end_graph()
                        output = outputs[(node['id'], step[1])]
                        first = output['id'] not in reached
                        reached.add(output['id'])
                        self.assertEqual((result['exp'], result['gold']),
                                         (output['exp'], output['gold']) if first else (0, 0))
                        self.assertEqual(result['bestiary'], {int(k): v for k, v in output['kills'].items()} if first else {})
                        for kind in ('potions', 'oils'):
                            self.assertEqual(result[kind], {int(k): v for k, v in output['items'].get(kind, {}).items()} if first else {})
                        for kind in ('armors', 'swords'):   # id lists
                            self.assertEqual(result[kind], [int(k) for k in output['items'].get(kind, {})] if first else [])
                        exp += result['exp']
                        served = result['nodes']
                        if output['endpoint']:
                            finished.append(quest)
                    shown = sorted({nodes[n['node']]['key'] for n in served if nodes.get(n['node'], {}).get('quest') == quest})
                    self.assertEqual(shown, sorted(step[3]))
            status = decode_finished_quests(decode_batch(c.rpc(115))[70])
            self.assertEqual(status['finished'], finished, f'quest {quest} did not finish')
            self.assertNotIn(quest, status['active'])
        self.assertEqual(len(finished), 3 + 12)
        self.assertEqual(server.state()['player']['exp'], exp)
        # Every step was recorded, journal buttons sent without an instance too (s01hq02 has two that end with "notebook").
        self.assertLessEqual(reached, set(server.state()['player']['story']['outputs']))
        # The quest rewards joined the equipment: Hermit's Armor (8) and Dawnbringer (17).
        gear = server.state()['player']['equipment']
        self.assertIn(8, gear['armors'])
        self.assertIn(17, gear['swords'])
        # Every ending saved its quest's completion fact (177-188), and fact 31 counts the five main quests.
        facts = server.state()['facts']
        self.assertEqual({f: facts.get(str(f)) for f in range(177, 189)}, {f: 1 for f in range(177, 189)})
        self.assertEqual(facts['31'], 5)
        # Nothing is offered or left on the map once the season is over.
        self.assertEqual(self.locations_by_cell(c.rpc(40, request))['quests'], [])
        self.assertEqual(Reader(c.rpc(60)).quest()['nodes'], [])

    def test_batch_methods_answer_standalone_with_batch_bytes(self):
        for server, extra in ((self.server, ()), (self.reconstructed()[0], (112,))):
            c = self.client(server)
            batch = decode_batch(c.rpc(115))
            for method in (6, 7, 9, 24, 56, 63, 69, 70, 117) + extra:
                with self.subTest(method=method):
                    self.assertEqual(c.rpc(method), batch[method])

    def test_reconstructed_skill_purchase_checks_level_points_and_persists(self):
        server, c = self.reconstructed()
        with urllib.request.urlopen(f'http://127.0.0.1:{server.http}/staticdata', timeout=1) as response:
            data = json.loads(gzip.decompress(response.read()))
        slugs = {}
        for row in data['skills']: slugs.setdefault(row['slug'], row)
        aard, muscle = slugs['aard_sign']['id'], slugs['muscle_memory']['id']
        self.assertEqual(c.rpc(64, I(muscle)), b'\0' + I(muscle))  # No points at level 1.
        c.rpc(57, self.completion_body({3: 1}, instance=self.TUT_EXAM, output='exam_end'))
        self.assertEqual(c.rpc(64, I(aard)), b'\0' + I(aard))      # Level 10 gate.
        self.assertEqual(c.rpc(64, I(muscle)), b'\1' + I(muscle))
        self.assertEqual(c.rpc(64, I(muscle)), b'\0' + I(muscle))  # Already owned.
        self.assertEqual(c.rpc(93, I(50)), b'\0' + I(4))           # Client grants are refused.
        server.stop()
        restarted = self.start('test-fresh', self.RECONSTRUCTED)
        skills = Reader(decode_batch(self.client(restarted).rpc(115))[63])
        owned, points = skills.ints(), skills.integer()
        self.assertIn(muscle, owned)
        self.assertEqual(points, 4)

    @staticmethod
    def completion_body(facts=None, instance=THORSTEIN, output='thorstein'):
        if facts is None: facts = {10145: 1, 95: 1, 107: 1, 77: 2, 123: 0, 113: 1}
        return Q(instance) + S(output) + I(len(facts)) + b''.join(I(k) + I(v) for k, v in facts.items())
    def assert_zero_completion_rewards(self, result):
        self.assertEqual((result['exp'], result['gold']), (0, 0))
        for name in ('potions', 'bombs', 'oils', 'lures', 'senses', 'bestiary', 'ingredients', 'expiry'):
            self.assertEqual(result[name], {})
        self.assertEqual(result['armors'], [])
        self.assertEqual(result['swords'], [])
    def test_completion_reader_exact_old_wire_order_and_boundaries(self):
        # Authored nonzero sentinels distinguish fields even though production rewards stay zero.
        location = I(1) + S('synthetic-place') + I(17) + I(23) + I(1) + I(41)
        node = I(1) + Q(901) + I(31) + S('synthetic-place') + S('settings') + S('graph') + I(2)
        rewards = I(51) + I(52) + b''.join(I(1) + I(100+n) + I(200+n) for n in range(7))
        tail = I(1) + I(71) + I(1) + I(81) + I(1) + Q(901) + I(91)
        golden = b'\1' + location + node + rewards + tail
        r = Reader(golden); result = r.end_graph()
        self.assertEqual(r.pos, len(golden))
        self.assertEqual(result['locations'], [('synthetic-place', I(17)+I(23), [41])])
        self.assertEqual(result['nodes'], [dict(instance=901, node=31, place='synthetic-place', settings='settings', graph='graph', mode=2)])
        self.assertEqual((result['exp'], result['gold']), (51, 52))
        for n, name in enumerate(('potions', 'bombs', 'oils', 'lures', 'senses', 'bestiary', 'ingredients')):
            self.assertEqual(result[name], {100+n: 200+n})
        self.assertEqual((result['armors'], result['swords'], result['expiry']), ([71], [81], {901: 91}))
        for cut in range(len(golden)):
            with self.subTest(cut=cut), self.assertRaises((ValueError, UnicodeDecodeError)):
                Reader(golden[:cut]).end_graph()
        with self.assertRaisesRegex(ValueError, 'unconsumed'):
            Reader(golden + b'\0').end_graph()
        # Wrongly appending the whole RPC60 before rewards moves expiry to Exp.
        misplaced = b'\1' + location + node + I(1) + Q(901) + I(91) + rewards + I(1)+I(71)+I(1)+I(81)
        with self.assertRaises(ValueError): Reader(misplaced).end_graph()
        legacy = Reader(b'\1' + bytes(56)).end_graph()
        self.assertEqual((legacy['locations'], legacy['nodes']), ([], []))
        self.assert_zero_completion_rewards(legacy)
    def test_graph_save_rejects_malformed_payload_without_persistence(self):
        valid = self.completion_body()
        prefix = Q(THORSTEIN) + S('thorstein')
        cases = [prefix+I(-1), prefix+I(1025), valid[:-1], valid+b'\0',
                 prefix+I(2)+I(10145)+I(1)+I(10145)+I(1),
                 Q(THORSTEIN)+I(-1), valid[:7]]
        self.client()
        baseline = self.server.state()
        for body in cases:
            with self.subTest(bytes=len(body)):
                c = self.client()
                self.assertTrue(c.unanswered(57, body))                       # no verified refusal: no reply
                self.assertEqual(Reader(c.rpc(59)).facts(), {2: 1})           # the session goes on
                self.assertEqual(self.server.state(), baseline)
                self.assertFalse((self.profile_file('test-alpha')).exists())
        self.assertEqual(Reader(self.client().rpc(60)).quest()['nodes'][0]['instance'], THORSTEIN)
    def test_graph_save_accepts_unknown_identity_merges_and_restores_facts(self):
        c = self.client()
        facts = {901: 5, 902: -3}
        body = self.completion_body(facts, instance=9876543210, output='s00/prolog/encounter_end\nspoof')
        response = c.rpc(57, body)
        state = self.server.state()
        path = self.profile_file('test-alpha'); saved = path.read_bytes()
        decoded = Reader(response).end_graph()
        self.assertTrue(decoded['success'])
        self.assertEqual(Reader(c.rpc(59)).facts(), {2: 1, **facts})
        self.server.log.flush()
        diagnostic_log = self.server.logpath.read_text()
        self.assertIn('instanceId=9876543210', diagnostic_log)
        self.assertIn('outputName=s00/prolog/encounter_end?spoof', diagnostic_log)
        self.assertNotIn('\n      spoof', diagnostic_log)
        self.assertEqual(state['revision'], 1)
        for _ in range(2): self.assertEqual(c.rpc(57, body), response)
        self.assertEqual(self.server.state(), state)
        self.assertEqual(path.read_bytes(), saved)
        self.assert_zero_completion_rewards(Reader(response).end_graph())
        self.server.stop(); restarted = self.start('test-alpha')
        self.assertEqual(self.client(restarted).rpc(57, body), response)
        self.assertEqual(Reader(self.client(restarted).rpc(59)).facts(), {2: 1, **facts})
        self.assertEqual(path.read_bytes(), saved)
        self.assertEqual(restarted.state()['revision'], 1)
    def test_terminal_prewritten_by_setfacts_allows_first_completion(self):
        c = self.client()
        # Three synthetic immediate writes model ordering; these are not captured player facts.
        for key, value in ((113, 1), (10145, 1), (123, 1)):
            self.assertEqual(c.rpc(78, I(2)+I(key)+I(value)), b'\1')
        self.assertEqual(self.server.state()['revision'], 3)
        body = self.completion_body()
        response = c.rpc(57, body)
        self.assertEqual(self.server.state()['revision'], 4)
        self.assertEqual(Reader(response).end_graph()['nodes'][0]['instance'], HORSE)
        saved = (self.profile_file('test-alpha')).read_bytes()
        self.assertEqual(c.rpc(57, body), response)
        self.assertEqual((self.profile_file('test-alpha')).read_bytes(), saved)
        self.assertEqual(self.server.state()['revision'], 4)
    def test_concurrent_duplicate_completions_share_one_saved_revision(self):
        clients = [self.client(), self.client()]; body = self.completion_body()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda c: c.rpc(57, body), clients))
        self.assertEqual(responses[0], responses[1])
        self.assertEqual(self.server.state()['revision'], 1)
        self.assertEqual(len(Reader(responses[0]).end_graph()['nodes']), 1)
    def test_completion_preserves_previous_rpc60_and_batch_bytes(self):
        c = self.client()
        expected = [
            ('8fea850a4b5174628d926c5067becec59236924032325393e29cbff43a7da67b',
             'cb033edf0259a880d300db37ffbe6796ca7d8d1c744a5b010a7b6afe68a0bf09'),
            ('395fead97e90114ba697f1375275fc53cdd24cd0abbe919c0882a3f589284694',
             '0113b9446c9f3e22be8425b127217cb5a54acd16771d9c12f693a5bc062873c7')]
        for phase, hashes in enumerate(expected):
            if phase: response = Reader(c.rpc(57, self.completion_body())).end_graph()
            raw = [c.rpc(60), c.rpc(115)]
            parts = decode_batch(raw[1])
            self.assertEqual(parts.pop(117), b'\1' + I(0))  # Restore only the added Aura response for old digests.
            parts[70] = previous_tracking_payload(parts[70])
            parts[3] = previous_player_name(parts[3])
            parts[60] = previous_thorstein(parts[60])
            previous_batch = I(len(parts)) + b''.join(I(k) + v for k, v in parts.items())
            self.assertEqual(tuple(hashlib.sha256(x).hexdigest() for x in (previous_thorstein(raw[0]), previous_batch)), hashes)
            self.assertEqual(decode_batch(raw[1])[60], raw[0])
            if phase:
                quest = Reader(raw[0]).quest()
                self.assertEqual(response['locations'], quest['locations'])
                self.assertEqual(response['nodes'], quest['nodes'])
                self.assertEqual(len(response['nodes']), 1)
                self.assertNotIn(THORSTEIN, [n['instance'] for n in response['nodes']])
    def test_profiles_are_separate(self):
        c = self.client(); c.rpc(78, I(1) + I(10145) + I(1))
        other = self.start('test-beta'); second = self.client(other)
        self.assertEqual(Reader(second.rpc(59)).facts(), {2: 1})
        self.assertEqual(Reader(second.rpc(60)).quest()['nodes'][0]['instance'], THORSTEIN)
    def test_players_are_devices_until_an_account_takes_their_profile(self):
        # ProfileRegistry: a device plays its guest profile; an account's first login takes over the guest profile
        # of that device and the profile then follows the account; logging out leaves a device a new guest profile.
        d1, d2 = 'SYNTHETIC_DEVICE_ONE', 'SYNTHETIC_DEVICE_TWO'
        def facts(identity):
            c = self.client(identity=identity)
            try: return Reader(c.rpc(59)).facts()
            finally: c.close()
        def set_fact(identity, fact):
            c = self.client(identity=identity)
            c.rpc(78, I(1) + I(fact) + I(1)); c.close()
        set_fact((d1, ''), 90001)                                            # a guest on the first device
        guest1 = self.server.profile_id((d1, ''))
        self.assertEqual(facts((d1, 'SYNTHETIC_ACCOUNT_A')), {2: 1, 90001: 1})   # account A takes it over
        self.assertEqual(self.server.profile_id((d1, 'SYNTHETIC_ACCOUNT_A')), guest1)
        self.assertEqual(facts((d1, '')), {2: 1})                            # logged out: a new guest profile
        set_fact((d1, ''), 90002)
        self.assertEqual(facts((d1, 'SYNTHETIC_ACCOUNT_B')), {2: 1, 90002: 1})   # B takes that one, never A's
        set_fact((d2, ''), 90003)                                            # a guest on the second device
        self.assertEqual(facts((d2, 'SYNTHETIC_ACCOUNT_A')), {2: 1, 90001: 1})   # A plays its own profile there
        self.assertEqual(facts((d2, '')), {2: 1, 90003: 1})                  # and the device keeps its guest
        self.assertEqual(facts((d1, 'SYNTHETIC_ACCOUNT_B')), {2: 1, 90002: 1})
        saved = self.server.get('/prototype/profiles')
        self.assertEqual(len(saved), 3)
        self.assertTrue(all(re.fullmatch(r'p[0-9a-f]{31}', name) for name in saved))
        index = (self.directory / 'profiles' / 'players.json').read_text()
        self.assertFalse([m for m in ('SYNTHETIC_DEVICE_ONE', 'SYNTHETIC_DEVICE_TWO', 'SYNTHETIC_ACCOUNT_A',
                                      'SYNTHETIC_ACCOUNT_B') if m in index])
        # Two players on one server keep their own profiles at the same time.
        first, second = self.client(), self.client(identity=(d2, ''))
        first.rpc(78, I(1) + I(10145) + I(1))
        self.assertEqual(Reader(second.rpc(59)).facts(), {2: 1, 90003: 1})
        self.assertEqual(Reader(first.rpc(59)).facts(), {2: 1, 10145: 1})
    def test_weekly_response_matches_standalone_and_batch_boundaries(self):
        c = self.client()
        standalone = c.rpc(94)
        self.assertEqual(len(standalone), 13)
        r = Reader(standalone)
        self.assertEqual(r.weekly(), {'success': 1, 'last_stamp_date': 0,
                                     'reward_id': 0, 'stamps': []})
        self.assertEqual(r.pos, len(standalone))
        batch = decode_batch(c.rpc(115))
        self.assertEqual(len(batch), 21)
        self.assertEqual(list(batch)[-5:], [94, 43, 56, 117, 122])
        self.assertEqual(batch[94], standalone)
        self.assertEqual(batch[43], b'\1' + I(0))
        self.assertEqual(batch[56], I(0))
    def test_weekly_reader_distinguishes_fields_and_rejects_missing_reward(self):
        # Nonzero golden fixture makes swapped date/reward/count observable.
        suffix = I(43) + b'\1' + I(0) + I(56) + I(0)
        correct = b'\1' + I(20260924) + I(701) + I(2) + I(11) + I(22)
        r = Reader(correct + suffix)
        self.assertEqual(r.weekly(), {'success': 1, 'last_stamp_date': 20260924,
                                     'reward_id': 701, 'stamps': [11, 22]})
        self.assertEqual(r.pos, len(correct))
        self.assertEqual(r.integer(), 43)
        self.assertEqual((r.byte(), r.integer()), (1, 0))
        self.assertEqual((r.integer(), r.integer()), (56, 0))
        self.assertEqual(r.pos, len(r.data))
        # Legacy nine-byte weekly body consumes method43 as count43, then runs out
        # with one byte left. This fixture contains no captured runtime bytes.
        legacy = b'\1' + I(0) + I(0)
        broken = Reader(legacy + suffix)
        with self.assertRaisesRegex(ValueError, 'truncated fixture response'):
            broken.weekly()
        self.assertEqual(len(broken.data) - broken.pos, 1)
    def test_invalid_facts_cannot_change_persistent_state(self):
        c = self.client()
        self.assertEqual(c.rpc(78, I(99) + I(10145) + I(1)), b'\0')
        self.assertEqual(self.server.state()['revision'], 0)
        c2 = self.client()
        self.assertTrue(c2.unanswered(57, Q(THORSTEIN) + S('thorstein') + I(2) + I(10145) + I(1)))
        self.assertEqual(self.server.state()['facts'], {'2': 1})
    def test_unsupported_rpc_and_unauthenticated_session_do_not_receive_success(self):
        c = self.client()
        self.assertTrue(c.unanswered(999999))
        self.assertEqual(Reader(c.rpc(59)).facts(), {2: 1})                 # the same session goes on
        c2 = self.client(auth=False)
        with self.assertRaises(EOFError): c2.rpc(59)
        self.server.stop()
        self.assertIn('Unsupported RPC method=999999', self.server.logpath.read_text())
    def test_malformed_requests_get_their_verified_refusal_and_the_session_goes_on(self):
        c = self.client()
        self.assertEqual(c.rpc(75, I(1)), b'\0' + I(0) + I(0))               # BuyShopBundle: false, bundle 0, gold
        self.assertEqual(c.rpc(75, I(1) + Q(7) + b'\0'), b'\0' + I(0) + I(0))
        self.assertEqual(c.rpc(80, I(1) + Q(7) + b'\0'), b'\0' + I(0))      # GetTransactionStatus: failed lookup
        self.assertEqual(c.rpc(77, Q(1) + b'\0'), b'\0' + I(0) * 3)          # RelocateQuest: false and three lists
        self.assertEqual(Reader(c.rpc(59)).facts(), {2: 1})
        self.assertEqual(self.server.state()['revision'], 0)
    def test_use_oil_potions_acknowledges_only_empty_loadout_without_mutation(self):
        c = self.client()
        before = self.server.state()
        self.assertEqual(c.rpc(89, I(-1) + I(0)), b'\1')
        self.assertEqual(self.server.state(), before)

    def test_use_oil_potions_refuses_selected_or_malformed_loadout(self):
        for payload in (I(0) + I(0), I(1) + I(0), I(-1) + I(1), I(0)):
            with self.subTest(payload_length=len(payload)):
                c = self.client()
                before = self.server.state()
                self.assertEqual(c.rpc(89, payload), b'\0')                  # BooleanResponse refusal
                c.close()
                self.assertEqual(self.server.state(), before)
    def test_auth_identifiers_are_not_logged_or_saved(self):
        self.client().rpc(78, I(2) + I(900001) + I(42))
        self.assertEqual((self.profile_file('test-alpha')).stat().st_mode & 0o777, 0o600)
        self.server.stop()
        contents = '\n'.join(p.read_text() for p in self.directory.rglob('*') if p.is_file())
        for marker in MARKERS:
            self.assertNotIn(marker, contents)
            self.assertNotIn(marker.encode().hex().upper(), contents)
    def test_tcp_read_eof_stages_distinguish_empty_and_truncated_frames(self):
        magic = bytes.fromhex('9043284a')
        marker = b'FICTIONAL_BODY_CANARY'
        cases = [
            (b'', [('magic', 4, 0, 'eof')]),
            (magic[:2], [('magic', 4, 2, 'eof')]),
            (magic + b'\3\0', [('magic', 4, 4, 'complete'), ('header', 5, 2, 'eof')]),
            (magic + b'\3' + I(56) + marker,
             [('magic', 4, 4, 'complete'), ('header', 5, 5, 'complete'),
              ('body', 56, len(marker), 'eof')]),
        ]
        for packet, _ in cases:
            c = self.client(auth=False)
            if packet: c.sock.sendall(packet)
            c.sock.shutdown(socket.SHUT_WR)
            with self.assertRaises(EOFError): c.receive()
        self.assertEqual(self.server.get('/prototype/profiles'), [])        # no session got a profile
        self.server.stop()
        logged = self.server.logpath.read_text()
        events = read_stage_events(logged)
        self.assertEqual(sorted({event[0] for event in events}), [1, 2, 3, 4])
        for session, (_, expected) in enumerate(cases, 1):
            self.assertEqual([event[1:] for event in events if event[0] == session], expected)
        for forbidden in (marker.decode(), marker.hex(), marker.hex().upper(), str(list(marker))):
            self.assertNotIn(forbidden, logged)
        self.assertNotIn('RX channel=', logged)
    def test_tcp_read_complete_stages_preserve_auth_rpc_and_empty_body(self):
        c = self.client()
        self.assertEqual(Reader(c.rpc(59)).facts(), {2: 1})
        c.send(2, b'')  # Valid empty logging-channel body; discarded as before.
        c.sock.shutdown(socket.SHUT_WR)
        with self.assertRaises(EOFError): c.receive()
        self.server.stop()
        logged = self.server.logpath.read_text()
        auth_size = len(auth_body(MARKERS[0].encode(), MARKERS[1].encode()))
        expected = []
        for size in (auth_size, 18, 0):
            expected.extend([(1, 'magic', 4, 4, 'complete'), (1, 'header', 5, 5, 'complete'),
                             (1, 'body', size, size, 'complete')])
        expected.append((1, 'magic', 4, 0, 'eof'))
        self.assertEqual(read_stage_events(logged), expected)
        for marker in MARKERS:
            self.assertNotIn(marker, logged)
            self.assertNotIn(marker.encode().hex(), logged)
    def test_auth25_56_byte_body_permits_rpc_without_saving_identifiers(self):
        markers = [b'LAB-DEVICE-00001', b'LAB-ACCOUNT-0001']
        # Pad synthetic markers to 16 B each; these are not captured identifiers.
        markers = [marker.ljust(16, b'_') for marker in markers]
        payload = auth_body(*markers)
        self.assertEqual(len(payload), 56)
        c = self.client(auth=False)
        c.send(3, payload)
        self.assertEqual(c.receive(), (3, I(1) + b'\0'))
        self.assertEqual(Reader(c.rpc(59)).facts(), {2: 1})
        self.server.stop()
        contents = '\n'.join(p.read_text() for p in self.directory.rglob('*') if p.is_file())
        for marker in markers:
            self.assertNotIn(marker.decode(), contents)
            self.assertNotIn(marker.hex(), contents)
            self.assertNotIn(marker.hex().upper(), contents)
    def test_unsupported_auth_version_and_malformed_body_are_refused(self):
        device, account = b'fictional-device', b'fictional-account'
        valid = auth_body(device, account)
        invalid = {
            'old_synthetic_api1': auth_body(device, account, 1),
            'unconfirmed_api26': auth_body(device, account, 26),
            'unsupported_method': I(2) + valid[4:],
            'truncated_identifier': valid[:-1],
            'oversize_identifier': valid[:16] + I(4097) + valid[20:],
            'trailing_byte': valid + b'\0',
        }
        for case, payload in invalid.items():
            with self.subTest(case=case):
                c = self.client(auth=False)
                c.send(3, payload)
                with self.assertRaises(EOFError): c.receive()
        self.assertEqual(self.server.get('/prototype/profiles'), [])        # no refused session got a profile
    def test_http_logs_omit_query_path_and_header_values(self):
        markers = ['SYNTHETIC_QUERY_DEVICE', 'SYNTHETIC_QUERY_ACCOUNT', 'SYNTHETIC_HTTP_TOKEN', 'SYNTHETIC_PATH_VALUE']
        request = urllib.request.Request(
            f'http://127.0.0.1:{self.server.http}/idjson?device={markers[0]}&account={markers[1]}',
            headers={'Authorization': 'Bearer ' + markers[2], 'User-Agent': markers[2]})
        with urllib.request.urlopen(request, timeout=1) as response:
            self.assertEqual(json.loads(response.read())['Address'], '127.0.0.1')
        with self.assertRaises(urllib.error.HTTPError) as failure:
            self.server.get('/' + markers[3] + '?token=' + markers[2])
        self.assertEqual(failure.exception.code, 404)
        failure.exception.close()
        with urllib.request.urlopen(f'http://127.0.0.1:{self.server.http}/v1/featuretiles/{markers[3]}?token={markers[2]}', timeout=1) as response:
            self.assertEqual(response.read(), b'')
        self.server.stop()
        logged = self.server.logpath.read_text()
        for marker in markers: self.assertNotIn(marker, logged)
        self.assertIn('HTTP route=gatekeeper method=GET status=200', logged)
        self.assertIn('HTTP route=unmatched method=GET status=404', logged)
        self.assertIn('HTTP route=featuretiles method=GET status=200 response_bytes=0', logged)
    def test_health_staticdata_and_loopback_listeners(self):
        self.assertEqual(self.server.get('/health')['compatibility'], 'unverified-1.1.116')
        with urllib.request.urlopen(f'http://127.0.0.1:{self.server.http}/staticdata') as response:
            data = json.loads(gzip.decompress(response.read()))
        self.assertEqual(len(data), 92)
        self.assertEqual(sum(bool(v) for v in without_reconstruction(data).values()), 17)  # Griffin adds a row to the existing monsters table.
        preloader = self.client(auth=False)
        preloader.send(4, I(2))
        channel, payload = preloader.receive()
        r = Reader(payload)
        self.assertEqual((channel, r.integer()), (4, 2))
        self.assertEqual(r.string(), f'http://127.0.0.1:{self.server.http}/staticdata')
        preloader.send(4, I(1) + I(0))
        channel, payload = preloader.receive()
        r = Reader(payload)
        self.assertEqual((channel, r.integer()), (4, 1))
        self.assertEqual(json.loads(gzip.decompress(r.take(r.integer()))), data)
        rows = Path('/proc/net/tcp').read_text().splitlines()[1:]
        for port in (self.server.http, self.server.tcp):
            listeners = [row.split()[1] for row in rows if row.split()[3] == '0A' and row.split()[1].endswith(f':{port:04X}')]
            self.assertEqual(listeners, [f'0100007F:{port:04X}'])
    def test_staticdata_combat_fixtures_preserve_legacy_tables(self):
        # 1.1.116 LoadBombs passes Container.BombEffects to BuildItemEffectsMap.
        # Missing/null fails there; [] represents an empty mapping, not restored balance.
        # The Griffin row is only a structural lookup fixture; it adds no historical combat values.
        with urllib.request.urlopen(f'http://127.0.0.1:{self.server.http}/staticdata', timeout=1) as response:
            data = json.loads(gzip.decompress(response.read()))
        self.assertIsInstance(data.get('bomb_to_effect'), list)
        self.assertEqual(data['bomb_to_effect'], [])
        self.assertEqual(without_reconstruction(data).get('monsters', []).count(GRIFFIN_MONSTER_FIXTURE), 1)
        compatibility_fields = {'bomb_to_effect', 'contract_allowed_swords',
                                'contract_ingredients', 'contract_bombs', 'events'}
        legacy = {key: value for key, value in without_quest_map_fixture(data).items() if key not in compatibility_fields}
        legacy['weekly_quests_rewards'] = []  # New fixture checked separately below.
        self.assertEqual(len(legacy), 82)
        # Canonical digest of the tested tcp-stage-01 sample: all 90 existing
        # records, IDs, paths and numeric values must remain exactly unchanged.
        canonical = json.dumps(legacy, sort_keys=True, separators=(',', ':')).encode()
        self.assertEqual(hashlib.sha256(canonical).hexdigest(),
                         'e9a44eb9e42a7d9f43183c9352ec6fde27ff95064ee794773b5c0d74aca124a2')
        self.assertEqual(sum(len(values) for values in legacy.values()), 90)
    def test_staticdata_reconstructed_skills_effects_and_items_are_consistent(self):
        # Every referenced effect, skill and item exists (GetEffectLists indexes the effects map
        # directly); starting skills unlock the attacks, parry and Igni; oils carry their family effect.
        with urllib.request.urlopen(f'http://127.0.0.1:{self.server.http}/staticdata', timeout=1) as response:
            data = json.loads(gzip.decompress(response.read()))
        effects = {row['id']: row['effect_type_id'] for row in data['effects']}
        skills = {row['id']: row for row in data['skills']}
        self.assertEqual(len({row['slug'] for row in data['skills']}), 49)
        for table, owner in (('skill_to_effect', skills), ('oil_to_effect', {row['id'] for row in data['oils']})):
            for row in data[table]:
                with self.subTest(table=table, row=row):
                    self.assertIn(row['effect_id'], effects)
                    self.assertIn(row['item_id'], owner)
        for row in data['skill_requirements']:
            self.assertIn(row['required_skill_id'], skills)
            self.assertIn(row['skill_id'], skills)
        unlocks = {skills[row['item_id']]['slug']: row['effect_id'] for row in data['skill_to_effect']
                   if row['effect_apply_type_id'] == 18 and skills[row['item_id']]['slug'] != 'witcher_aura'}
        # Aura's two server-backed utility rows are checked by its dedicated protocol suite.
        self.assertEqual(unlocks, {'fast_attack': 47, 'strong_attack': 48, 'parry': 49, 'hit_deflection': 50,
                                   'aard_sign': 42, 'igni_sign': 43, 'quen_sign': 44, 'bomb_creation': 46,
                                   'acquired_tolerance': 45, 'fast_metabolism': 45,
                                   'tawny_owl': 62, 'cat': 62, 'squall': 62, 'wolverine': 62})
        self.assertEqual({effects[45], effects[62]}, {2})
        potion_recipes = {row['id'] for row in data['potion_recipes']}
        self.assertTrue(all(row['power'] in potion_recipes for row in data['skill_to_effect'] if row['effect_id'] == 62))
        # Bomb throws need a base BombSpeed (effect 16, percent) and BombAngle (effect 74, points) at fight start.
        bomb = {(row['effect_id'], row['power'], row['effect_apply_type_id']) for row in data['skill_to_effect']
                if skills[row['item_id']]['slug'] == 'bomb_creation'}
        self.assertLessEqual({(16, 100, 1), (74, 45, 1)}, bomb)
        self.assertEqual({row['id']: row['effect_type_id'] for row in data['effects'] if row['id'] in (16, 74)}, {16: 1, 74: 1})
        starting = {skills[row['id']]['slug'] for row in data['player_starting_skills']}
        self.assertLessEqual({'fast_attack', 'strong_attack', 'parry', 'igni_sign'}, starting)
        # Item ids share one client storage: no id may repeat across potions, oils and bombs.
        ids = [row['id'] for key in ('potions', 'oils', 'bombs') for row in data[key]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertLessEqual({301, 205, 401, 402}, set(ids))  # Donor graph references.
        # LoadOils accepts only OilCombatEffect (family effects 29-39) for every oil row.
        self.assertTrue(all(29 <= row['effect_id'] <= 39 for row in data['oil_to_effect']))
        basic = next(row for row in data['oils'] if row['slug'] == 'oil_basic')
        self.assertEqual(sorted(row['effect_id'] for row in data['oil_to_effect'] if row['item_id'] == basic['id']),
                         list(range(29, 40)))
        hybrid = next(row for row in data['oils'] if row['slug'] == 'oil_hybrid')
        self.assertIn({'item_id': hybrid['id'], 'effect_id': 32, 'power': 100, 'effect_apply_type_id': 1}, data['oil_to_effect'])
        thresholds = [row['exp_threshold'] for row in data['level_ups']]
        self.assertEqual(thresholds[:4], [0, 1000, 3000, 6000])
        self.assertEqual(thresholds, sorted(thresholds))
    def test_staticdata_griffin_has_complete_synthetic_description_lookup(self):
        # The native 1.1.116 Monster.Creator receives grouped descriptions; the Griffin rows are
        # structural placeholders and their thresholds are not claimed as recovered game values.
        with urllib.request.urlopen(f'http://127.0.0.1:{self.server.http}/staticdata', timeout=1) as response:
            data = json.loads(gzip.decompress(response.read()))
        legacy = without_reconstruction(data)
        self.assertEqual(legacy.get('monsters', []).count(GRIFFIN_MONSTER_FIXTURE), 1)
        self.assertEqual([row for row in legacy.get('monster_descriptions', []) if row.get('monster_id') == 9],
                         GRIFFIN_DESCRIPTION_FIXTURES)
    def test_staticdata_contract_relations_are_empty_and_bomb_baseline_is_preserved(self):
        # All three 1.1.116 LoadContracts inputs reach MapDetails unconditionally.
        # Its empty-source return precedes delegate use; null instead throws.
        with urllib.request.urlopen(f'http://127.0.0.1:{self.server.http}/staticdata', timeout=1) as response:
            data = json.loads(gzip.decompress(response.read()))
        additions = {'contract_allowed_swords', 'contract_ingredients', 'contract_bombs'}
        for key in sorted(additions):
            with self.subTest(key=key):
                self.assertIsInstance(data.get(key), list)
                self.assertEqual(data[key], [])
        previous = {key: value for key, value in without_quest_map_fixture(data).items() if key not in additions | {'events'}}
        previous['weekly_quests_rewards'] = []  # Restore only the pre-fixture baseline.
        self.assertEqual(len(previous), 83)
        canonical = json.dumps(previous, sort_keys=True, separators=(',', ':')).encode()
        self.assertEqual(hashlib.sha256(canonical).hexdigest(),
                         '14b3e6bc033429cc8dfdb97ed03ecd190ceec6b658dd0969fe87b5cc5fc658fd')
    def test_staticdata_events_is_empty_and_contract_baseline_is_preserved(self):
        # LoadContracts reads Container.Events unconditionally. Null throws;
        # [] reaches its epilogue without requiring any EventRewards rows.
        with urllib.request.urlopen(f'http://127.0.0.1:{self.server.http}/staticdata', timeout=1) as response:
            data = json.loads(gzip.decompress(response.read()))
        self.assertIsInstance(data.get('events'), list)
        self.assertEqual(data['events'], [])
        previous = {key: value for key, value in without_quest_map_fixture(data).items() if key != 'events'}
        previous['weekly_quests_rewards'] = []  # Restore only the pre-fixture baseline.
        self.assertEqual(len(previous), 86)
        canonical = json.dumps(previous, sort_keys=True, separators=(',', ':')).encode()
        self.assertEqual(hashlib.sha256(canonical).hexdigest(),
                         'a7ab381ce10fa9d3a40a9d6cb57cd5d49d7b28b1a347a0c07b61bacab18786ed')
        self.assertEqual(sum(len(values) for values in previous.values()), 90)
    def test_weekly_reward_record_matches_rpc_and_existing_sword(self):
        # Synthetic boot fixture, not restored weekly rewards or their claiming flow.
        with urllib.request.urlopen(f'http://127.0.0.1:{self.server.http}/staticdata', timeout=1) as response:
            data = json.loads(gzip.decompress(response.read()))
        c = self.client()
        standalone = c.rpc(94)
        self.assertEqual(decode_batch(c.rpc(115))[94], standalone)
        progress = Reader(standalone).weekly()
        self.assertEqual(progress['reward_id'], 0)
        rewards = data['weekly_quests_rewards']
        self.assertEqual(len(rewards), 1)
        reward, = rewards
        self.assertEqual(reward, {'id': 0, 'weekly_quest_tier_id': 0,
                                  'item_type_id': 9, 'amount': 1, 'gold': 0, 'item_id': 1})
        self.assertEqual(reward['id'], progress['reward_id'])
        # Native PlayerInventory.GetItem type 9 selects sword storage.
        sword, = [row for row in data['swords'] if row['id'] == reward['item_id']]
        self.assertEqual(sword['slug'], 'sword_steel_griffin')
        self.assertEqual(len(data), 92)
        self.assertEqual(sum(len(values) for values in without_quest_map_fixture(data).values()), 91)
        previous = without_quest_map_fixture(data)
        previous['weekly_quests_rewards'] = []
        canonical = json.dumps(previous, sort_keys=True, separators=(',', ':')).encode()
        self.assertEqual(hashlib.sha256(canonical).hexdigest(),
                         'ac9c855e916cece3f93f9205bc7661d5eac973c2ac3abec6b5f825901529954a')
        self.assertEqual(sum(len(values) for values in previous.values()), 90)
    def test_monster_event_failure_matches_batch_and_standalone_without_padding(self):
        # Exact old Factory.Deserialize returns after one byte when Success != 1.
        # This is an explicit unsupported seasonal-feature response, not no-event data.
        c = self.client()
        batch = decode_batch(c.rpc(115))
        self.assertIn(122, batch)
        standalone = c.rpc(122)
        self.assertEqual(standalone, bytes([0]))
        self.assertEqual(batch[122], standalone)
        self.assertEqual(len(batch), 21)
        self.assertEqual(batch[117], b'\1' + I(0))
        previous = {method: payload for method, payload in batch.items() if method not in (117, 122)}
        previous[70] = previous_tracking_payload(previous[70])
        previous[3] = previous_player_name(previous[3])
        previous[60] = previous_thorstein(previous[60])
        restored = I(len(previous)) + b''.join(I(method) + payload for method, payload in previous.items())
        self.assertEqual(hashlib.sha256(restored).hexdigest(), 'c925c2f09455fdc61b7bbbf600493684fd16fac80b80a29c3ccf65942c3d3684')
        # A following nonempty weekly payload catches accidental success-path padding.
        weekly = bytes([1]) + I(20260924) + I(701) + I(2) + I(11) + I(22)
        synthetic = I(2) + I(122) + standalone + I(94) + weekly
        self.assertEqual(decode_batch(synthetic), {122: bytes([0]), 94: weekly})
        with self.assertRaisesRegex(ValueError, 'truncated fixture response'):
            decode_batch(I(1) + I(122))
        with self.assertRaisesRegex(ValueError, 'unrecognized batch fixture method 0'):
            decode_batch(I(2) + I(122) + standalone + I(0) + I(94) + weekly)
    def test_quest_journal_logs_are_catalog_keys(self):
        with urllib.request.urlopen(f'http://127.0.0.1:{self.server.http}/staticdata', timeout=1) as response:
            quests = {row['id']: row['journal_log'] for row in json.loads(gzip.decompress(response.read()))['quests']}
        self.assertEqual(quests, {145: JOURNAL_LOGS['prolog_01'], TUTORIAL_QUEST: JOURNAL_LOGS['tutorial'],
                                  JOINT_VENTURE_QUEST: JOURNAL_LOGS['prolog_02'],
                                  **{q['id']: q['journal'] for q in SEASON1['quests']}})
        # Season 1 logs are keys of the 1.1.116 catalog, checked by season1_story.py; here their shape.
        self.assertIn(149, quests)
        for quest in SEASON1['quests']:
            self.assertRegex(quest['journal'], r'^assets/_bundledassets/story/journal/s01/[a-z0-9_]+/log_s01[a-z0-9_]+\.asset$')
    def test_quest_mapping_has_single_root_and_preserves_existing_sample(self):
        with urllib.request.urlopen(f'http://127.0.0.1:{self.server.http}/staticdata', timeout=1) as response:
            full = json.loads(gzip.decompress(response.read()))
        # The prologue sample is unchanged once the appended tutorial quest is removed.
        data = without_reconstruction(full)
        self.assertEqual(data['quests'], [{'id': 145, 'season_id': 0, 'name': 'LAB prologue',
                                         'journal_log': '', 'activation_criteria': ''}])
        self.assertEqual(data['quest_nodes'], [
            {'id': 1, 'quest_id': 145, 'name': 'LAB Thorstein', 'activation_criteria': ''},
            {'id': 2, 'quest_id': 145, 'name': 'LAB dead horse', 'activation_criteria': ''},
            {'id': 3, 'quest_id': 145, 'name': 'LAB griffin', 'activation_criteria': ''}])
        self.assertEqual(data['quest_node_outputs'], [
            {'id': 1, 'quest_node_id': 1, 'name': 'thorstein', 'endpoint': 0},
            {'id': 2, 'quest_node_id': 2, 'name': '2ghouls_left', 'endpoint': 0}])
        self.assertEqual(data['quest_node_edges'], [
            {'from_quest_node_output_id': 1, 'to_quest_node_id': 2},
            {'from_quest_node_output_id': 2, 'to_quest_node_id': 3}])
        self.assertEqual(data['quest_edges'], [])
        # Independent relation checks: every reference resolves; exactly one root,
        # and it remains node1 if the serialized node order is reversed.
        quests = {row['id']: row for row in data['quests']}
        nodes = {row['id']: row for row in data['quest_nodes']}
        outputs = {row['id']: row for row in data['quest_node_outputs']}
        self.assertEqual(len(nodes), len(data['quest_nodes']))
        for node in nodes.values(): self.assertIn(node['quest_id'], quests)
        for output in outputs.values(): self.assertIn(output['quest_node_id'], nodes)
        incoming = set()
        for edge in data['quest_node_edges']:
            output = outputs[edge['from_quest_node_output_id']]
            target = nodes[edge['to_quest_node_id']]
            self.assertEqual(nodes[output['quest_node_id']]['quest_id'], target['quest_id'])
            incoming.add(target['id'])
        for ordered in (data['quest_nodes'], list(reversed(data['quest_nodes']))):
            self.assertEqual([row['id'] for row in ordered if row['id'] not in incoming], [1])
        self.assertEqual(len(data), 87)   # the inherited sample (without_reconstruction)
        self.assertEqual(sum(map(len, without_bomb_fixture(data).values())), 103)  # Includes three Griffin lookup rows.
        previous = without_quest_map_fixture(full)
        self.assertEqual(sum(map(len, previous.values())), 91)
        canonical = json.dumps(previous, sort_keys=True, separators=(',', ':')).encode()
        self.assertEqual(hashlib.sha256(canonical).hexdigest(),
                         '36a9eef125e4e34569aeeee71da0e8d0e8fad9f4108549c3234601358a898b67')
        self.assertEqual(without_bomb_fixture(data)['bombs'], [])  # Exact preceding quest-map baseline.
    def test_auto_equip_covers_every_item_with_all_columns(self):
        # AutoEquipController.CalculatePriority indexes each owned item's row by item type (2 bombs,
        # 3 potions, 4 oils, 9 swords); a missing row throws KeyNotFoundException.
        with urllib.request.urlopen(f'http://127.0.0.1:{self.server.http}/staticdata', timeout=1) as response:
            data = json.loads(gzip.decompress(response.read()))
        rows = {(row['item_type_id'], row['item_id']): row for row in data['auto_equip']}
        expected = {(2, row['id']) for row in data['bombs']} | {(3, row['id']) for row in data['potions']} | \
            {(4, row['id']) for row in data['oils']} | {(9, row['id']) for row in data['swords']}
        self.assertEqual(set(rows), expected)
        self.assertTrue(all(len(row) == 32 for row in rows.values()))
        hybrid = next(row['id'] for row in data['oils'] if row['slug'] == 'oil_hybrid')
        self.assertEqual(rows[(4, hybrid)]['family_hybrid'], 100)
        # CalculatePriority drops items below priority 1: every row carries a positive base weight.
        self.assertTrue(all(row['day'] > 0 and row['weather_normal'] > 0 and row['difficulty1'] > 0 for row in rows.values()))

    def test_bombs_and_potions_have_damage_and_effects(self):
        with urllib.request.urlopen(f'http://127.0.0.1:{self.server.http}/staticdata', timeout=1) as response:
            data = json.loads(gzip.decompress(response.read()))
        types = {row['id'] for row in data['damage_types']}
        self.assertEqual(types, set(range(1, 8)))   # Vulnerability.Type Fire..Dimeritium
        damaged = {row['bomb_id'] for row in data['bomb_damage_types']}
        self.assertEqual(damaged, {row['id'] for row in data['bombs']})
        self.assertTrue(all(row['damage_type_id'] in types and row['amount'] >= 0 for row in data['bomb_damage_types']))
        self.assertTrue(all(row['radius'] > 0 for row in data['bombs']))
        effects = {row['id'] for row in data['effects']}
        potions = {row['id'] for row in data['potions']}
        self.assertTrue(all(row['effect_id'] in effects and row['item_id'] in potions for row in data['potion_to_effect']))
        self.assertIn(205, {row['item_id'] for row in data['potion_to_effect']})   # Exam potion.

    def test_story_monsters_have_rows_and_descriptions(self):
        # CombatPreparationController.Show resolves the fight monster from static data.
        with urllib.request.urlopen(f'http://127.0.0.1:{self.server.http}/staticdata', timeout=1) as response:
            data = json.loads(gzip.decompress(response.read()))
        monsters = {row['slug']: row['id'] for row in data['monsters']}
        self.assertLessEqual({'ghoul', 'alghoul', 'gryphon', 'devourer'}, set(monsters))
        self.assertEqual(len(set(monsters.values())), len(data['monsters']))
        # Every world species has a row. Generated rows retain their fields except for the reviewed native
        # display tier, with the client's lq model of the same slug.
        self.assertLessEqual({s['monster_id'] for s in WORLD['species']}, set(monsters.values()))
        rows = {row['id']: row for row in data['monsters']}
        skulls = {species['monster_id']: species['skulls'] for species in WORLD['species']}
        for row in WORLD['monsters']:
            self.assertGreaterEqual(row['id'], 101)
            self.assertEqual(rows[row['id']], dict(row, difficulty={0: 1, 1: 4, 2: 6, 3: 8}[skulls[row['id']]]))
            slug = row['slug']
            self.assertEqual(row['model'], f'Assets/_bundledassets/characters/monsters/s00/{slug}/{slug}_lq/{slug}_lq.prefab')
        described = {row['monster_id'] for row in data['monster_descriptions']}
        self.assertLessEqual(set(monsters.values()), described)
        # Names are MONSTERS/NAMES/<X> terms (MONSTERS/BESTIARY/<X> is the trivia text). As
        # DataManager.LoadMonsterKnowledge reads the rows (line inserted at level - 1, level -> threshold, last
        # row wins), each monster shows its five description lines in order and has three knowledge tiers whose
        # incremental thresholds follow the pre-1.2 common/rare/legendary totals. Every monster has vulnerabilities.
        vulnerable = {}
        for row in data['monster_vulnerabilities']:
            vulnerable.setdefault(row['monster_id'], []).append(row['damage_type_id'])
        types = {row['id'] for row in data['damage_types']}
        for row in data['monsters']:
            self.assertTrue(row['name'].startswith('MONSTERS/NAMES/'), row['name'])
            key = row['name'].removeprefix('MONSTERS/NAMES/')
            lines, levels = [], {}
            for d in data['monster_descriptions']:
                if d['monster_id'] != row['id']: continue
                lines.extend([None] * (d['level'] - 1 - len(lines)))
                lines.insert(d['level'] - 1, d['content'])
                levels[d['level']] = d['threshold']
            self.assertEqual(lines, [f'MONSTERS/DESCRIPTIONS/{key}/INFO_{n}' for n in range(1, 6)])
            self.assertEqual(levels, {1: {1:3,2:47,3:100}, 2: {1:2,2:8,3:20},
                                      3: {1:1,2:1,3:4}}.get(row['rarity'], {1:3,2:47,3:100}))
            self.assertTrue(vulnerable.get(row['id']), row['slug'])
            self.assertLessEqual(set(vulnerable[row['id']]), types)
        self.assertEqual(len({d['id'] for d in data['monster_descriptions']}), len(data['monster_descriptions']))
        self.assertEqual(vulnerable[1], [5, 2])      # Ghoul: fast attacks and silver (community sheet).
        # SKILLS/NAMES/ELEMENT/<SLUG> names and icon_<slug> sprites (GUI atlas).
        self.assertEqual({row['id']: row['slug'] for row in data['damage_types']},
                         {1: 'damage_fire', 2: 'damage_silver', 3: 'damage_steel', 4: 'damage_kinetic',
                          5: 'damage_fast', 6: 'damage_slow', 7: 'damage_dimeritium'})
        self.assertEqual({r['slug']: r['name'] for r in data['monsters'] if r['id'] in (9, 12)},
                         {'gryphon': 'MONSTERS/NAMES/GRYPHON', 'wraith_lvl2': 'MONSTERS/NAMES/WRAITH_LVL2'})

    def test_level_up_is_pushed_once_per_level_and_check_in_app_answers(self):
        server, c = self.reconstructed()
        c.rpc(3)
        self.assertEqual(c.pushes, [])                             # a new profile starts at level 1, announced
        # Story rewards reach level 2 (1000 XP): the griffin's 250 and a wraith's 250 do not, the gargoyle king's 600 does.
        # The level is pushed after that response as an Api RESPONSE with message id 0, no acknowledgement and method 31:
        # [int Level] + 13 lists with one id per unit. The window never finishes loading without an item, so every level
        # grants its rewards (added to the inventory).
        before = self.inventory(c)
        for output in ('griffin_1', 'wraith_won'):
            c.rpc(57, self.completion_body({}, instance=GRIFFIN, output=output))
        c.rpc(3)
        self.assertEqual(c.pushes, [])
        c.rpc(57, self.completion_body({}, instance=GRIFFIN, output='gargoyle'))
        c.rpc(3)
        lists = [I(1) + I(205)] + [I(0)] * 9 + [I(5) + I(103) * 3 + I(101) * 2] + [I(0)] * 2
        self.assertEqual(c.pushes, [(31, I(2) + b''.join(lists))])
        after = self.inventory(c)
        self.assertEqual(after['ingredients'].get(103, 0) - before['ingredients'].get(103, 0), 3)
        self.assertEqual(after['potions'].get(205, 0) - before['potions'].get(205, 0), 1)
        c.rpc(3)
        self.assertEqual(len(c.pushes), 1)                          # announced once
        self.assertEqual(server.state()['player']['exp'], 1100)
        # The level-up window's CheckInApp (101) is answered true, so no in-app offer opens.
        self.assertEqual(c.rpc(101), b'\1')
        # Several levels at once are pushed in order, also after a restart of the client.
        server.stop()
        path = self.profile_file('test-fresh')
        profile = json.loads(path.read_text())
        player = profile.get('Player') or profile.get('player')
        player['Exp' if 'Exp' in player else 'exp'] = 6000                 # level 4
        path.write_text(json.dumps(profile))
        server = self.start('test-fresh', self.RECONSTRUCTED)
        c = self.client(server)
        c.rpc(115); c.rpc(3)
        self.assertEqual(c.pushes, [])                             # never during boot, only after experience
        c.rpc(8, b'\1' + I(13) + I(0) * 13 + b'\0')                # a fight without an encounter grants nothing
        c.rpc(3)
        self.assertEqual([body[:4] for _, body in c.pushes], [I(3), I(4)])
        self.assertTrue(all(body[4:8] == I(1) for _, body in c.pushes))         # one Swallow each
        # Legacy profiles are never pushed.
        legacy = self.client()
        legacy.rpc(3); legacy.rpc(3)
        self.assertEqual(legacy.pushes, [])

    def test_bestiary_knowledge_tiers_follow_three_and_fifty_kills(self):
        server, c = self.reconstructed()
        c.rpc(3); c.rpc(3)      # the first request saves the profile after its answer; the second waits for that
        def set_kills(kills):
            nonlocal server, c
            server.stop()
            path = self.profile_file('test-fresh')
            profile = json.loads(path.read_text())
            player = profile.get('Player') or profile.get('player')
            player['Kills' if 'Kills' in player or 'kills' not in player else 'kills'] = {'3': kills}
            path.write_text(json.dumps(profile))
            server = self.start('test-fresh', self.RECONSTRUCTED)
            c = self.client(server)
        set_kills(2)
        self.assertEqual(c.rpc(65, I(3)), b'\0' + I(-1) + I(0))
        set_kills(3)                                                 # Community: a skill point at three kills
        self.assertEqual(c.rpc(65, I(3)), b'\1' + I(3) + I(1))
        self.assertEqual(c.rpc(65, I(3)), b'\0' + I(-1) + I(0))
        set_kills(50)                                                # and another at fifty
        self.assertEqual(c.rpc(65, I(3)), b'\1' + I(3) + I(1))
        self.assertEqual(c.rpc(65, I(3)), b'\0' + I(-1) + I(0))

    def test_player_modifiers_and_friend_actions_answer_without_closing_the_session(self):
        server, c = self.reconstructed()
        # AddPlayerModifier (90): [int 4][int Result][int Id][int Start][int Expire]. The season 1 modifiers
        # (player_modifiers rows 1-8) are kept; an unknown id is refused. RemovePlayerModifier (92) succeeds;
        # GetPlayerModifiers (91) lists what is held, alone and in the boot batch.
        self.assertEqual(c.rpc(90, I(99) + I(3600)), I(4) + I(1) + I(99) + I(0) + I(0))
        with urllib.request.urlopen(f'http://127.0.0.1:{server.http}/staticdata', timeout=1) as response:
            rows = json.loads(gzip.decompress(response.read()))['player_modifiers']
        self.assertEqual(rows[:-2], [{'id': m['id'], 'slug': m['slug']} for m in SEASON1['modifiers']])  # then the debug tools' two
        self.assertEqual({row['id']: row['slug'] for row in rows}[7], 's01_12h')
        # Vesemir's remedy (modifier 7) lasts the graph's 12 h, like the node it gates.
        r = Reader(c.rpc(90, I(7) + I(43200)))
        self.assertEqual((r.integer(), r.integer(), r.integer()), (4, 0, 7))
        start, expire = r.integer(), r.integer()
        self.assertEqual(expire - start, 12 * 3600)
        r = Reader(c.rpc(90, I(5) + I(7200)))                     # the potion keeps its 2 h
        self.assertEqual((r.integer(), r.integer(), r.integer()), (4, 0, 5))
        self.assertEqual(-r.integer() + r.integer(), 7200)
        self.assertEqual(c.rpc(92, I(5)), I(0) + I(5))
        self.assertEqual(c.rpc(91), I(0) + I(1) + I(7) + I(start) + I(expire))
        self.assertEqual(decode_batch(c.rpc(115))[91], c.rpc(91))
        self.assertEqual(c.rpc(92, I(7)), I(0) + I(7))
        self.assertEqual(c.rpc(92, I(1)), I(0) + I(1))
        self.assertEqual(c.rpc(91), I(0) + I(0))
        # Friend actions (103-108) are refused with the ids echoed, in each response layout.
        for method in (103, 104, 105, 108):
            self.assertEqual(c.rpc(method, Q(42)), b'\0' + Q(42))
        self.assertEqual(c.rpc(106, I(2) + Q(42)), b'\0' + I(2) + Q(42))
        self.assertEqual(c.rpc(107, Q(42)), b'\0' + Q(42) + I(0) * 3)
        self.assertEqual(c.rpc(3)[:1], b'\1')                     # the session is still open
        legacy = self.client()
        self.assertEqual(legacy.rpc(92, I(1)), I(1) + I(1))

    def test_item_descriptions_get_their_values(self):
        # DataManager.Load* replace description tag #n with the item's n-th effect power (potions, armors,
        # swords) or n-th damage row (bombs); an item without them shows a raw "#0%".
        with urllib.request.urlopen(f'http://127.0.0.1:{self.server.http}/staticdata', timeout=1) as response:
            data = json.loads(gzip.decompress(response.read()))
        effects = {row['id']: row['effect_type_id'] for row in data['effects']}
        def powers(table):
            rows = {}
            for row in data[table]:
                self.assertIn(row['effect_id'], effects)
                rows.setdefault(row['item_id'], []).append(row['power'])
            return rows
        potions = powers('potion_to_effect')
        self.assertEqual(set(potions), {row['id'] for row in data['potions']})
        self.assertEqual((potions[201], potions[202], potions[206], potions[208]), ([33], [50], [75], [50, 100]))
        self.assertEqual(powers('armor_to_effect'), {1: [80], 2: [10], 3: [50], 4: [15], 5: [100], 6: [25], 8: [50]})
        # Every sword but the Witcher's two (their descriptions name no effect) has its effect row.
        self.assertEqual(set(powers('sword_to_effect')), {row['id'] for row in data['swords']} - {7, 8})
        damage = {}
        for row in data['bomb_damage_types']:
            damage.setdefault(row['bomb_id'], []).append((row['damage_type_id'], row['amount']))
        self.assertEqual(set(damage), {row['id'] for row in data['bombs']})
        self.assertEqual([damage[b][0] for b in (401, 402, 403, 404)], [(4, 525), (4, 800), (4, 800), (4, 800)])
        self.assertEqual(damage[405], [(7, 0), (4, 525)])   # Dimeritium: "#1" is the kinetic damage.

    def test_tutorial_quest_rows_resolve_within_quest_144(self):
        with urllib.request.urlopen(f'http://127.0.0.1:{self.server.http}/staticdata', timeout=1) as response:
            data = json.loads(gzip.decompress(response.read()))
        nodes = {row['id']: row for row in data['quest_nodes'] if row['quest_id'] == TUTORIAL_QUEST}
        self.assertEqual(set(nodes), TUTORIAL_NODES)
        outputs = {row['id']: row for row in data['quest_node_outputs'] if row['quest_node_id'] in nodes}
        self.assertEqual({row['name'] for row in outputs.values()}, {'tutorial_end', 'exam', 'exam_end', 'exam_fail'})
        incoming = {edge['to_quest_node_id'] for edge in data['quest_node_edges'] if edge['from_quest_node_output_id'] in outputs}
        self.assertEqual(set(nodes) - incoming, {228})
        self.assertEqual(len({row['id'] for row in data['quest_node_outputs']}), len(data['quest_node_outputs']))
    def test_bomb_lookup_fixture_matches_old_schema_and_preserves_99_rows(self):
        # The donor asks IIntStorage<Bomb> for 401 during graph initialization.
        # Field names/types are from old DataMember metadata; numbers and visual
        # mapping are authored structural placeholders, not recovered balance.
        before = self.server.get('/prototype/profiles')
        with urllib.request.urlopen(f'http://127.0.0.1:{self.server.http}/staticdata', timeout=1) as response:
            data = json.loads(gzip.decompress(response.read()))
        self.assertEqual({k: v for k, v in data['bombs'][0].items() if k != 'radius'},
                         {k: v for k, v in BOMB_LOOKUP_FIXTURE.items() if k != 'radius'})
        self.assertEqual(without_reconstruction(data)['bombs'], [BOMB_LOOKUP_FIXTURE])
        integer_fields = {'id', 'priority', 'delay', 'duration', 'value', 'radius', 'explode_style'}
        string_fields = {'slug', 'prefab_path'}
        for row in data['bombs']:
            self.assertEqual(set(row), integer_fields | string_fields)
            for key in integer_fields:
                self.assertIs(type(row[key]), int)
                self.assertGreaterEqual(row[key], -(2**31))
                self.assertLess(row[key], 2**31)
            for key in string_fields: self.assertIs(type(row[key]), str)
        self.assertEqual(len({item['id'] for item in data['bombs']}), len(data['bombs']))
        # Observed LoadBombs branches accept missing damage/effect map entries
        # and empty recipes; no fabricated related IDs are required here.
        # The reconstruction fills bomb damage (tested separately); the other relations stay empty.
        for key in ('bomb_damage_types', 'bomb_to_effect', 'bomb_recipes',
                    'bomb_recipe_ingredients', 'shop_bombs'):
            self.assertIs(type(data[key]), list)
            self.assertEqual(without_reconstruction(data)[key], [])
        self.assertEqual(without_reconstruction(data).get('monsters', []).count(GRIFFIN_MONSTER_FIXTURE), 1)
        legacy = without_reconstruction(data)
        self.assertEqual((len(data), sum(map(len, legacy.values())), sum(bool(v) for v in legacy.values())), (92, 104, 17))
        previous = without_griffin_combat_fixture(without_bomb_fixture(without_reconstruction(data)))
        self.assertEqual(sum(map(len, previous.values())), 99)
        canonical = json.dumps(previous, sort_keys=True, separators=(',', ':')).encode()
        self.assertEqual(hashlib.sha256(canonical).hexdigest(),
                         'e9401f6552188cb144128f0a6dc2a0d0fc743797c02ff70dccfe97a6f93046a7')
        self.assertEqual(self.server.get('/prototype/profiles'), before)
    def test_bomb_fixture_preserves_quest_map_protocol_before_and_after_completion(self):
        # Exact quest-map-01 bodies captured with this same synthetic profile
        # and completion request. A data row must not grant equipment/rewards
        # or change any of the 20 inline responses or active node payloads.
        expected = [
            ('8fea850a4b5174628d926c5067becec59236924032325393e29cbff43a7da67b',
             '95cc85d643cd210bc99797d278e5809861eb0f9090407ca116ee999832ca7eec'),
            ('395fead97e90114ba697f1375275fc53cdd24cd0abbe919c0882a3f589284694',
             '70958482d2eece541d0bc83bb2b80397153cb297c8c9d7d795027d221a5aca86'),
        ]
        client = self.client()
        for phase, hashes in enumerate(expected):
            if phase:
                completion = client.rpc(57, self.completion_body())
                self.assertEqual(hashlib.sha256(completion).hexdigest(),
                                 '7182a244d9dff93a4b7e9f78dd71795c71d605e0480ca1744ac226512b563013')
                self.assert_zero_completion_rewards(Reader(completion).end_graph())
            before = self.server.state()
            active, batch = client.rpc(60), client.rpc(115)
            self.assertEqual(tuple(hashlib.sha256(x).hexdigest() for x in (previous_thorstein(active), previous_batch(batch))), hashes)
            parts = decode_batch(batch)
            self.assertEqual(len(parts), 21)
            self.assertEqual(parts[60], active)
            self.assertEqual(self.server.state(), before)
    def test_tracked_quest_matches_nodes_at_boot_completion_and_restart(self):
        with urllib.request.urlopen(f'http://127.0.0.1:{self.server.http}/staticdata', timeout=1) as response:
            data = json.loads(gzip.decompress(response.read()))
        node_map = {row['id']: row['quest_id'] for row in data['quest_nodes']}
        c = self.client()
        expected_node = 1
        saved = None
        for phase in ('boot', 'completion', 'restart'):
            if phase == 'completion':
                completion = Reader(c.rpc(57, self.completion_body())).end_graph()
                expected_node = 2
                self.assertEqual(node_map[completion['nodes'][0]['node']], 145)
                saved = self.server.state()
            if phase == 'restart':
                c.close(); self.server.stop()
                self.server = self.start('test-alpha'); c = self.client()
                self.assertEqual(self.server.state(), saved)
            before = self.server.state()
            batch = decode_batch(c.rpc(115))
            tracking = decode_finished_quests(batch[70])
            self.assertEqual(tracking, {'season': 0, 'finished': [], 'tracked': 145, 'active': [145]})
            active = Reader(batch[60]).quest()['nodes']
            self.assertEqual(len(active), 1)
            self.assertEqual(active[0]['node'], expected_node)
            self.assertEqual(node_map[active[0]['node']], tracking['tracked'])
            self.assertIn(tracking['tracked'], tracking['active'])
            self.assertEqual(self.server.state(), before)
    def test_finished_quest_reader_exact_body_and_boundaries(self):
        body = decode_batch(self.client().rpc(115))[70]
        self.assertEqual(body, I(0) + I(0) + I(145) + I(1) + I(145))
        self.assertEqual(previous_tracking_payload(body), I(0) + I(0) + I(-1) + I(1) + I(145))
        for length in range(len(body)):
            with self.subTest(length=length), self.assertRaises(ValueError):
                decode_finished_quests(body[:length])
        with self.assertRaisesRegex(ValueError, 'unconsumed finished-quests bytes'):
            decode_finished_quests(body + bytes([0]))
    def test_same_profile_cannot_be_opened_by_two_servers(self):
        # A second server on the same directory starts, but cannot serve a player whose profile the first holds.
        self.client().rpc(78, I(2) + I(95) + I(1))
        second = self.start('test-alpha')
        with self.assertRaises(EOFError): self.client(second)
        self.assertEqual(self.server.state()['facts'], {'2': 1, '95': 1})
    def test_corrupt_profile_is_preserved_and_refused(self):
        self.client().rpc(78, I(2) + I(95) + I(1))
        self.server.stop()
        path = self.profile_file('test-alpha')
        damaged = '{"synthetic_corrupt_profile":'
        path.write_text(damaged)
        restarted = self.start('test-alpha')                                 # other players are still served
        with self.assertRaises(EOFError): self.client(restarted)            # this player's session is refused
        self.assertEqual(path.read_text(), damaged)

if __name__ == '__main__': unittest.main(verbosity=2)
