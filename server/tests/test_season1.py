"""Season 1 opens as the maintainer listed it (10 October 2026): each quest after its prerequisite, Monster Slayer on the
troll trigger, To the Rescue's Kienan and the mushrooms beside the walking player, Lothar's map sold once, and a permanent
effect without a timer."""
import gzip
import json
import math
import time
import unittest
import urllib.request

import test_prototype as base
from test_prototype import I, Q, Reader, SEASON1

CELLS = [0x4704440000000000 + (k << 40) for k in range(9)]
REQUEST = I(9) + b''.join(Q(cell) for cell in CELLS)
# The quest rows the client checks (season1_quests.py "criteria").
CRITERIA = {149: 'f100>=4', 104: 'f100>=4', 148: 'f100>=4', 150: 'f1001>=1', 152: 'f178>=1', 153: 'f179>=1',
            154: 'f31>=5', 147: 'f1001>=1', 158: 'f46>=1', 159: 'f1003>=1', 160: 'f184>=1', 161: 'f1010>=1'}
GIVER = {n['quest']: n['id'] for n in SEASON1['nodes'] if n['kind'] == 'giver'}
NODE = {n['key']: n['id'] for n in SEASON1['nodes']}
GOOD_MONEY_DONE = {100: 4, 53: 4, 1000: 1, 1001: 1, 1003: 1}


class Season1Tests(base.PrototypeTests):
    def season(self, name, facts, story=None, gold=None, summons=None):
        """A profile past "A Joint Venture" with [facts] (and story progress, orens, summoned monsters) on a map of places
        around (10, 20)."""
        origin = (10.0, 20.0)
        cos = math.cos(math.radians(origin[0]))
        places = [{'id': f'lab-test-{r}-{k}', 'lat': origin[0] + math.sin(k * math.pi / 4) * r / 110540.0,
                   'lng': origin[1] + math.cos(k * math.pi / 4) * r / (111320.0 * cos), 'biomes': [4], 'kind': 'path'}
                  for r in (100, 150, 200, 250, 300, 400, 500, 600, 700) for k in range(8)]
        url, _ = self.playable_service(lambda ids, epoch: {
            i: {'center': list(origin), 'places': places if n == 0 else []} for n, i in enumerate(ids)})
        env = dict(self.RECONSTRUCTED, Playable__Url=url)
        server = self.start(name, env)
        c = self.client(server); c.rpc(3); c.rpc(3)
        server.stop()
        path = self.profile_file(name)
        profile = json.loads(path.read_text())
        profile['QuestStage'] = 'jv_done'
        profile['Facts'] = {str(k): v for k, v in facts.items()}
        if story:
            profile['Player']['Story'] = {'Active': [], 'Started': [], 'Finished': [], 'Outputs': [], 'Tracked': None,
                                          'Reached': {}, 'Clock': 0, **story}
        if gold is not None: profile['Player']['Gold'] = gold
        if summons is not None: profile['Player']['Summons'] = summons
        path.write_text(json.dumps(profile))
        server = self.start(name, env)
        c = self.client(server)
        c.rpc(88, REQUEST)
        return server, c

    def givers(self, c):
        return {g['node']: g['mode'] for g in self.locations_by_cell(c.rpc(40, REQUEST))['quests']}

    def test_season1_quests_open_after_their_prerequisites(self):
        with urllib.request.urlopen(f'http://127.0.0.1:{self.server.http}/staticdata', timeout=1) as response:
            rows = json.loads(gzip.decompress(response.read()))['quests']
        self.assertEqual({q['id']: q['activation_criteria'] for q in rows if q['id'] in CRITERIA}, CRITERIA)
        # After "A Joint Venture": Good Money, Evil Never Sleeps, and To the Rescue, whose Kienan the client shows beside the
        # player after 200 m of walking (Collecting).
        server, c = self.season('test-open', {100: 4})
        self.assertEqual(self.givers(c), {GIVER[149]: 1, GIVER[104]: 1, GIVER[148]: 7})
        self.assertEqual(Reader(c.rpc(60)).quest()['nodes'], [])

        def learn(facts):   # facts the game's own graphs set, as their steps send them
            for fact, value in facts.items():
                self.assertEqual(c.rpc(78, I(2) + I(fact) + I(value)), b'\1')
            return set(self.givers(c))
        # Good Money opens Pride, What Lurks and the Dark Side, not Monster Slayer, Will o' the Wisp or the Mushrooming;
        # Lothar's map waits, invisible, beside the player for whichever of his graphs queues it.
        self.assertEqual(learn({53: 4, 1000: 1, 1001: 1, 1003: 1}),
                         {GIVER[104], GIVER[148], GIVER[150], GIVER[159], GIVER[147]})
        self.assertEqual([(n['node'], n['mode'], n['place']) for n in Reader(c.rpc(60)).quest()['nodes']],
                         [(NODE['s01hq01_map'], 2, 'tut_thorstein')])
        # Each quest of the main line opens the next; What Lurks opens Will o' the Wisp.
        self.assertIn(GIVER[152], learn({54: 4, 178: 1}))
        opened = learn({55: 6, 179: 1})
        self.assertIn(GIVER[153], opened)
        self.assertNotIn(GIVER[152], opened)
        self.assertIn(GIVER[160], learn({47: 3, 184: 1}))
        # Intruder after the five main quests (fact 31 counts them), Monster Slayer only on its trigger.
        self.assertNotIn(GIVER[154], learn({31: 4}))
        opened = learn({31: 5})
        self.assertIn(GIVER[154], opened)
        self.assertNotIn(GIVER[161], opened)

    def test_season1_a_started_quests_hidden_giver_stays_normal(self):
        # Once Kienan is helped, his giver only marks where the quest may be relocated: as Collecting it would come up
        # beside the walking player again.
        server, c = self.season('test-rescue', {100: 4, 65: 1, 143: 1}, story={'Started': [148]})
        self.assertEqual(self.givers(c), {GIVER[148]: 1, GIVER[149]: 1, GIVER[104]: 1})

    def test_season1_endings_save_their_completion_facts_and_the_main_quest_count(self):
        # Pride's last step sends only its own facts; the server adds Pride's completion fact and counts the main quests.
        server, c = self.season('test-done', {**GOOD_MONEY_DONE, 54: 3, 31: 1},
                                story={'Started': [150], 'Finished': [149], 'Outputs': [1015]})
        vesemir = SEASON1['nodes'][[n['key'] for n in SEASON1['nodes']].index('s01mq02_vesemir')]
        c.rpc(57, self.completion_body({211: 0}, instance=vesemir['instance'], output='vesemir'))
        facts = server.state()['facts']
        self.assertEqual((facts['178'], facts['31']), (1, 2))
        self.assertIn(GIVER[152], self.givers(c))   # The Sins of Our Fathers is offered

    def test_season1_lothar_sells_the_map_once(self):
        server, c = self.season('test-map', GOOD_MONEY_DONE, gold=600)
        node, = Reader(c.rpc(60)).quest()['nodes']
        # Lothar's payment graph sends "payment" (no node, no facts): the reply takes 500 orens and still holds the map,
        # which the game opens because the graph queued it.
        paid = Reader(c.rpc(57, self.completion_body({}, instance=0, output='payment'))).end_graph()
        self.assertEqual((paid['gold'], [n['node'] for n in paid['nodes']]), (-500, [NODE['s01hq01_map']]))
        self.assertEqual(server.state()['player']['gold'], 100)
        # Without enough orens nothing is taken.
        self.assertEqual(Reader(c.rpc(57, self.completion_body({}, instance=0, output='payment'))).end_graph()['gold'], 0)
        self.assertEqual(server.state()['player']['gold'], 100)
        # The map's graph starts Sword in the Stone and sets fact 46, so the map leaves and Lothar stops selling it.
        started = Reader(c.rpc(57, self.completion_body({46: 1, 10158: 1}, instance=node['instance'], output='map'))).end_graph()
        self.assertNotIn(NODE['s01hq01_map'], [n['node'] for n in started['nodes']])
        self.assertIn(158, server.state()['player']['story']['started'])

    def test_season1_mushrooms_appear_beside_the_walking_player_for_a_day(self):
        now = int(time.time())
        vogt = next(o['id'] for o in SEASON1['outputs'] if o['node'] == NODE['s01mq05_vogt'] and o['name'] == 'vogt')
        server, c = self.season('test-mushrooms', {100: 4, 179: 1, 56: 3}, story={
            'Started': [153], 'Outputs': [vogt], 'Reached': {str(vogt): now}})
        nodes = Reader(c.rpc(60)).quest()['nodes']
        mushroom, = [n for n in nodes if n['node'] == NODE['s01mq05_mushroom']]
        self.assertEqual((mushroom['mode'], mushroom['place']), (7, 'tut_thorstein'))
        # The contest lasts a day (the graph's 24 h modifier): then the mushrooms go and the vogt's ceremony comes.
        with urllib.request.urlopen(urllib.request.Request(
                f'http://127.0.0.1:{server.http}/prototype/story/clock?add={24 * 3600}&profile={server.profile_id()}',
                method='POST'), timeout=1):
            pass
        shown = {n['node'] for n in Reader(c.rpc(60)).quest()['nodes']}
        self.assertNotIn(NODE['s01mq05_mushroom'], shown)
        self.assertIn(NODE['s01mq05_final'], shown)

    def test_season1_the_leshen_hound_and_the_tracks_are_hunt_circles(self):
        # Their only settings (the footprints placeholder) have no prefab: as normal nodes they drew nothing on the map.
        server, c = self.season('test-hound', {100: 4, 72: 4}, story={'Started': [104]})
        shown = {n['node']: (n['mode'], n['place']) for n in Reader(c.rpc(60)).quest()['nodes']}
        mode, place = shown[NODE['s01mq04_hound']]
        self.assertEqual(mode, 4)                       # a search circle around a real place
        self.assertNotEqual(place, 'tut_thorstein')
        self.assertEqual(shown[NODE['s01mq04_hemlock']][0], 1)
        self.assertEqual({n['display'] for n in SEASON1['nodes'] if n['poi'].endswith('footprint_placeholder.asset')}, {4})

    def test_season1_monster_slayer_opens_after_losing_to_rock_trolls(self):
        now = int(time.time())
        trolls = [{'ItemType': 16, 'ItemId': 1, 'StartTime': now, 'DespawnTime': now + 3600, 'Longitude': 1, 'Latitude': 1,
                   'Monsters': [{'MonsterId': 22, 'Difficulty': 2, 'InstanceId': 7000 + k, 'Alive': True} for k in range(2)]}]
        server, c = self.season('test-trolls', GOOD_MONEY_DONE, summons=trolls)

        def fight(instance, won):
            self.assertEqual(c.rpc(113, Q(instance)), b'\1')
            c.rpc(114, bytes([won]) + I(13) + I(0) * 13 + b'\0')
            return server.state()['facts']
        self.assertNotIn('1011', fight(7001, False))    # a loss before any win counts nothing
        self.assertEqual(fight(7000, True)['1011'], 1)
        for losses in (1, 2):
            facts = fight(7001, False)
            self.assertEqual((facts['1011'], facts.get('1010')), (1 + losses, None))
        self.assertNotIn(GIVER[161], self.givers(c))
        self.assertEqual(fight(7001, False)['1010'], 1)  # the third loss: the troll talks
        self.assertIn(GIVER[161], self.givers(c))
        self.assertEqual(Reader(base.decode_batch(c.rpc(115))[59]).facts()[1010], 1)   # the game learns it at start-up

    def test_season1_a_permanent_effect_shows_no_timer(self):
        server, c = self.reconstructed()
        r = Reader(c.rpc(90, I(2) + I(-1)))   # the curse: AddPlayerModifier with -1 seconds, until removed
        self.assertEqual([r.integer() for _ in range(3)], [4, 0, 2])
        start, expire = r.integer(), r.integer()
        self.assertEqual(expire, -1)
        self.assertEqual(c.rpc(91), I(0) + I(1) + I(2) + I(start) + I(-1))

    def test_season1_the_wisps_treasure_ends_its_timer(self):
        # The catch graph gives the wisp 15 minutes (effect 8, 900 s); the treasure graph adds it again with 0 s to end it.
        server, c = self.reconstructed()
        c.rpc(90, I(8) + I(900))
        r = Reader(c.rpc(90, I(8) + I(0)))
        self.assertEqual([r.integer() for _ in range(3)], [4, 0, 8])
        self.assertEqual(r.integer(), r.integer())       # it expires as it starts
        self.assertEqual(c.rpc(91), I(0) + I(0))


def load_tests(loader, tests, pattern):
    # Reuse the prototype fixtures without running its inherited regression suite twice.
    return unittest.TestSuite(Season1Tests(name) for name in vars(Season1Tests) if name.startswith('test_'))


if __name__ == '__main__':
    unittest.main()
