import tempfile
import unittest
from pathlib import Path

from anomaly_alerts import actions
from anomaly_alerts.config import ConfigError
from anomaly_alerts.models import Anomaly, Detection
from helpers import NOW, make_series, make_spec


def anomaly(category="errors", direction="spike", provider="aws"):
    detection = Detection(direction, "warning", 5.0, 50.0, 12.0, 1.0, 3)
    return Anomaly(
        spec=make_spec(category=category),
        series=make_series([1], provider=provider),
        detection=detection,
        window_start=NOW,
        window_end=NOW,
    )


class ActionTests(unittest.TestCase):
    def write(self, text):
        folder = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(folder, ignore_errors=True))
        path = Path(folder) / "actions.yaml"
        path.write_text(text)
        return path

    def test_first_matching_rule_wins(self):
        path = self.write(
            "actions:\n"
            "  - {match: {category: errors, direction: spike}, steps: [first]}\n"
            "  - {match: {category: errors}, steps: [second]}\n"
        )
        rules = actions.load_rules(path)
        self.assertEqual(actions.steps_for(anomaly(), rules), ["first"])
        self.assertEqual(actions.steps_for(anomaly(direction="drop"), rules), ["second"])

    def test_no_match_falls_back_to_generic_steps(self):
        rules = actions.load_rules(self.write("actions:\n  - {match: {category: cpu}, steps: [x]}\n"))
        self.assertEqual(actions.steps_for(anomaly(), rules), actions.GENERIC_STEPS)
        self.assertEqual(actions.steps_for(anomaly(), []), actions.GENERIC_STEPS)

    def test_provider_can_be_matched(self):
        rules = actions.load_rules(self.write("actions:\n  - {match: {provider: gcp}, steps: [gcp step]}\n"))
        self.assertEqual(actions.steps_for(anomaly(provider="gcp"), rules), ["gcp step"])
        self.assertEqual(actions.steps_for(anomaly(provider="aws"), rules), actions.GENERIC_STEPS)

    def test_bad_rules_are_rejected(self):
        for text in (
            "actions:\n  - {match: {colour: red}, steps: [x]}\n",
            "actions:\n  - {match: {category: cpu}, steps: []}\n",
            "actions:\n  - {steps: [x]}\n",
            "nothing: here\n",
        ):
            with self.subTest(text=text), self.assertRaises(ConfigError):
                actions.load_rules(self.write(text))

    def test_the_shipped_rules_load(self):
        shipped = Path(__file__).resolve().parent.parent / "config" / "actions.yaml"
        self.assertGreater(len(actions.load_rules(shipped)), 0)


if __name__ == "__main__":
    unittest.main()
