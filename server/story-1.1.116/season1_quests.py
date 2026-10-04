"""Season 1 quest overlay: what the client graphs do not say.

The graphs (season1_graphs.py) give each node's outputs, the facts every output sets, the fights and the queued
nodes. This overlay adds, per quest, the decisions the lost server data held:
  - which graphs are map POIs, quest givers, queued nodes or journal buttons, with their POI settings;
  - when a node shows, as a condition on facts the graphs set (the journal's progress facts), on outputs already
    reached, or on the time since an output;
  - which outputs end the quest and what the quest pays;
  - a walk-through for the tests: outputs in order, with the facts the graphs send, and the nodes then on the map.

Conditions: `|` separates alternatives, `&` joins atoms. Atoms: `f<fact><op><value>` (op = = != < <= > >=, a missing
fact is 0), `out:<node>.<output>` (reached), `wait:<node>.<output>:<seconds>` (reached that long ago), `done:<quest>`
(finished), `started:<quest>`, each negated with a leading `!`. A giver's root criteria are fact conditions only;
the client row carries the first one (the client evaluates a single expression) and the server checks them all.

Evidence: Client (graphs, journals, POI settings, localisation), Community (Gamepressure walkthroughs, 2021) or
Authored, as noted per quest.
"""

POI = "assets/_bundledassets/story/poi_settings/"

# LAB pacing (Authored, at the player's request, 30 September 2026): the long real-time waits of season 1 last 24
# minutes instead of hours. Client: the graphs' AddExpiringEffect times are 43200 s (modifier 7, Vesemir's remedy)
# and 86400 s (modifier 3, the mushroom hunt; modifier 6, the Intruder's solvent); Community (Gamepressure): Vesemir
# wakes after 12 hours, the mushroom contest ends after a day. The server serves the nodes after LAB_WAIT and answers
# AddPlayerModifier for these modifiers with LAB_WAIT, so the client's timers show the same time.
LAB_WAIT = 24 * 60
MODIFIER_SECONDS = {7: LAB_WAIT, 3: LAB_WAIT, 6: LAB_WAIT}
EMPTY = POI + "_common/empty.asset"
TRACKS = POI + "s00/prolog/footprint_placeholder.asset"


def node(key, graph, poi=None, kind="poi", show="", root="", band=None, near=None, place_of=None, node_id=None,
         copies=1, button_id=None):
    return {"key": key, "graph": graph, "poi": poi, "kind": kind, "show": show, "root": root, "band": band,
            "near": near, "place_of": place_of, "id": node_id, "copies": copies, "button_id": button_id}


def items(**kinds):
    return {kind: {str(k): v for k, v in m.items()} for kind, m in kinds.items()}


QUESTS = [
    # ── Good Money (s01mq01). Community (Gamepressure, 19 Aug 2021): 1200 XP and 40 gold; the figurine pays 60
    # (Client: fact 175 = 60 with the gold notice). Unlocks the side quests (facts 1000, 1001, 1003).
    {"id": 149, "code": "s01mq01", "name": "Good Money", "folder": "s01mq01_scholar", "criteria": "f100>=4",
     "nodes": [
         node("s01mq01_margit", "s01mq01_scholar_01", POI + "s01/mq01/scholar_lq.asset", "giver", root="f53<1", node_id=11491),
         node("s01mq01_cocoon_1", "s01mq01_cocoon_01", POI + "s01/mq01/endrega_cocoon_lq.asset", show="f53=1", band=(300, 800)),
         node("s01mq01_cocoon_2", "s01mq01_cocoon_02", POI + "s01/mq01/endrega_cocoon_lq.asset", show="f53=2", near="s01mq01_cocoon_1",
              band=(40, 150), node_id=11492),
         node("s01mq01_margit_2", "s01mq01_scholar_02", POI + "s01/mq01/scholar_lq.asset", show="f53=3", place_of="s01mq01_margit",
              node_id=11493),
     ],
     "end": {"s01mq01_margit_2.scholar_02": {"exp": 1200, "gold": 40}},
     "walk": [
         ("s01mq01_margit", "scholar_01", {53: 1, 175: 60}, ["s01mq01_cocoon_1"]),
         ("s01mq01_cocoon_1", "endriagaworker_01", {1: 1}, ["s01mq01_cocoon_1"]),
         ("s01mq01_cocoon_1", "endriagaworker_02", {1: 2}, ["s01mq01_cocoon_1"]),
         ("s01mq01_cocoon_1", "dehael", {1: 4, 53: 2}, ["s01mq01_cocoon_2"]),
         ("s01mq01_cocoon_2", "endriagaworker", {1: 5}, ["s01mq01_cocoon_2"]),
         ("s01mq01_cocoon_2", "endriagatailed", {1: 6}, ["s01mq01_cocoon_2"]),
         ("s01mq01_cocoon_2", "embrions", {53: 3, 50: 1}, ["s01mq01_margit_2"]),
         ("s01mq01_margit_2", "scholar_02", {53: 4, 1000: 1, 1001: 1, 1003: 1, 31: 1}, []),
     ]},

    # ── Evil Never Sleeps (s01mq04, "Licho nadało"). Client: progress fact 72 (1 contract, 2 arachnomorphs killed,
    # 3 cursed amulet, 4 journal read, 5 mixture made, 6 likho killed), ingredients 73 (moss) and 74 (hemlock),
    # amulet thrown 75. Community (Gamepressure): Bedwyr sends you after spiders, the amulet curses you, two
    # ingredients, the campfire summons the likho, back to Bedwyr; 250 XP and 35 gold. Authored: the hound's POI
    # (footprints; no hound settings exist), places, 'no_reward' pays no gold.
    {"id": 104, "code": "s01mq04", "name": "Evil Never Sleeps", "folder": "s01mq04_cursed_one", "criteria": "f1001>=1",
     "nodes": [
         node("s01mq04_bedwyr", "s01mq04_cursedone_01", POI + "s01/mq04/cursed_one_lq.asset", "giver", root="f72<1"),
         node("s01mq04_nest", "s01mq04_nest", POI + "s01/mq04/arachnomorph_lq.asset", show="f72=1", band=(300, 800)),
         node("s01mq04_bedwyr_curse", "s01mq04_cursedone_02", POI + "s01/mq04/cursed_one_lq.asset", show="f72=2",
              place_of="s01mq04_bedwyr"),
         node("s01mq04_hemlock", "s01mq04_herb_01", POI + "s01/mq04/water_hemlocks_lq.asset", show="f72=4 & f74<1", band=(200, 650)),
         node("s01mq04_hound", "s01mq04_leshen_hound_01", TRACKS, show="f72=4 & f73<1", band=(200, 650)),
         node("s01mq04_campfire", "s01mq04_licho_01", POI + "s01/mq04/camp_fire_2_lq.asset", show="f72=5", band=(150, 500)),
         node("s01mq04_bedwyr_end", "s01mq04_cursedone_03", POI + "s01/mq04/cursed_one_cured_lq.asset", show="f72=6 & f75>=1",
              place_of="s01mq04_bedwyr"),
         node("s01mq04_journal", "quest_item_buttons/qi_journal", kind="button"),
         node("s01mq04_journal_craft", "quest_item_buttons/qi_journal_button", kind="button", node_id=218),
         node("s01mq04_amulet", "quest_item_buttons/qi_amulet_button", kind="button", node_id=222),
         node("s01mq04_amulet_1", "quest_item_buttons/qi_amulet_button_1", kind="button", node_id=224),
         node("s01mq04_amulet_2", "quest_item_buttons/qi_amulet_button_2", kind="button", node_id=223),
     ],
     "end": {"s01mq04_bedwyr_end.final": {"exp": 250, "gold": 35}, "s01mq04_bedwyr_end.no_reward": {"exp": 250}},
     "walk": [
         ("s01mq04_bedwyr", "start", {72: 1}, ["s01mq04_nest"]),
         ("s01mq04_nest", "arachnomorph_01", {35: 1}, ["s01mq04_nest"]),
         ("s01mq04_nest", "nest", {72: 2}, ["s01mq04_bedwyr_curse"]),
         ("s01mq04_bedwyr_curse", "curse_start", {72: 3, 82: 1, 80: 1}, []),
         ("s01mq04_journal", "read", {72: 4}, ["s01mq04_hemlock", "s01mq04_hound"]),
         ("s01mq04_hemlock", "herb", {74: 1, 80: 2}, ["s01mq04_hound"]),
         ("s01mq04_hound", "hound_killed", {73: 1, 80: 4}, []),
         ("s01mq04_journal_craft", "journal", {72: 5, 80: 5, 81: 1}, ["s01mq04_campfire"]),
         ("s01mq04_campfire", "licho_killed", {72: 6, 82: 4}, []),
         ("s01mq04_amulet_2", "amulet", {75: 1, 82: 0}, ["s01mq04_bedwyr_end"]),
         ("s01mq04_bedwyr_end", "final", {31: 2}, []),
     ]},

    # ── To The Rescue (s01hq05, "W sukurs"). Client: Kienan's dialogue (s01hq05_bandit) sets the journal fact
    # 143 = 1 and 65 = 1 when Geralt helps ('help'); 'no_help' refuses and his second dialogue (bandit_again)
    # helps (10148 = 1) or ends it (143 = 2); the pit (wife) ends with 23 = 2, 121 = 2..5 and 143 = 3..6; the bribe
    # path leaves the actor's key (200 = 1) for the treasure. Community (Gamepressure): meet Kienan, the pit holds a devourer, kill or spare
    # him; 250 XP and 45 gold. Authored: Kienan asks again half an hour after a refusal; places.
    {"id": 148, "code": "s01hq05", "name": "To The Rescue", "folder": "s01hq05_bandit_and_devourer", "criteria": "f1001>=1",
     "nodes": [
         node("s01hq05_kienan", "s01hq05_bandit", POI + "s01/hq05/actor_lq.asset", "giver", root="f65<1 & f143<1"),
         node("s01hq05_kienan_again", "s01hq05_bandit_again", POI + "s01/hq05/actor_lq.asset",
              show="wait:s01hq05_kienan.no_help:1800 & f143<1 & !out:s01hq05_kienan_again.help & !out:s01hq05_kienan_again.end",
              place_of="s01hq05_kienan"),
         node("s01hq05_pit", "s01hq05_wife", POI + "s01/hq05/bandit_wife_lq.asset", show="f143=1 & f121<1 | out:s01hq05_kienan_again.help & f121<1",
              band=(300, 800)),
         node("s01hq05_treasure", "s01hq05_treasure", POI + "s01/hq05/treasure_placeholder.asset", show="f200=1", band=(200, 600)),
     ],
     "end": {"s01hq05_pit.actor_free": {"exp": 250, "gold": 45}, "s01hq05_pit.actor_escape": {"exp": 250, "gold": 45},
             "s01hq05_pit.actor_dead": {"exp": 250, "gold": 45}, "s01hq05_treasure.treasure": {"exp": 250, "gold": 45},
             "s01hq05_kienan_again.end": {}},
     "walk": [
         ("s01hq05_kienan", "help", {65: 1, 143: 1, 10148: 1}, ["s01hq05_pit"]),
         ("s01hq05_pit", "devourer", {}, ["s01hq05_pit"]),
         ("s01hq05_pit", "actor_bribe", {23: 2, 121: 4, 143: 6, 200: 1, 10148: 2}, ["s01hq05_treasure"]),
         ("s01hq05_treasure", "treasure", {187: 1, 200: 0}, []),
     ]},

    # ── Pride Ain't Cheap (s01mq02, "Słona cena pychy"). Client: progress fact 54 (1 witcher found, 2 Varik's
    # errand, 3 remedy brewing, 4 Vesemir awake), saliva/root 29 (1 saliva, 3 root), the decoction 28; Varik's
    # remedy adds the 12 h modifier 7 and Vesemir wakes after it. Community (Gamepressure): 250 XP, 2 Swallows and
    # an Insectoid Oil; "give him 12 hours". Authored: places.
    {"id": 150, "code": "s01mq02", "name": "Pride Ain't Cheap", "folder": "s01mq02_cure", "criteria": "f1001>=1",
     "nodes": [
         node("s01mq02_witcher", "s01mq02_witcher", POI + "s01/mq02/young_vesemir_meditating_lq.asset", "giver", root="f54<1"),
         node("s01mq02_varik", "s01mq02_medic_01", POI + "s01/mq02/medic_lq.asset", show="f54=1", band=(250, 700)),
         node("s01mq02_drowner", "s01mq02_drowner", POI + "s01/mq02/drowner_lq.asset", show="f54=2 & f29<1", band=(200, 650)),
         node("s01mq02_plant", "s01mq02_plant", POI + "s01/mq02/poisonous_plant.asset", show="f54=2 & f29=1", band=(200, 650)),
         node("s01mq02_varik_2", "s01mq02_medic_02", POI + "s01/mq02/medic_lq.asset", show="f54=2 & f29>=3",
              place_of="s01mq02_varik"),
         node("s01mq02_vesemir", "s01mq02_medic_03", POI + "s01/mq03/youngvesemir_lq.asset",
              show=f"f54=3 & wait:s01mq02_varik_2.medic_02:{LAB_WAIT}", place_of="s01mq02_varik"),
         node("s01mq02_potion", "quest_item_buttons/qi_potion_button", kind="button", node_id=304),
     ],
     "end": {"s01mq02_vesemir.vesemir": {"exp": 250, "items": items(potions={205: 2}, oils={307: 1})}},
     "walk": [
         ("s01mq02_witcher", "witcher", {54: 1, 52: 1}, ["s01mq02_varik"]),
         ("s01mq02_varik", "medic_01", {54: 2, 28: 1}, ["s01mq02_drowner"]),
         ("s01mq02_drowner", "drowner", {28: 2, 29: 1}, ["s01mq02_plant"]),
         ("s01mq02_potion", "potion", {28: -1}, ["s01mq02_plant"]),
         ("s01mq02_plant", "scolo_again", {29: 3}, ["s01mq02_varik_2"]),
         ("s01mq02_varik_2", "medic_02", {54: 3, 29: -1}, []),
         ("wait", LAB_WAIT),
         (None, None, None, ["s01mq02_vesemir"]),
         ("s01mq02_vesemir", "vesemir", {54: 4, 31: 3}, []),
     ]},

    # ── What Lurks in the Nemeta (s01hq02, "Co się kryje w nemetach"). Client: progress fact 47 (1 nemeton cleared
    # with the notebook, 2 notes read, 3 met the partner at the well, 4 missed); the quest opens with fact 1003
    # (set by Good Money, cleared by the nemeton graph). Community (Gamepressure): found at a nemeton, meet the
    # partner at sunset; 250 XP and 100 gold. Authored: the nemeton giver uses the map nest prefab; the three-day
    # miss is not timed.
    {"id": 159, "code": "s01hq02", "name": "What Lurks in the Nemeta", "folder": "s01hq02_nests", "criteria": "f1003>=1",
     "nodes": [
         node("s01hq02_nemeton", "s01hq02_nest", POI + "s01/mq05/nest_lq.asset", "giver", root="f47<1"),
         node("s01hq02_notebook", "quest_item_buttons/qi_notebook", kind="button"),
         node("s01hq02_notebook_button", "quest_item_buttons/qi_notebook_button", kind="button"),
         node("s01hq02_well", "s01hq02_scholar", POI + "s01/hq02/scholar_well.asset", show="f47=2", band=(250, 700)),
     ],
     "end": {"s01hq02_well.scholar": {"exp": 250, "gold": 100}},
     "walk": [
         ("s01hq02_nemeton", "nest", {47: 1, 1003: 0}, []),
         ("s01hq02_notebook", "notebook", {47: 2}, ["s01hq02_well"]),
         ("s01hq02_well", "scholar", {47: 3}, []),
     ]},

    # ── The Dark Side Of The Full Moon (s01hq03, "Ciemna strona pełni"). Client: Lothar the blacksmith (node 289)
    # finds his forge empty on a full moon (AstroCondition in the graph; 119 = 1, TRACK 147); tracks set 119 = 2;
    # the werewolf (291) is killed (141 = 2, map found: 46 = 1) or spared (141 = 4); Lothar's farewell (464) or
    # the new blacksmith (381) end it; both can hand over the Sword in the Stone map (queue 399). Community
    # (Gamepressure): 350 XP. Authored: the hunt resets on 'too_late' (119 = 0) to the forge.
    {"id": 147, "code": "s01hq03", "name": "The Dark Side Of The Full Moon", "folder": "s01hq03_blacksmith",
     "criteria": "f1001>=1",
     "nodes": [
         node("s01hq03_lothar", "s01hq03_blacksmith", POI + "_common/blacksmith_lq.asset", "giver", root="f119<1"),
         node("s01hq03_forge", "s01hq03_blacksmith", POI + "_common/blacksmith_lq.asset", show="f119=0 & f141<2",
              place_of="s01hq03_lothar"),
         node("s01hq03_tracks", "s01hq03_tracks", TRACKS, show="f119=1", band=(200, 600)),
         node("s01hq03_werewolf", "s01hq03_werewolf", POI + "s01/hq03/werewolf_lq.asset", show="f119=2", band=(300, 800)),
         node("s01hq03_farewell", "s01hq03_blacksmith_final", POI + "_common/blacksmith_lq.asset", show="f141=4 & f119<3",
              place_of="s01hq03_lothar"),
         node("s01hq03_new_smith", "s01hq03_new_smith", POI + "_common/new_blacksmith_lq.asset", show="f141=2 & f64<1",
              place_of="s01hq03_lothar"),
     ],
     "end": {"s01hq03_farewell.blacksmith": {"exp": 350}, "s01hq03_farewell.blacksmith_map": {"exp": 350},
             "s01hq03_new_smith.new_blacksmith": {"exp": 350}},
     "walk": [
         ("s01hq03_lothar", "full_moon_01", {119: 1, 131: 2}, ["s01hq03_tracks"]),
         ("s01hq03_tracks", "tracks", {119: 2}, ["s01hq03_werewolf"]),
         ("s01hq03_werewolf", "werewolf_dead", {46: 1, 119: 0, 141: 2, 172: 3}, ["s01hq03_new_smith"]),
         ("s01hq03_new_smith", "new_blacksmith", {64: 1, 116: 10}, []),
     ]},

    # ── Sword in the Stone (s01hq01, "Miecz w skale"). Client: the map comes from the blacksmith quest (fact 46 = 1,
    # 172 = 1..4) and the graph that shows it is queued as node 399 (s01hq01_map); the journal's "Examine" button
    # (node 400) sets 46 = 2 and the stone (385) appears; the name is learnt at dusk and spoken at dawn
    # (AstroCondition in the graph), then the golem is fought. Community (Gamepressure): dusk and dawn in real time.
    # Authored: 500 XP (no published reward), the map node stands beside the player.
    {"id": 158, "code": "s01hq01", "name": "Sword in the Stone", "folder": "s01hq01_sword_in_stone", "criteria": "f46>=1",
     "nodes": [
         node("s01hq01_map", "s01hq01_map", EMPTY, "queued", show="f46=1 & !started:158 & !done:158"),
         node("s01hq01_map_button", "quest_item_buttons/qi_map_button", kind="button", node_id=400),
         node("s01hq01_stone", "s01hq01_sword_in_stone", POI + "s01/hq01/quest_golem_alt.asset", show="f46=2", band=(300, 800)),
     ],
     # Community (Witcher Wiki; Game Rant, 27 Nov 2021): the quest gives the Dawnbringer sword (swords row 17).
     "end": {"s01hq01_stone.sword": {"exp": 500, "items": items(swords={17: 1})}},
     "walk": [
         ("s01hq01_map", "map", {46: 1, 10158: 1}, []),
         ("s01hq01_map_button", "map_button", {46: 2}, ["s01hq01_stone"]),
         ("s01hq01_stone", "inscription", {10158: 5}, ["s01hq01_stone"]),
         ("s01hq01_stone", "golem", {42: -1, 183: 1}, ["s01hq01_stone"]),
         ("s01hq01_stone", "sword", {}, []),
     ]},

    # ── Monster Slayer (s01hq06, "Pogromca potworów"). Client: the troll Pryk (node 395) asks for help (144 = 1)
    # or fights; the cave (396) is investigated; blaming the bandits ends at the cave (41 = 3/4), blaming the
    # nekker shaman leads to the fleder (144 = 5). Community (Gamepressure): from a stone troll; the reward is a
    # choice (grey stones or gold). Authored: 350 XP (+100 gold on the fleder endings), the troll stands by the
    # cave (no troll POI settings), the random-troll attack (474) is not served.
    {"id": 161, "code": "s01hq06", "name": "Monster Slayer", "folder": "s01hq06_trolling", "criteria": "f1000>=1",
     "nodes": [
         node("s01hq06_troll", "s01hq06_conversation", POI + "s01/hq06/troll_corpse_lq.asset", "giver", root="f144<1"),
         node("s01hq06_cave", "s01hq06_investigation", POI + "s01/hq06/troll_corpse_lq.asset", show="f144=1 & !out:s01hq06_cave.fleder",
              band=(300, 800)),
         node("s01hq06_fleder", "s01hq06_fleder", POI + "s01/hq06/fleder_lq.asset", show="out:s01hq06_cave.fleder & f144<5",
              band=(200, 650)),
     ],
     "end": {"s01hq06_troll.refuse": {}, "s01hq06_troll.won": {"exp": 350}, "s01hq06_troll.lost": {"exp": 350},
             "s01hq06_cave.won": {"exp": 350}, "s01hq06_cave.lost": {"exp": 350},
             "s01hq06_fleder.won": {"exp": 350, "gold": 100}, "s01hq06_fleder.grey_rocks": {"exp": 350, "gold": 100}},
     "walk": [
         ("s01hq06_troll", "help", {144: 1, 1000: 2}, ["s01hq06_cave"]),
         ("s01hq06_cave", "fleder", {10161: 2}, ["s01hq06_fleder"]),
         ("s01hq06_fleder", "nekker_shaman", {1000: 0, 10161: 4}, ["s01hq06_fleder"]),
         ("s01hq06_fleder", "grey_rocks", {144: 5}, []),
     ]},

    # ── Will O' The Wisp (s01hq04, "Błędny ognik"). Client: a nemeton (390, firefly nest with its event graph and a
    # fake nest fight) releases the wisp (120 = 1, 100 gold by fact 175); the stump (446), the plant (393) and the
    # treasure (394, 120 = 2) follow. Community (Gamepressure): three points, 250 XP and 100 gold. Authored: the
    # points appear one after another, 150-400 m apart, without the 15-minute limit.
    {"id": 160, "code": "s01hq04", "name": "Will O' The Wisp", "folder": "s01hq04_firefly", "criteria": "f1001>=1",
     "nodes": [
         node("s01hq04_nemeton", "s01hq04_firefly", POI + "s01/hq04/firefly_nest_lq.asset", "giver", root="f120<1"),
         node("s01hq04_stump", "s01hq04_stump", POI + "s01/hq04/firefly_stump_lq.asset",
              show="f120=1 & !out:s01hq04_stump.stump", near="s01hq04_nemeton", band=(150, 400)),
         node("s01hq04_plant", "s01hq04_catch", POI + "s01/hq04/firefly_plant_lq.asset",
              show="out:s01hq04_stump.stump & !out:s01hq04_plant.catch", near="s01hq04_stump", band=(150, 400)),
         node("s01hq04_treasure", "s01hq04_treasure", POI + "s01/hq04/firefly_treasure_lq.asset",
              show="out:s01hq04_plant.catch", near="s01hq04_plant", band=(150, 400)),
     ],
     "end": {"s01hq04_treasure.treasure": {"exp": 250}},
     "walk": [
         ("s01hq04_nemeton", "firefly", {120: 1, 175: 100}, ["s01hq04_stump"]),
         ("s01hq04_stump", "stump", {}, ["s01hq04_plant"]),
         ("s01hq04_plant", "catch", {}, ["s01hq04_treasure"]),
         ("s01hq04_treasure", "treasure", {120: 2}, []),
     ]},

    # ── The Great Mushrooming (s01mq05, "Wielkie Grzybobranie"). Client: the eccentric (56 = 1), his chest opened with
    # Good Money's key (56 = 2, 50 gold), the vogt Darach Dearg (321: 56 = 3, the 24 h modifier 3), mushrooms (331,
    # counters 11 and 30) whose graph queues the champion (327), a corpse, a monster corpse, Dehael and "enough"
    # (324-326, 495), the draconid nest (330), the leshen and the final ceremony with the fiend (347). Community
    # (Gamepressure): 24 hours of mushrooms, 750 XP and 120 gold. Authored: the queued events stand invisible
    # beside the player (the mushroom graph sends nothing to the server, so they must already be there), the
    # assignment of 324-326 and 495, five mushrooms around the player.
    {"id": 153, "code": "s01mq05", "name": "The Great Mushrooming", "folder": "s01mq05_mushroom_hunt", "criteria": "f1001>=1",
     "nodes": [
         node("s01mq05_madman", "s01mq05_madman", POI + "s01/mq05/mad_lad_lq.asset", "giver", root="f56<1"),
         node("s01mq05_chest", "s01mq05_treasure", POI + "s01/mq05/mad_lad_treasure_lq.asset", show="f56=1", band=(200, 600)),
         node("s01mq05_vogt", "s01mq05_vogt", POI + "s01/mq05/vogt_lq.asset", show="f56=2", band=(250, 700)),
         node("s01mq05_mushroom", "s01mq05_mushroom", POI + "s01/mq05/mushroom_lq.asset",
              show=f"f56=3 & !wait:s01mq05_vogt.vogt:{LAB_WAIT}", band=(60, 450), copies=5),
         node("s01mq05_champion", "s01mq05_champion", EMPTY, "queued", show="f56=3 & f153<1", node_id=327),
         node("s01mq05_corpse", "s01mq05_corpse", EMPTY, "queued", show="f56=3 & !out:s01mq05_corpse.corpse & !out:s01mq05_corpse.no_nest", node_id=325),
         node("s01mq05_monster_corpse", "s01mq05_monster_corpse", EMPTY, "queued", show="f56=3 & f58<1", node_id=324),
         node("s01mq05_dehael", "s01mq05_dehael", EMPTY, "queued", show="f56=3 & !out:s01mq05_dehael.dehael & !out:s01mq05_dehael.no_reward",
              node_id=326),
         node("s01mq05_enough", "s01mq05_enough", EMPTY, "queued", show="f56=3", node_id=495),
         node("s01mq05_nest", "s01mq05_nest", POI + "s01/mq05/nest_lq.asset", show="out:s01mq05_corpse.corpse & f8<3",
              band=(200, 600)),
         node("s01mq05_leshen", "s01mq05_leshen", POI + "s01/mq05/leshen_lq.asset", show="f58=1 & f9<4", band=(200, 600)),
         node("s01mq05_final", "s01mq05_final", POI + "s01/mq05/vogt_lq.asset",
              show=f"f56=3 & wait:s01mq05_vogt.vogt:{LAB_WAIT}", place_of="s01mq05_vogt"),
     ],
     "end": {f"s01mq05_final.{name}": {"exp": 750, "gold": 120}
             for name in ("first_place", "second_place", "third_place", "peleton", "last_place")},
     "walk": [
         ("s01mq05_madman", "madlad", {56: 1}, ["s01mq05_chest"]),
         ("s01mq05_chest", "treasure", {56: 2, 175: 50}, ["s01mq05_vogt"]),
         ("s01mq05_vogt", "vogt", {56: 3, 176: 1}, ["s01mq05_mushroom", "s01mq05_champion", "s01mq05_corpse",
                                                      "s01mq05_monster_corpse", "s01mq05_dehael", "s01mq05_enough"]),
         ("s01mq05_corpse", "corpse", {34: 1, 10153: 17}, ["s01mq05_mushroom", "s01mq05_champion", "s01mq05_monster_corpse",
                                                 "s01mq05_dehael", "s01mq05_enough", "s01mq05_nest"]),
         ("wait", LAB_WAIT),
         (None, None, None, ["s01mq05_champion", "s01mq05_monster_corpse", "s01mq05_dehael", "s01mq05_enough",
                             "s01mq05_nest", "s01mq05_final"]),
         ("s01mq05_final", "fiend", {12: 2}, ["s01mq05_champion", "s01mq05_monster_corpse", "s01mq05_dehael",
                                              "s01mq05_enough", "s01mq05_nest", "s01mq05_final"]),
         ("s01mq05_final", "second_place", {56: 4, 160: 4, 31: 4}, []),
     ]},

    # ── The Sins Of Our Fathers (s01mq03, "Grzechy naszych ojców"). Client: Vesemir hands over the contract (55 = 1);
    # the hermit (311, arachas fight; 147 = 1); the tracks (129 = 2); the vodyanoi's blood (129 = 3, 32 = 1);
    # Thorstein's candles (26 = 1); the lure at the grave (127 = 1); the striga's lair (313: kill her, or lift the
    # curse through the night with the candles, 55 = 3..6, 147 = 2); the armour chest (179 = 1). Community
    # (Gamepressure): given by Vesemir at the end of Pride Ain't Cheap. Authored: 500 XP (no published reward),
    # the hermit stands on the mq04 hermit settings, the lure on the tombstone, the empty lair (453) is not served.
    {"id": 152, "code": "s01mq03", "name": "The Sins Of Our Fathers", "folder": "s01mq03_striga", "criteria": "f54>=4",
     "nodes": [
         node("s01mq03_vesemir", "s01mq03_vesemir", POI + "s01/mq03/youngvesemir_lq.asset", "giver", root="f55<1"),
         node("s01mq03_instruction", "s01mq03_instruction", kind="button"),
         node("s01mq03_hermit", "s01mq03_hermit", POI + "s01/mq04/hermit_lq.asset", show="f55>=1 & f147<1", band=(300, 800)),
         node("s01mq03_tracks", "s01mq03_tracks", TRACKS, show="f147=1 & f129<2", band=(200, 600)),
         node("s01mq03_vodnik", "s01mq03_vodnik", POI + "s01/mq03/vodnik_lq.asset", show="f129=2", band=(250, 700)),
         node("s01mq03_thorstein", "s01mq03_thorstein", POI + "_common/thorstein_lq.asset", show="f129=3 & f26<1",
              band=(150, 500)),
         node("s01mq03_lure", "s01mq03_lure", POI + "s01/mq03/tombstone_lq.asset", show="f26>=1 & f127<1 & f147<2",
              band=(250, 700)),
         node("s01mq03_lair", "s01mq03_striga", POI + "s01/mq03/striga_lair_lq.asset", show="f127=1 & f147<2",
              near="s01mq03_lure", band=(40, 200)),
         node("s01mq03_armor", "s01mq03_armor", POI + "s01/mq03/armor_chest_lq.asset", show="f55>=5 & f179<1",
              place_of="s01mq03_lair"),
     ],
     "end": {"s01mq03_lair.striga_killed": {"exp": 500}, "s01mq03_lair.striga_killed_knew": {"exp": 500},
             # Community (Witcher Wiki): lifting the curse gives Hermit's Armor (armors row 8).
             "s01mq03_armor.armor": {"exp": 500, "items": items(armors={8: 1})}},
     "walk": [
         ("s01mq03_vesemir", "vesemir", {55: 1, 51: 1}, ["s01mq03_hermit"]),
         ("s01mq03_hermit", "arachas", {197: 2}, ["s01mq03_hermit"]),
         ("s01mq03_hermit", "hermit", {147: 1}, ["s01mq03_tracks"]),
         ("s01mq03_tracks", "tracks", {129: 2}, ["s01mq03_vodnik"]),
         ("s01mq03_vodnik", "vodnik", {129: 3, 32: 1}, ["s01mq03_thorstein"]),
         ("s01mq03_thorstein", "thorstein", {26: 1}, ["s01mq03_lure"]),
         ("s01mq03_lure", "lure", {127: 1, 134: 1}, ["s01mq03_lair"]),
         ("s01mq03_lair", "curse_lifted", {55: 5, 147: 2, 127: -1}, ["s01mq03_armor"]),
         ("s01mq03_armor", "armor", {179: 1, 31: 5}, []),
     ]},

    # ── Intruder (s01mq06, "Intruz"; the first of the two versions in the 1.1.116 catalog, quest 154). Client: it
    # opens at the fifth finished side quest (fact 31 = 5; the finishing graphs queue node 403); progress runs on
    # fact 57 when the Great Mushrooming told the vogt about the frightener (161 = 2), otherwise on 162: 1 the
    # contract, 2 the massacre, 4 Vesemir's poison, 5 the solvent used; the first frightener fight sets 59; the
    # archespore gives the solvent (27 = 2); journal buttons 357 (solvent), 358 and 478 (poison); the second
    # frightener fight (361) sets 61; Thorstein (124) and the vogt's payment end it. Authored: 500 XP, the start
    # stands beside the player and as a giver, the 24-hour wait advised by the sorcerer is not served (the
    # frightener can be hunted at once), the massacre POI uses the corpse settings.
    {"id": 154, "code": "s01mq06", "name": "Intruder", "folder": "s01mq06_frightener", "criteria": "f31>=5",
     "nodes": [
         node("s01mq06_dehael", "s01mq06_start", POI + "s01/mq06/dehael_lq.asset", "giver", root="f57<1 & f162<1"),
         node("s01mq06_dehael_queued", "s01mq06_start", POI + "s01/mq06/dehael_lq.asset", "queued",
              show="f31>=5 & !started:154 & !done:154", node_id=403),
         node("s01mq06_vogt", "s01mq06_vogt_01", POI + "s01/mq05/vogt_lq.asset", show="f57<1 & f162<1", band=(250, 700)),
         node("s01mq06_massacre", "s01mq06_massacre_01", POI + "s01/mq06/mans_corpse_1.asset", show="f57=1 | f162=1",
              band=(300, 800)),
         node("s01mq06_frightener", "s01mq06_frightener_01", POI + "s01/mq06/frightener_lair_lq.asset",
              show="f57=2 & f59<1 | f162=2 & f59<1", near="s01mq06_massacre", band=(100, 400)),
         node("s01mq06_vesemir", "s01mq06_vesemir", POI + "s01/mq03/youngvesemir_lq.asset",
              show="f57=2 & f59>=1 | f162=2 & f59>=1", band=(250, 700)),
         node("s01mq06_archespore", "s01mq06_archespore", POI + "s01/mq06/archespore_lq.asset",
              show="f57=4 & f27=1 | f162=4 & f27=1", band=(200, 650)),
         node("s01mq06_solvent", "quest_item_buttons/qi_solvent_button", kind="button", node_id=357),
         node("s01mq06_poison", "quest_item_buttons/qi_poison_button", kind="button", node_id=358),
         node("s01mq06_poison_01", "quest_item_buttons/qi_poison_01_button", kind="button", node_id=478),
         node("s01mq06_lair", "s01mq06_frightener_02", POI + "s01/mq06/frightener_lair_lq.asset",
              show="f57=5 & f61<2 | f162=5 & f61<2", place_of="s01mq06_frightener"),
         node("s01mq06_thorstein", "s01mq06_thorstein", POI + "_common/thorstein_lq.asset", show="f61>=2 & f124<1",
              band=(150, 500)),
         node("s01mq06_vogt_end", "s01mq06_vogt_02", POI + "s01/mq05/vogt_lq.asset", show="f61>=2 & f124>=1",
              place_of="s01mq06_vogt"),
     ],
     "end": {f"s01mq06_vogt_end.{name}": {"exp": 500} for name in ("bad_reward", "bonus_reward", "full_reward")},
     "walk": [
         ("s01mq06_dehael", "start", {}, ["s01mq06_vogt"]),
         ("s01mq06_vogt", "vogt", {162: 1}, ["s01mq06_massacre"]),
         ("s01mq06_massacre", "massacre_01", {162: 2}, ["s01mq06_frightener"]),
         ("s01mq06_frightener", "frightener_fail", {59: 1}, ["s01mq06_vesemir"]),
         ("s01mq06_vesemir", "vesemir", {162: 4, 27: 1}, ["s01mq06_archespore"]),
         ("s01mq06_archespore", "archespore", {27: 2}, []),
         ("s01mq06_solvent", "solvent", {27: -3, 162: 5}, ["s01mq06_lair"]),
         ("s01mq06_lair", "frightener", {61: 2, 163: 1}, ["s01mq06_thorstein"]),
         ("s01mq06_thorstein", "thorstein_shop", {124: 1}, ["s01mq06_vogt_end"]),
         ("s01mq06_vogt_end", "full_reward", {166: 1}, []),
     ]},
]

# Player modifiers the season 1 graphs add (AddExpiringEffect): ids from the graphs, slugs from the client's
# NOTIFICATIONS/EFFECT/S01_* names matched by use and duration. 1 and 8 are the unused ones (blacksmith's sharpening,
# will o' the wisp).
MODIFIERS = [(1, "s01_blacksmith"), (2, "s01_curse"), (3, "s01_mushrooming"), (4, "s01_candle"), (5, "s01_potion"),
             (6, "s01_24h"), (7, "s01_12h"), (8, "s01_firefly")]

# Monster rows for the fights: slug -> (community sheet name or None, family, trophy override, count kills).
MONSTERS = {
    "arachnomorph": ("Arachnomorph", 8, None, True), "arachas": ("Common Arachas", 8, None, True),
    "archespore": ("Archspore", 11, None, False), "bies_lvl1": ("Fiend", 6, None, True),
    "cavetroll": ("Rock Troll", 3, None, True), "fogling_lvl1": ("Foglet", 1, None, True),
    "foglingignisfatuus": ("Ignis Fatuus", 1, None, True), "frightener": ("Frightener", 8, None, True),
    "golem_lvl1": ("Golem", 5, None, True), "golem_lvl2": ("Golem", 5, None, True), "golem_lvl2_hq01": ("Golem", 5, "trophy_golem_lvl2.png", True),
    "leshensdog_lvl2": ("Leshen Hound", 6, None, True), "lessun": ("Leshen", 6, None, True),
    "likho": ("Liho", 6, "trophy_licho.png", True), "nekkerwarrior_lvl3": ("Nekker Shaman", 3, None, True),
    "scolopendromorph_lvl1": ("Scolopendromorph", 8, None, True), "striga_albino": ("White Striga", 11, None, True),
    "vodyanoi": ("Vodnik", 3, None, True), "actor_fightable": (None, 11, None, False),
    "hermit_fightable": (None, 11, None, False),
}
