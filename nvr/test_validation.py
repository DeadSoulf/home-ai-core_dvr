import unittest

from nvr.validation import normalize_sdk_channel


class SDKChannelValidationTests(unittest.TestCase):
    def test_valid_channel_numbers_are_normalized(self):
        self.assertEqual(normalize_sdk_channel(1), "1")
        self.assertEqual(normalize_sdk_channel("33"), "33")
        self.assertEqual(normalize_sdk_channel(" 0001 "), "1")
        self.assertEqual(normalize_sdk_channel(2048), "2048")
        self.assertEqual(normalize_sdk_channel(None), "")
        self.assertEqual(normalize_sdk_channel(""), "")

    def test_path_injection_and_unsupported_values_are_rejected(self):
        for value in ("../..", "1/../../", "..\\", "0", 0, 2049, -1,
                      "1.0", "12345", True, "１２", "one"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_sdk_channel(value)


if __name__ == "__main__":
    unittest.main()
