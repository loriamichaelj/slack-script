import unittest

from anomaly_alerts.detectors import DETECTORS, ewma, iqr, mad, zscore
from helpers import BASE


class DetectorTests(unittest.TestCase):
    def test_in_range_scores_near_zero(self):
        for name, module in DETECTORS.items():
            with self.subTest(detector=name):
                scored = module.score(BASE, [12.0])
                self.assertLess(abs(scored.scores[0]), 1.0)

    def test_spike_scores_high_and_drop_scores_negative(self):
        for name, module in DETECTORS.items():
            with self.subTest(detector=name):
                up = module.score(BASE, [50.0]).scores[0]
                down = module.score(BASE, [-30.0]).scores[0]
                self.assertGreater(up, module.DEFAULT_THRESHOLD)
                self.assertLess(down, -module.DEFAULT_THRESHOLD)

    def test_flat_baseline_has_no_scores(self):
        flat = [7.0] * 40
        for name, module in DETECTORS.items():
            with self.subTest(detector=name):
                scored = module.score(flat, [9.0])
                self.assertIsNone(scored.scores)
                self.assertEqual(scored.spread, 0.0)

    def test_mad_matches_modified_z_formula(self):
        # median 12, MAD 1 for BASE, so M = 0.6745 * (x - 12) / 1
        expected = 0.6745 * (30 - 12) / 1
        self.assertAlmostEqual(mad.score(BASE, [30.0]).scores[0], expected, places=6)

    def test_mad_survives_past_spikes_where_zscore_does_not(self):
        spiky = BASE + [200.0] * 5
        self.assertGreater(mad.score(spiky, [30.0]).scores[0], 3.5)
        self.assertLess(zscore.score(spiky, [30.0]).scores[0], 3.5)

    def test_mad_falls_back_when_most_values_equal_the_median(self):
        mostly_zero = [0.0] * 50 + [1.0] * 10
        scored = mad.score(mostly_zero, [20.0])
        self.assertIsNotNone(scored.scores)
        self.assertGreater(scored.scores[0], 3.5)

    def test_iqr_is_zero_inside_the_quartiles(self):
        self.assertEqual(iqr.score(BASE, [11.5, 12.0, 12.5]).scores, [0.0, 0.0, 0.0])

    def test_iqr_score_is_distance_past_quartile_in_iqr_units(self):
        # BASE: Q1 = 11, Q3 = 13, IQR = 2
        self.assertAlmostEqual(iqr.score(BASE, [20.0]).scores[0], 3.5)
        self.assertAlmostEqual(iqr.score(BASE, [5.0]).scores[0], -3.0)

    def test_ewma_baseline_is_not_moved_by_the_window(self):
        a = ewma.score(BASE, [30.0]).center
        b = ewma.score(BASE, [30.0, 30.0, 30.0]).center
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
