import unittest

from anomaly_alerts.detectors.guards import evaluate
from helpers import BASE, make_spec


class GuardTests(unittest.TestCase):
    def test_sustained_spike_is_detected(self):
        found = evaluate(BASE + [50, 50, 50], make_spec())
        self.assertIsNotNone(found)
        self.assertEqual(found.direction, "spike")
        self.assertEqual(found.severity, "critical")
        self.assertEqual(found.observed, 50)
        self.assertEqual(found.breaching, 3)

    def test_single_noisy_point_is_ignored(self):
        self.assertIsNone(evaluate(BASE + [50, 12, 12], make_spec()))
        self.assertIsNone(evaluate(BASE + [12, 12, 50], make_spec()))
        self.assertIsNone(evaluate(BASE + [12, 50, 12], make_spec()))

    def test_normal_data_is_quiet(self):
        self.assertIsNone(evaluate(BASE + [12, 13, 11], make_spec()))

    def test_not_enough_history_gives_no_verdict(self):
        self.assertIsNone(evaluate(BASE[:20] + [50, 50, 50], make_spec(min_points=30)))
        self.assertIsNotNone(evaluate(BASE[:27] + [50, 50, 50], make_spec(min_points=20)))

    def test_direction_filters_what_alerts(self):
        spike = BASE + [50, 50, 50]
        drop = BASE + [0, 0, 0]
        self.assertIsNone(evaluate(spike, make_spec(direction="drop")))
        self.assertIsNone(evaluate(drop, make_spec(direction="spike")))
        self.assertEqual(evaluate(drop, make_spec(direction="drop")).direction, "drop")
        self.assertEqual(evaluate(spike, make_spec(direction="both")).direction, "spike")

    def test_minimum_absolute_change_suppresses_small_moves(self):
        values = BASE + [20, 20, 20]  # statistically odd, but only 8 units up
        self.assertIsNotNone(evaluate(values, make_spec(min_abs_change=0)))
        self.assertIsNone(evaluate(values, make_spec(min_abs_change=10)))

    def test_flat_baseline_uses_percentage_change(self):
        flat = [10.0] * 60
        big = evaluate(flat + [20, 20, 20], make_spec())
        self.assertIsNotNone(big)
        self.assertEqual(big.direction, "spike")
        self.assertIsNone(evaluate(flat + [12, 12, 12], make_spec()))  # only 20%

    def test_warning_then_critical_after_twice_the_window(self):
        # 19 scores about 4.7: above the 3.5 threshold, below twice it (7.0).
        short = evaluate(BASE + [19] * 3, make_spec())
        self.assertEqual(short.severity, "warning")
        long = evaluate(BASE + [19] * 6, make_spec())
        self.assertEqual(long.severity, "critical")

    def test_every_detector_flags_a_clear_spike(self):
        for name in ("zscore", "mad", "ewma", "iqr"):
            with self.subTest(detector=name):
                spec = make_spec(detector=name, threshold={"iqr": 1.5}.get(name, 3.0))
                self.assertIsNotNone(evaluate(BASE + [60, 60, 60], spec))
                self.assertIsNone(evaluate(BASE + [12, 12, 12], spec))


if __name__ == "__main__":
    unittest.main()
