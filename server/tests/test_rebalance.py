"""0.3.0's rebalance and its presets (Revival by default, Vanilla built in): quest and daily rewards, experience, level-ups,
bags, trinket bonuses, summoning scrolls, consumables and the texts the hook gives the game. Synthetic profiles only."""
import gzip
import json
import struct
import time
import unittest
import urllib.request

import test_prototype as base
from test_tasks import TaskTests

I, Q, Reader = base.I, base.Q, base.Reader
SPECIES = {s['monster_id']: s for s in base.WORLD['species']}


def modifiers(data):
    r = Reader(data)
    r.integer()
    return {r.integer(): (r.integer(), r.integer()) for _ in range(r.integer())}   # id: (start, expiry)


class RebalanceTests(TaskTests):
    def edit(self, name, change):
        path = self.profile_file(name)
        profile = json.loads(path.read_text())
        change(profile['Player'])
        path.write_text(json.dumps(profile))

    world = base.PrototypeTests.tuned

    def saved_profile(self, c):
        c.rpc(3); c.rpc(3)      # the first request saves the profile after its answer; the second waits for that

    def static(self, server):
        with urllib.request.urlopen(f'http://127.0.0.1:{server.http}/staticdata', timeout=2) as response:
            return json.loads(gzip.decompress(response.read()))

    def griffin(self, c):
        return Reader(c.rpc(57, self.completion_body({}, instance=base.GRIFFIN, output='griffin_1'))).end_graph()

    def test_quest_endings_pay_the_presets_table(self):
        server, c = self.reconstructed()
        done = self.griffin(c)
        self.assertEqual((done['exp'], done['gold'], done['potions']), (500, 100, {205: 2}))   # Revival
        self.assertEqual(self.inventory(c)['potions'].get(205), 2)
        self.assertEqual(self.griffin(c)['exp'], 0)                                            # an ending pays once
        server = self.start('test-vanilla', dict(self.RECONSTRUCTED, **self.world('vanilla')))
        done = self.griffin(self.client(server))
        self.assertEqual((done['exp'], done['gold'], done['potions']), (250, 45, {}))            # the wiki's v1.1 amounts

    def test_a_fight_pays_by_rarity_and_after_a_server_restart(self):
        server, c = self.task_server(self.kills(1))
        r = Reader(c.rpc(111, I(16) + I(1) + I(1000000) + I(1000000)))
        self.assertEqual(r.byte(), 1)
        group, = self.summoned_groups(r)
        monster, instance, _ = group['monsters'][0]
        self.assertEqual(c.rpc(113, Q(instance)), b'\1')
        server.stop()                                            # the encounter outlives a restart
        self.assertEqual(self.saved_fight()['InstanceId'], instance)
        server, c = self.task_server(self.kills(1))
        end = self.combat_end(Reader(c.rpc(114, bytes([1]) + I(13) + I(0) * 13 + bytes([0]))))
        self.assertEqual(end['base'], {1: 100, 2: 250, 3: 600}[SPECIES[monster]['rarity']])
        server.stop()
        self.assertIsNone(self.saved_fight())

    def saved_fight(self):
        return json.loads(self.profile_file('tasks').read_text())['Player'].get('Fight')

    def test_daily_claims_pay_scaled_gold_experience_and_an_item(self):
        server, c = self.task_server(self.kills(1))
        tasks, _, _ = self.daily(c)
        task = next(iter(tasks))
        gold = next(d['gold'] for d in self.kills(1) if d['id'] == task)
        rows = {r['id']: r['reward'] for r in self.static(server)['daily_quests']}
        self.assertEqual(rows[task], 2 * gold)                   # tasks.goldPercent 200 in the panel's row
        self.fight(c)
        before, items = self.player_info(c), self.inventory(c)
        self.assertEqual(self.claim(c, task)[0], 0)
        after, items_after = self.player_info(c), self.inventory(c)
        self.assertEqual((after['gold'] - before['gold'], after['exp'] - before['exp']), (2 * gold, 200))
        count = lambda inv: sum(sum(m.values()) for k, m in inv.items() if k != 'bag')
        self.assertEqual(count(items_after) - count(items), 1)   # one item from the daily pool

    def test_a_lost_level_up_window_comes_again_after_the_next_boot(self):
        server, c = self.reconstructed()
        self.saved_profile(c)
        server.stop()
        self.edit('test-fresh', lambda p: p.update(Exp=3000, LevelAnnounced=3, LevelShown=2))
        server, c = self.reconstructed()
        # The boot's experience sets the level the game compares a LevelUp push with, so it stops below level 3 until
        # that window is shown; the game's own GetPlayerInfo after the window reads the whole amount.
        info = Reader(base.decode_batch(c.rpc(115))[3]); info.byte(); info.string(); info.integer()
        self.assertEqual(info.integer(), 2999)
        c.rpc(119)
        c.rpc(3)
        c.rpc(3)                # a push follows a reply: the next request reads it
        self.assertEqual([level for method, body in c.pushes if method == 31 for level in [struct.unpack('>i', body[:4])[0]]], [3])
        c.rpc(3)
        self.assertEqual(len([p for p in c.pushes if p[0] == 31]), 1)
        self.assertEqual(server.state()['player'].get('levelShown', 3), 3)

    def test_a_retried_fight_brings_its_level_up_window_again(self):
        # The game retries a request whose answer it lost; the LevelUp push written behind that answer was lost with it.
        server, c = self.reconstructed()
        self.saved_profile(c)
        server.stop()
        self.edit('test-fresh', lambda p: p.update(Exp=950, LevelAnnounced=1, LevelShown=1))
        server, c = self.reconstructed()
        r = Reader(c.rpc(111, I(16) + I(1) + I(1) + I(1)))
        self.assertEqual(r.byte(), 1)
        group, = self.summoned_groups(r)
        self.assertEqual(c.rpc(113, Q(group['monsters'][0][1])), b'\1')
        body = bytes([1]) + I(13) + I(0) * 13 + b'\0'
        won = c.rpc(114, body)
        self.assertEqual(c.rpc(114, body, repeat=True), won)   # (it reads the first answer's push on the way)
        c.rpc(3)                # a push follows a reply: the next request reads it
        self.assertEqual([struct.unpack('>i', p[:4])[0] for m, p in c.pushes if m == 31], [2, 2])

    def test_the_original_level_table_keeps_each_players_level(self):
        server, c = self.reconstructed()
        self.saved_profile(c)
        server.stop()
        self.edit('test-fresh', lambda p: p.update(Exp=45000 + 4500, LevelAnnounced=10))   # level 10, half way to 11
        server = self.start('test-fresh', dict(self.RECONSTRUCTED, **self.world('revival', **{'xp.vanillaCurve': 1})))
        c = self.client(server)
        c.rpc(115)
        thresholds = {r['id']: r['exp_threshold'] for r in self.static(server)['level_ups']}
        self.assertEqual((thresholds[2], thresholds[10], thresholds[11], thresholds[40]), (1000, 27000, 33000, 3877000))
        self.assertEqual(self.player_info(c)['exp'], 27000 + 2700)                             # still 45 % of the way to 11
        server.stop()
        server = self.start('test-fresh', self.RECONSTRUCTED)                                   # and back
        c = self.client(server)
        c.rpc(115)
        self.assertEqual(self.player_info(c)['exp'], 45000 + 4500)

    def test_bags_count_quest_slots_and_trinkets(self):
        server, c = self.task_server(self.kills(1))
        self.assertEqual(self.inventory(c)['bag'], 400)                                        # Revival's start
        server.stop()
        def change(p):
            p['Story'] = dict(p.get('Story') or {'Active': [], 'Started': [], 'Finished': []}, Outputs=[1179])  # Mushrooming 1st
            p.setdefault('Story', {}).setdefault('Active', []); p['Story'].setdefault('Started', []); p['Story'].setdefault('Finished', [])
            p['Tasks']['Achievements'] = {'20011': 1790000000, '20024': 1790000000, '20001': 1790000000}
        self.edit('tasks', change)
        server, c = self.task_server(self.kills(1))
        self.assertEqual(self.inventory(c)['bag'], 400 + 400 + 200)
        # The trinkets' bonuses: an attack modifier (permanent, not removable), the journal's station.
        live = modifiers(c.rpc(91))
        self.assertEqual(live[921][1], -1)
        c.rpc(92, I(921))
        self.assertIn(921, modifiers(c.rpc(91)))
        r = Reader(c.rpc(69)); r.byte()
        stations = [struct.unpack('>qiiii', r.take(24)) for _ in range(r.integer())]
        self.assertIn((1020024, 1, -1, 0, 0), [(s[0], s[1], s[2], 0, 0) for s in stations])
        rows = [r for r in self.static(server)['player_modifier_to_effect'] if r['item_id'] == 921]
        self.assertEqual([(r['effect_id'], r['power'], r['effect_apply_type_id']) for r in rows], [(30, 20, 22)])
        # Vanilla: no trinket bonuses, the original bag.
        server.stop()
        server, c = self.task_server(self.kills(1), extra=self.world('vanilla'))
        self.assertEqual(self.inventory(c)['bag'], 200)
        self.assertNotIn(921, modifiers(c.rpc(91)))

    def test_summoning_scrolls_follow_their_descriptions(self):
        server, c = self.task_server(self.kills(1))
        server.stop()
        self.edit('tasks', lambda p: p.update(Gold=1000, Items=dict(p['Items'], summoning_scrolls={'6': 1, '4': 1})))
        server, c = self.task_server(self.kills(1))
        r = Reader(c.rpc(111, I(16) + I(6) + I(1000000) + I(1000000)))
        self.assertEqual(r.byte(), 1)
        group, = self.summoned_groups(r)
        self.assertEqual(len(group['monsters']), 5)
        self.assertTrue(all(SPECIES[m[0]]['family'] == 2 for m in group['monsters']))         # 5 random draconids
        # A legendary scroll summons a legendary at level 1 too: the level gate is the world's, a scroll names its rarity.
        r = Reader(c.rpc(111, I(16) + I(4) + I(1000000) + I(1000000)))
        self.assertEqual(r.byte(), 1)
        group, = self.summoned_groups(r)
        self.assertEqual([SPECIES[m[0]]['rarity'] for m in group['monsters']], [3])
        self.assertEqual(self.inventory(c)['scrolls'], {})
        # The shop sells them (Alchemy, beside the baits), one at a time.
        bundles = {b['id']: b for b in self.static(server)['shop_bundles']}
        self.assertEqual(bundles[5003]['gold_price'], 120)                                      # Revival's lesser scroll
        r = Reader(c.rpc(75, I(5003) + Q(42)))
        self.assertEqual(r.byte(), 1)
        self.assertEqual(self.inventory(c)['scrolls'], {3: 1})

    def test_boosters_and_weather_items_are_used_from_the_inventory(self):
        server, c = self.reconstructed()
        self.saved_profile(c)
        server.stop()
        self.edit('test-fresh', lambda p: p.update(Items=dict(p['Items'], consumables={'1': 1, '3': 1, '4': 1})))
        server, c = self.reconstructed()
        self.assertEqual(self.inventory(c)['consumables'], {1: 1, 3: 1, 4: 1})
        r = Reader(c.rpc(99, I(1)))
        ok, item, expiry = r.byte(), r.integer(), r.integer()
        self.assertEqual((ok, item), (1, 1))
        self.assertAlmostEqual(expiry, time.time() + 1800, delta=120)
        self.assertEqual(self.inventory(c)['consumables'], {3: 1, 4: 1})
        self.assertEqual(c.rpc(99, I(1))[0], 0)                                                # none left
        self.assertEqual(self.griffin(c)['exp'], 1000)                                         # +100 % while it lasts
        where = struct.pack('>ff', 12.3, 45.6)
        self.assertEqual(c.rpc(67, where), I(6))                                               # no weather service: clear
        self.assertEqual(c.rpc(99, I(3))[0], 1)
        self.assertEqual(c.rpc(67, where), I(3))                                               # rain for an hour
        self.assertEqual(c.rpc(99, I(4))[0], 1)
        self.assertEqual(c.rpc(67, where), I(5))                                               # fog replaces it
        live = modifiers(c.rpc(91))
        self.assertIn(22, live)                                                                # the original fog modifier id
        self.assertNotIn(12, live)
        consumables = {r['id']: r for r in self.static(server)['consumables']}
        self.assertEqual((consumables[1]['slug'], consumables[1]['duration']), ('xp_booster', 1800))

    def test_packs_open_from_the_inventory(self):
        server, c = self.reconstructed()
        self.saved_profile(c)
        server.stop()
        self.edit('test-fresh', lambda p: p.update(Items=dict(p['Items'], friend_packs={'1': 3})))
        server, c = self.reconstructed()
        before = self.inventory(c)['ingredients']
        reply = Reader(c.rpc(109, I(1) + I(2)))                                              # Remove, named Open: two packs
        self.assertEqual((reply.byte(), reply.integer(), reply.integer()), (1, 1, 2))
        found = {}
        for _ in range(reply.integer()):                       # what they held (the game leaves it unread; hook.js shows it)
            item_type, item, amount = reply.integer(), reply.integer(), reply.integer()
            self.assertEqual(item_type, 1)                                                     # Revival's pack: ingredients
            found[item] = amount
        self.assertEqual(reply.pos, len(reply.data))
        self.assertIn(sum(found.values()), range(6, 25))                                       # three draws a pack, 1-4 each
        after = self.inventory(c)['ingredients']
        self.assertEqual({i: after.get(i, 0) - before.get(i, 0) for i in after if after.get(i, 0) != before.get(i, 0)}, found)
        with urllib.request.urlopen(f'http://127.0.0.1:{server.http}/revival/texts', timeout=2) as response:
            texts = json.loads(response.read())
        self.assertEqual(texts['replace']['REVIVAL/OPEN_PACK']['en'], 'Open')
        self.assertEqual(texts['append']['ITEMS/DESCRIPTIONS/PACKS/PACK_HERBALIST']['en'], '\nNow and then it also holds rarer finds.')
        # Vanilla: Remove throws the pack away, the button keeps its name, and the pack (herbs or roots) its description
        server.stop()
        server, c = self.reconstructed(env=self.world('vanilla'))
        self.assertEqual(c.rpc(109, I(1) + I(1)), b'\1' + I(1) + I(1))
        self.assertEqual(self.inventory(c)['ingredients'], after)
        with urllib.request.urlopen(f'http://127.0.0.1:{server.http}/revival/texts', timeout=2) as response:
            texts = json.loads(response.read())
        self.assertNotIn('REVIVAL/OPEN_PACK', texts['replace'])
        self.assertNotIn('ITEMS/DESCRIPTIONS/PACKS/PACK_HERBALIST', texts['append'])

    def test_deflects_pay_as_perfect_parries_only_on_revival(self):
        # With Hit Reflection the game counts every perfect parry as a deflect (Details[3]): Revival pays them as parries.
        details = [0] * 13
        details[11], details[3] = 3, 2
        body = bytes([1]) + I(13) + b''.join(I(v) for v in details) + b'\0'
        for preset, values, parry in (('revival', {}, 75), ('vanilla', {}, 45), ('revival', {'xp.perfectParry': 30}, 150)):
            with self.subTest(preset=preset, values=values):
                server, c = self.reconstructed(f'test-parry-{preset}-{len(values)}', env=self.world(preset, **values))
                r = Reader(c.rpc(111, I(16) + I(1) + I(1) + I(1)))
                self.assertEqual(r.byte(), 1)
                group, = self.summoned_groups(r)
                self.assertEqual(c.rpc(113, Q(group['monsters'][0][1])), b'\1')
                self.assertEqual(self.combat_end(Reader(c.rpc(114, body)))['parry'], parry)
                server.stop()

    def test_potions_and_oils_last_half_an_hour_in_their_slots(self):
        # Tuning combat.lastingMinutes (Revival 30, Vanilla 0): a potion or oil spent on a fight becomes a modifier with the item's
        # own effects, kept out of the game's modifiers during the fight it was taken for (that fight has it already). At the
        # fight's end the game is given each one as AddPlayerModifier's reply (90), which puts it in the effects panel.
        def fight(c):
            r = Reader(c.rpc(111, I(16) + I(1) + I(1) + I(1)))
            self.assertEqual(r.byte(), 1)
            group, = self.summoned_groups(r)
            self.assertEqual(c.rpc(113, Q(group['monsters'][0][1])), b'\1')
            c.rpc(114, bytes([1]) + I(13) + I(0) * 13 + b'\0')
        for preset in ('revival', 'vanilla'):
            with self.subTest(preset=preset):
                name = 'test-lasting-' + preset
                server, c = self.reconstructed(name, env=self.world(preset))
                if preset == 'revival':
                    data = self.static(server)
                    self.assertIn({'id': 10201, 'slug': 'lasting_potion_thunderbolt'}, data['player_modifiers'])
                    own = [dict(r, item_id=10201) for r in data['potion_to_effect'] if r['item_id'] == 201]
                    self.assertEqual([r for r in data['player_modifier_to_effect'] if r['item_id'] == 10201], own)
                    self.assertTrue(any(r['item_id'] == 10302 for r in data['player_modifier_to_effect']))
                self.saved_profile(c)
                server.stop()
                self.edit(name, lambda p: p.update(Items=dict(p['Items'], potions={'201': 3, '202': 3}, oils={'301': 2, '302': 2})))
                c = self.client(self.start(name, dict(self.RECONSTRUCTED, **self.world(preset))))
                c.rpc(119)   # the post-sync gate: from here the session gets pushes
                lasting = lambda: {k: v for k, v in modifiers(c.rpc(91)).items() if k >= 10000}
                def added():
                    pushed = [struct.unpack('>5i', body) for method, body in c.pushes if method == 90]
                    c.pushes.clear()
                    return {m: (start, expire) for _, result, m, start, expire in pushed if result == 0}
                self.assertEqual(c.rpc(89, I(301) + I(1) + I(201)), b'\1')   # Thunderbolt and the basic oil for a fight
                self.assertEqual(lasting(), {})
                c.pushes.clear()
                fight(c)
                if preset == 'vanilla':
                    self.assertEqual(lasting(), {})
                    self.assertEqual(added(), {})
                    continue
                after = lasting()
                self.assertEqual(set(after), {10201, 10301})
                self.assertAlmostEqual(after[10201][1], time.time() + 1800, delta=60)
                self.assertEqual(added(), {m: (after[m][0], after[m][1]) for m in after})
                # One potion slot: Swift replaces Thunderbolt, and the necrophage oil the basic one
                self.assertEqual(c.rpc(89, I(302) + I(1) + I(202)), b'\1')
                self.assertEqual(lasting(), {})
                self.griffin(c)   # a story fight, ended by its graph (EndBehaviourGraph)
                self.assertEqual(set(lasting()), {10202, 10302})
                self.assertEqual(set(added()), {10202, 10302})

    def test_a_won_fight_pays_orens_by_rarity_and_difficulty(self):
        # Tuning rewards.fightGold* (Revival 3-7, 10-15 and 20-25 orens by rarity and 25 % more a difficulty tier, Vanilla
        # none), into the purse, and pushed (2003) to a game with the hook, which shows them in the fight's summary.
        for preset in ('revival', 'vanilla'):
            with self.subTest(preset=preset):
                server, c = self.task_server(self.kills(1), name='orens-' + preset, extra=self.world(preset))
                c.rpc(2002)   # the hook's own request (a skill reset, nothing to give back): this game has the hook
                r = Reader(c.rpc(111, I(16) + I(1) + I(1000000) + I(1000000)))
                self.assertEqual(r.byte(), 1)
                group, = self.summoned_groups(r)
                monster, instance, _ = group['monsters'][0]
                self.assertEqual(c.rpc(113, Q(instance)), b'\1')
                before = self.player_info(c)['gold']
                c.pushes.clear()
                c.rpc(114, bytes([1]) + I(13) + I(0) * 13 + b'\0')
                orens = self.player_info(c)['gold'] - before
                pushed = [struct.unpack('>i', body)[0] for method, body in c.pushes if method == 2003]
                least, most = base.fight_orens(monster)
                if preset == 'vanilla':
                    self.assertEqual((orens, pushed), (0, []))
                else:
                    self.assertTrue(least <= orens <= most, orens)
                    self.assertEqual(pushed, [orens])
                server.stop()

    def test_the_hook_texts_follow_the_preset(self):
        server, c = self.task_server(self.kills(1))
        with urllib.request.urlopen(f'http://127.0.0.1:{server.http}/revival/texts', timeout=2) as response:
            texts = json.loads(response.read())
        silver = texts['replace']['MONSTERS/DESCRIPTIONS/BASILISKWHITE/INFO_2']
        self.assertEqual(silver, '[0{**UI/PANELS/BESTIARY/OCCURANCE**}0]: ' + ''.join(
            f'**MONSTERS/OCCURANCE/{t}**\n' for t in SPECIES[110]['tags']))
        # the server's own texts come in the game's nine languages
        lizard = texts['append']['ACHIEVEMENTS/DESCRIPTIONS/TROPHY_LIZARD_SLAYER']
        self.assertEqual(set(lizard), {'en', 'pl', 'de', 'es', 'it', 'fr', 'ru', 'pt', 'ja'})
        self.assertEqual(lizard['en'], '\nBonus: +20% experience and +20% attack against draconids')
        self.assertEqual(lizard['pl'], '\nPremia: +20% doświadczenia i +20% do ataku przeciw drakonidom')
        self.assertEqual(texts['replace']['NOTIFICATIONS/EFFECT/TROPHY_LIZARD_SLAYER']['de'],
                         'Echsenschlächter: +20 % Angriff gegen Drakoniden')
        self.assertEqual(texts['replace']['ITEMS/NAMES/CONSUMABLES/INTERACTION_BOOSTER']['en'], 'Rain Charm')
        self.assertEqual(texts['replace']['UI/PANELS/COMBAT_END/FIGHT_DURATION']['pl'], 'Złote monety')   # the orens line
        # the lasting potions' and oils' names: the game's own terms, which hook.js looks up
        self.assertEqual(texts['alias']['NOTIFICATIONS/EFFECT/LASTING_POTION_THUNDERBOLT'], 'ITEMS/NAMES/POTIONS/POTION_THUNDERBOLT')
        self.assertEqual(texts['alias']['NOTIFICATIONS/EFFECT/LASTING_OIL_BASIC'], 'ITEMS/NAMES/OILS/OIL_BASIC')
        self.assertFalse(any('**' in term for term in texts['alias'].values()))
        self.assertEqual(texts['replace']['REVIVAL/OPEN_PACK_HEADER']['fr'], 'Voulez-vous ouvrir cet <nobr>objet :</nobr> <nobr>#0 ?</nobr>')
        for term, text in list(texts['replace'].items()) + list(texts['append'].items()):
            if isinstance(text, dict):
                self.assertTrue(all(text.values()), term)
        # the settings hook.js applies in the game (Revival); the oils multiply, so their descriptions stay
        self.assertEqual(texts['settings'], {'combat.oilsMultiply': 1, 'quests.collectingDistance': 100,
                                             'quests.collectingUntracked': 1, 'quests.intruderAllEndings': 1,
                                             'skills.reset': 1, 'xp.deflectsAsParries': 1, 'combat.quenPerfectParry': 1,
                                             'tasks.perfectParriesAsParries': 1})
        self.assertFalse(any(k.startswith('ITEMS/DESCRIPTIONS/OILS/') for k in texts['append']))
        server.stop()
        server, c = self.task_server(self.kills(1), extra=self.world('vanilla', **{'spawns.wikiOccurrences': 0}))
        with urllib.request.urlopen(f'http://127.0.0.1:{server.http}/revival/texts', timeout=2) as response:
            texts = json.loads(response.read())
        self.assertFalse(any(k.startswith('MONSTERS/') for k in texts['replace']))
        self.assertNotIn('UI/PANELS/COMBAT_END/FIGHT_DURATION', texts['replace'])   # Vanilla fights pay no orens
        self.assertEqual(texts['alias'], {})   # nor do its potions last
        # the original sum of bonuses: each oil's description says what its bonus is a share of
        oils = ['BASIC', 'NECROPHAGE', 'OGROID', 'CURSED', 'RELICT', 'HYBRID', 'INSECTOID', 'DRACONID', 'SPECTER', 'ELEMENTAL', 'VAMPIRE']
        self.assertEqual(set(texts['append']), {'ITEMS/DESCRIPTIONS/OILS/OIL_' + oil for oil in oils})
        self.assertTrue(texts['append']['ITEMS/DESCRIPTIONS/OILS/OIL_BASIC']['en'].startswith("\nIts bonus is a share of the sword's base"))
        self.assertEqual(texts['settings'], {'combat.oilsMultiply': 0, 'quests.collectingDistance': 200,
                                             'quests.collectingUntracked': 0, 'quests.intruderAllEndings': 0,
                                             'skills.reset': 0, 'xp.deflectsAsParries': 0, 'combat.quenPerfectParry': 0,
                                             'tasks.perfectParriesAsParries': 0})

    def test_the_blacksmiths_sharpening_raises_melee_damage(self):
        # s01_blacksmith (id 1), which his story graph adds for an hour: ImproveAttackPower (41), Tuning combat.blacksmithDamage
        for amount in (10, 25):
            with self.subTest(amount=amount):
                server = self.start(f'test-smith-{amount}', dict(self.RECONSTRUCTED, **self.world(**{'combat.blacksmithDamage': amount})))
                rows = self.static(server)['player_modifier_to_effect']
                self.assertEqual([(r['effect_id'], r['power']) for r in rows if r['item_id'] == 1], [(41, amount)])
                server.stop()

    def test_quen_absorbs_its_share_of_a_blow(self):
        # The game starts Quen's shield at nothing (Player.ShieldModifier 0, a blow passes 1 - it), so the Quen skill carries
        # ImproveQuenAbsorb (69, power / 100): Tuning skills.quenAbsorb, Revival 100, Vanilla 70.
        for preset, share in (('revival', 100), ('vanilla', 70)):
            with self.subTest(preset=preset):
                server = self.start('test-quen-' + preset, dict(self.RECONSTRUCTED, **self.world(preset)))
                data = self.static(server)
                quen = next(s['id'] for s in data['skills'] if s['slug'] == 'quen_sign')
                rows = [(r['effect_id'], r['power']) for r in data['skill_to_effect'] if r['item_id'] == quen]
                self.assertIn((69, share), rows)
                server.stop()

    def test_bestiary_tiers_follow_the_tuning(self):
        # Each tier's row carries the kills since the previous tier: Revival 3/25/100, Vanilla (before 1.2) 3/50/150.
        for preset, expected in (('revival', {1: 3, 2: 22, 3: 75}), ('vanilla', {1: 3, 2: 47, 3: 100})):
            server = self.start('test-' + preset, dict(self.RECONSTRUCTED, **self.world(preset)))
            rows = self.static(server)['monster_descriptions']
            self.assertEqual({r['level']: r['threshold'] for r in rows if r['monster_id'] == 1}, expected)   # the ghoul
            server.stop()


def load_tests(loader, tests, pattern):
    # Only this module's own tests: the base classes' tests run in their own modules.
    return unittest.TestSuite(RebalanceTests(name) for name in loader.getTestCaseNames(RebalanceTests)
                              if name in RebalanceTests.__dict__)


if __name__ == '__main__':
    unittest.main()
