"""Acceptance checks for the third-party model dispatch example."""

import unittest

from config_demo import load_settings


class ConfigDemoTests(unittest.TestCase):
    def test_defaults(self):
        self.assertEqual(load_settings({}), {"debug": False, "timeout_seconds": 30})

    def test_true_values(self):
        for value in ("true", "1", "yes", "on", " TrUe "):
            with self.subTest(value=value):
                self.assertIs(load_settings({"APP_DEBUG": value})["debug"], True)

    def test_false_values(self):
        for value in ("false", "0", "no", "off", " oFf\t"):
            with self.subTest(value=value):
                self.assertIs(load_settings({"APP_DEBUG": value})["debug"], False)

    def test_invalid_debug_values(self):
        for value in ("", "   ", "maybe", "2"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                load_settings({"APP_DEBUG": value})

    def test_positive_timeout(self):
        for value, expected in (("1", 1), ("60", 60), ("+5", 5), (" 5 ", 5), ("05", 5)):
            with self.subTest(value=value):
                actual = load_settings({"APP_TIMEOUT": value})["timeout_seconds"]
                self.assertEqual(actual, expected)
                self.assertIs(type(actual), int)

    def test_invalid_timeout(self):
        for value in ("0", "-1", "1.5", "", "   ", "abc"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                load_settings({"APP_TIMEOUT": value})

    def test_combined_settings_and_input_preserved(self):
        env = {"APP_DEBUG": "yes", "APP_TIMEOUT": "7"}
        before = env.copy()
        self.assertEqual(load_settings(env), {"debug": True, "timeout_seconds": 7})
        self.assertEqual(env, before)


if __name__ == "__main__":
    unittest.main()
