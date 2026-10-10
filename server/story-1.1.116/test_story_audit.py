"""story_audit finds a step that can never show, a quest that cannot end and a walk-through fact the client never sets.

  python -m unittest test_story_audit      # in server/story-1.1.116
"""
import unittest

from story_audit import audit

EMPTY = {"outputs": {}, "sets": [], "queues": [], "fight_outputs": {}, "npcs": []}
# The giver's graph sets fact 5 to 1 and raises the counter fact 6; the POI's graph ends the quest.
GRAPHS = {"giver": dict(EMPTY, outputs={"start": {"facts": [[5, 1]]}}, sets=[[5, 1], [6, "+1"]]),
          "poi": dict(EMPTY, outputs={"end": {"facts": []}})}


def story(show, walk_facts):
    return {"quests": [{"id": 1, "name": "Q", "criteria": "f100>=4"}],
            "nodes": [{"id": 10, "quest": 1, "key": "giver", "graph": "giver", "kind": "giver", "root": "", "show": ""},
                      {"id": 11, "quest": 1, "key": "poi", "graph": "poi", "kind": "poi", "root": "", "show": show}],
            "outputs": [{"id": 1, "node": 10, "name": "start", "endpoint": False, "gold": 0, "kills": {}},
                        {"id": 2, "node": 11, "name": "end", "endpoint": True, "gold": 0, "kills": {}}],
            "monsters": [], "walks": {"1": [["giver", "start", walk_facts, ["poi"]]]}}


class AuditTests(unittest.TestCase):
    def errors(self, show, walk_facts=None):
        return audit(GRAPHS, story(show, walk_facts or {"5": 1}), {"monsters": []}, set())[0]

    def test_a_story_the_graphs_can_play_has_no_errors(self):
        self.assertEqual(self.errors("f5=1 & f6>=3 & out:giver.start"), [])

    def test_a_condition_no_graph_meets_never_shows_and_its_quest_cannot_end(self):
        self.assertEqual(self.errors("f5=2"), ["quest 1 Q: can never end", "poi (poi): never shows: f5=2"])

    def test_a_walk_fact_the_graph_never_sets(self):
        self.assertEqual(self.errors("f5=1", {"5": 2}),
                         ["walk 1: giver.start sends f5=2, which the client's graph never sets"])


if __name__ == "__main__":
    unittest.main()
