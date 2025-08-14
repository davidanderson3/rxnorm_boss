import unittest

from boss import compute_stats


class ComputeStatsTests(unittest.TestCase):
    def test_ai_am_different_boss_from_percentages(self):
        rows = [
            {"ai": [{"rxcui": "1"}], "am": [{"rxcui": "2"}], "boss_from": ["AI"]},
            {"ai": [{"rxcui": "1"}], "am": [{"rxcui": "1"}], "boss_from": ["AM"]},
            {"ai": [{"rxcui": "1"}], "am": [{"rxcui": "2"}], "boss_from": ["AM"]},
            {"ai": [{"rxcui": "1"}], "am": [{"rxcui": "2"}], "boss_from": []},
        ]
        stats = compute_stats(rows)
        self.assertEqual(stats["ai_am_different"]["count"], 3)
        self.assertAlmostEqual(stats["ai_am_different"]["pct"], 75.0)
        self.assertEqual(
            stats["boss_from_AI_when_ai_am_different"]["count"], 1
        )
        self.assertAlmostEqual(
            stats["boss_from_AI_when_ai_am_different"]["pct"], 33.333333, places=5
        )
        self.assertEqual(
            stats["boss_from_AM_when_ai_am_different"]["count"], 1
        )
        self.assertAlmostEqual(
            stats["boss_from_AM_when_ai_am_different"]["pct"], 33.333333, places=5
        )


if __name__ == "__main__":
    unittest.main()
