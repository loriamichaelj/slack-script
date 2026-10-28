import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from anomaly_alerts.state import StateStore
from helpers import NOW


class StateTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = Path(self.dir.name) / "nested" / "alerts.json"

    def store(self, cooldown=3600):
        s = StateStore(self.path, cooldown)
        s.load()
        return s

    def test_new_fingerprint_alerts(self):
        self.assertTrue(self.store().allow("fp", "warning", NOW))

    def test_cooldown_silences_repeats_then_expires(self):
        s = self.store()
        s.record("fp", "warning", NOW)
        self.assertFalse(s.allow("fp", "warning", NOW + timedelta(minutes=59)))
        self.assertTrue(s.allow("fp", "warning", NOW + timedelta(minutes=60)))

    def test_escalation_bypasses_cooldown_once(self):
        s = self.store()
        s.record("fp", "warning", NOW)
        later = NOW + timedelta(minutes=5)
        self.assertTrue(s.allow("fp", "critical", later))
        s.record("fp", "critical", later)
        self.assertFalse(s.allow("fp", "critical", later + timedelta(minutes=5)))
        self.assertFalse(s.allow("fp", "warning", later + timedelta(minutes=5)))

    def test_state_survives_a_save_and_load(self):
        s = self.store()
        s.record("fp", "critical", NOW)
        s.save(NOW)
        self.assertFalse(self.store().allow("fp", "critical", NOW + timedelta(minutes=1)))

    def test_old_entries_are_pruned_on_save(self):
        s = self.store()
        s.record("old", "warning", NOW - timedelta(days=8))
        s.record("new", "warning", NOW)
        s.save(NOW)
        reloaded = self.store(cooldown=10**9)
        self.assertTrue(reloaded.allow("old", "warning", NOW))  # forgotten
        self.assertFalse(reloaded.allow("new", "warning", NOW))

    def test_corrupt_file_is_ignored(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{not json")
        with self.assertLogs("anomaly_alerts.state", "WARNING"):
            self.assertTrue(self.store().allow("fp", "warning", NOW))


if __name__ == "__main__":
    unittest.main()
