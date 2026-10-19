import unittest

from nvr.sdk_features import capabilities, unsupported_sdk_post


class SDKFeatureTests(unittest.TestCase):
    def test_new_profile_disables_only_unported_functions(self):
        features = capabilities("hcnet611-local")
        for key in ("login", "record", "live", "snapshot", "ptz", "preset"):
            self.assertTrue(features[key], key)
        for key in ("device_status", "events", "network_usage",
                    "ability", "voice", "remote_archive"):
            self.assertFalse(features[key], key)
        self.assertTrue(unsupported_sdk_post("hcnet611-local", "/api/events/start"))
        self.assertTrue(unsupported_sdk_post("hcnet611-local", "/api/archive-prepare"))
        self.assertFalse(unsupported_sdk_post("hcnet611-local", "/api/ptz"))
        self.assertFalse(unsupported_sdk_post("hcnet611-local", "/api/nvr/cameras"))

    def test_legacy_profile_does_not_change_existing_functions(self):
        features = capabilities("")
        self.assertTrue(features["events"])
        self.assertFalse(unsupported_sdk_post("", "/api/events/start"))


if __name__ == "__main__":
    unittest.main()
