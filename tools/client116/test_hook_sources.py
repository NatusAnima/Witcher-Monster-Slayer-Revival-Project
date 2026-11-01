"""The hook's C fast hooks (CModule sources inside hook.js and gps.js):  python tools/client116/test_hook_sources.py
"""
import os, re, unittest

HERE = os.path.dirname(os.path.abspath(__file__))


def c_modules():
    """(file, source) of every template literal that holds a C module."""
    for name in ("hook.js", "gps.js"):
        with open(os.path.join(HERE, name), encoding="utf-8") as f:
            for match in re.finditer(r"`(\s*#include <gum/guminterceptor\.h>.*?)`", f.read(), re.S):
                yield name, match.group(1)


class HookSources(unittest.TestCase):
    def test_the_c_modules_keep_no_state_of_their_own(self):
        # A CModule's code and its static variables share memory that is read-only once loaded: writing a static crashed
        # the game's main thread at its first frame (0.4.0, LocationModule.Tick). State goes in JS memory, as an extern.
        modules = list(c_modules())
        self.assertGreaterEqual(len(modules), 7)
        for name, source in modules:
            with self.subTest(file=name, start=source.strip()[:80]):
                self.assertIsNone(re.search(r"^\s*static\s+(?!inline\b)", source, re.M))


if __name__ == "__main__":
    unittest.main()
