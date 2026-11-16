"""The CI root registry and the script that picks which roots a workflow acts on."""

import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GITHUB = ROOT / ".github"
REGISTRY = GITHUB / "terraform-roots.json"
SELECT = GITHUB / "scripts" / "select-roots.sh"

# Which backend settings terraform init needs, per cloud.
BACKEND_KEYS = {
    "gcp": {"bucket"},
    "aws": {"bucket"},
    "azure": {"resource_group_name", "storage_account_name", "container_name"},
}


def registry():
    return json.loads(REGISTRY.read_text())


def select(*args, **env):
    clean = {k: v for k, v in os.environ.items() if not k.startswith(("ONLY_", "FOR_", "BEFORE", "GCP_", "AWS_", "AZURE_"))}
    result = subprocess.run(
        [str(SELECT), *args], capture_output=True, text=True, env={**clean, **env}, cwd=ROOT, check=True
    )
    return [f"{r['cloud']}/{r['root']}" for r in json.loads(result.stdout)]


class RegistryTests(unittest.TestCase):
    def test_every_entry_points_at_a_real_root(self):
        for entry in registry():
            with self.subTest(root=f"{entry['cloud']}/{entry['root']}"):
                self.assertTrue((ROOT / "terraform" / entry["cloud"] / entry["root"]).is_dir())

    def test_every_entry_has_the_backend_settings_its_cloud_needs(self):
        for entry in registry():
            with self.subTest(root=f"{entry['cloud']}/{entry['root']}"):
                self.assertEqual(set(entry["backend"]), BACKEND_KEYS[entry["cloud"]])

    def test_every_entry_names_its_environment_and_identities(self):
        for entry in registry():
            with self.subTest(root=f"{entry['cloud']}/{entry['root']}"):
                self.assertIn(entry["env"], {"SEED", "DEV"})
                self.assertIn(entry["plan_identity"], {"tf-planner"})
                self.assertIn(entry["apply_identity"], {"seed-admin", "dev-deployer"})

    def test_no_root_is_listed_twice(self):
        names = [f"{e['cloud']}/{e['root']}" for e in registry()]
        self.assertEqual(len(names), len(set(names)))

    def test_every_seed_and_dev_root_in_terraform_is_registered_or_exempt(self):
        exempt = {"gcp/org"}  # applied by hand, never by a workflow
        on_disk = {f"{p.parent.name}/{p.name}" for p in (ROOT / "terraform").glob("*/*") if p.is_dir()}
        listed = {f"{e['cloud']}/{e['root']}" for e in registry()}
        self.assertEqual(on_disk - exempt - listed, set(), "a Terraform root is missing from the registry")


@unittest.skipUnless(shutil.which("jq"), "jq is needed to run the selector")
class SelectRootsTests(unittest.TestCase):
    def test_all_lists_every_root_in_order(self):
        self.assertEqual(select("all"), [f"{e['cloud']}/{e['root']}" for e in registry()])

    def test_target_picks_one_root(self):
        self.assertEqual(select("target", "aws/dev"), ["aws/dev"])
        self.assertEqual(select("target", "nope/none"), [])

    def test_a_cloud_that_is_not_bootstrapped_is_dropped(self):
        self.assertEqual(select("all", ONLY_READY="1"), [])
        self.assertEqual(select("all", ONLY_READY="1", AWS_ACCOUNT_ID="1"), ["aws/seed", "aws/dev"])
        self.assertEqual(select("all", ONLY_READY="1", GCP_WORKLOAD_IDENTITY_PROVIDER="p"), ["gcp/seed", "gcp/dev"])

    def test_azure_needs_both_its_tenant_and_its_subscription(self):
        self.assertEqual(select("all", ONLY_READY="1", AZURE_TENANT_ID="t"), [])
        self.assertEqual(select("all", ONLY_READY="1", AZURE_SUBSCRIPTION_ID="s"), [])
        ready = select("all", ONLY_READY="1", AZURE_TENANT_ID="t", AZURE_SUBSCRIPTION_ID="s")
        self.assertEqual(ready, [f"azure/{e['root']}" for e in registry() if e["cloud"] == "azure"])

    def test_roots_applied_by_hand_are_dropped_for_apply_only(self):
        ready = dict(ONLY_READY="1", AZURE_TENANT_ID="t", AZURE_SUBSCRIPTION_ID="s", AWS_ACCOUNT_ID="1")
        self.assertIn("azure/seed", select("all", **ready))
        self.assertNotIn("azure/seed", select("all", FOR_APPLY="1", **ready))
        self.assertIn("aws/dev", select("all", FOR_APPLY="1", **ready))

    def test_changed_without_a_base_means_everything(self):
        self.assertEqual(select("changed", BEFORE="0" * 40), [f"{e['cloud']}/{e['root']}" for e in registry()])

    def test_changed_compares_directories(self):
        head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=ROOT, check=True).stdout.strip()
        self.assertEqual(select("changed", BEFORE=head, GITHUB_SHA=head), [])

    def test_bad_mode_is_an_error(self):
        with self.assertRaises(subprocess.CalledProcessError):
            select("bogus")
