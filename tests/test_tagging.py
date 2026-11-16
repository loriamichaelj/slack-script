"""Every Terraform root must tag what it creates with the same standard set.

A root passes when one tag set in its .tf files carries all the required keys: a provider's
default_tags or default_labels, or the tags or labels it merges into each resource.
"""

import re
import unittest
from pathlib import Path

TERRAFORM = Path(__file__).resolve().parent.parent / "terraform"
REQUIRED = ("project", "app", "env", "managed_by", "repo")

# Roots whose resources cannot carry tags at all. Say why, so the exemption can be reviewed.
EXEMPT = {
    "gcp/org": "only IAM bindings, a log sink and monitoring scopes, none of which support labels",
}

# A map that follows tags = , labels = , default_tags { tags = } or default_labels = .
# merge( is allowed in front of the map, which is how the shared set is extended.
_TAG_SET = re.compile(r"\b(?:default_)?(?:tags|labels)\s*=\s*(?:merge\(\s*)?\{(?P<body>[^{}]*)\}")
_KEY = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+?)\s*$")


def roots():
    return sorted(p for p in TERRAFORM.glob("*/*") if p.is_dir() and not p.name.startswith("."))


def tag_sets(root: Path) -> list[dict]:
    found = []
    for path in sorted(root.glob("*.tf")):
        for match in _TAG_SET.finditer(path.read_text()):
            # One entry per line, or per comma when the whole map is written on one line.
            entries = (m.groups() for part in re.split(r"[,\n]", match.group("body")) if (m := _KEY.match(part)))
            found.append(dict(entries))
    return found


def name(root: Path) -> str:
    return f"{root.parent.name}/{root.name}"


class TaggingTests(unittest.TestCase):
    def test_roots_are_found(self):
        self.assertGreaterEqual(len(roots()), 5, "the test cannot see the Terraform roots")

    def test_every_root_has_the_standard_tags(self):
        for root in roots():
            if name(root) in EXEMPT:
                continue
            with self.subTest(root=name(root)):
                sets = tag_sets(root)
                complete = [s for s in sets if all(key in s for key in REQUIRED)]
                missing = [[k for k in REQUIRED if k not in s] for s in sets]
                self.assertTrue(
                    complete,
                    f"{name(root)} has no tag set with all of {REQUIRED}; "
                    f"found {len(sets)} set(s), missing keys: {missing}",
                )

    def test_the_project_and_app_names_agree_across_clouds(self):
        for key in ("project", "app"):
            values = {}
            for root in roots():
                if name(root) in EXEMPT:
                    continue
                for s in tag_sets(root):
                    if key in s:
                        values[name(root)] = s[key]
            with self.subTest(key=key):
                self.assertEqual(
                    len(set(values.values())), 1, f"{key} differs between roots: {values}"
                )

    def test_exemptions_are_real_and_still_needed(self):
        names = {name(r) for r in roots()}
        for exempt in EXEMPT:
            with self.subTest(root=exempt):
                self.assertIn(exempt, names, "an exempt root no longer exists")
                complete = [s for s in tag_sets(TERRAFORM / exempt) if all(k in s for k in REQUIRED)]
                self.assertFalse(complete, f"{exempt} is tagged now, so remove it from EXEMPT")
