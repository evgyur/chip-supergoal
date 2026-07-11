import unittest


class LiveGoalManagerProbe(unittest.TestCase):
    @unittest.skip(
        "reserved hook: no external Hermes GoalManager adapter ships in this repository"
    )
    def test_live_goalmanager_probe_reserved(self):
        self.fail("reserved live probe must never execute as release evidence")

if __name__ == "__main__":
    unittest.main()
