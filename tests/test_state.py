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

    def test_last_saved_is_none_until_a_save(self):
        s = self.store()
        self.assertIsNone(s.last_saved())
        s.save(NOW)
        self.assertIsNotNone(s.last_saved())

    def test_alerted_since_counts_recent_entries(self):
        s = self.store()
        s.record("a", "warning", NOW - timedelta(hours=30))
        s.record("b", "warning", NOW - timedelta(hours=2))
        s.record("c", "critical", NOW)
        self.assertEqual(s.alerted_since(NOW - timedelta(hours=24)), 2)

    def test_corrupt_file_is_ignored(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{not json")
        with self.assertLogs("anomaly_alerts.state", "WARNING"):
            self.assertTrue(self.store().allow("fp", "warning", NOW))


if __name__ == "__main__":
    unittest.main()


class FakeS3:
    """Just enough of a boto3 S3 client for the state backend."""

    class exceptions:
        class NoSuchKey(Exception):
            pass

        class ClientError(Exception):
            pass

    def __init__(self):
        self.objects = {}

    def get_object(self, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise self.exceptions.NoSuchKey()
        import io

        return {"Body": io.BytesIO(self.objects[(Bucket, Key)])}

    def put_object(self, Bucket, Key, Body, ContentType):
        self.objects[(Bucket, Key)] = Body

    def head_object(self, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise self.exceptions.ClientError()
        return {"LastModified": NOW}


class S3StateTests(unittest.TestCase):
    def store(self, fake):
        s = StateStore("s3://bkt/state/alerts.json", 3600)
        s._backend._client = fake
        s.load()
        return s

    def test_round_trip_through_s3(self):
        fake = FakeS3()
        s = self.store(fake)
        self.assertIsNone(s.last_saved())
        s.record("fp", "warning", NOW)
        s.save(NOW)
        self.assertIn(("bkt", "state/alerts.json"), fake.objects)
        again = self.store(fake)
        self.assertFalse(again.allow("fp", "warning", NOW + timedelta(minutes=5)))
        self.assertEqual(again.last_saved(), NOW)

    def test_unreadable_s3_state_does_not_stop_alerting(self):
        fake = FakeS3()
        fake.objects[("bkt", "state/alerts.json")] = b"not json"
        self.assertTrue(self.store(fake).allow("fp", "warning", NOW))

    def test_bad_s3_uri_is_rejected(self):
        with self.assertRaises(ValueError):
            StateStore("s3://bucket-only", 3600)
