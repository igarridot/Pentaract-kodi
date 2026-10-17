import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "plugin.video.pentaract" / "resources" / "lib" / "advancedsettings.py"


def load_module():
    spec = importlib.util.spec_from_file_location("pentaract_advancedsettings_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AdvancedSettingsTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module()

    def test_tune_creates_a_document_from_nothing(self):
        xml = self.module.tune_network_timeouts("")

        self.assertEqual((120, 120), self.module.read_network_timeouts(xml))
        self.assertTrue(xml.startswith("<advancedsettings>"))
        self.assertTrue(xml.endswith("</advancedsettings>\n"))

    def test_tune_keeps_unrelated_settings_and_overrides_timeouts(self):
        existing = (
            "<advancedsettings>\n"
            "    <cache><memorysize>52428800</memorysize></cache>\n"
            "    <network><curlclienttimeout>10</curlclienttimeout><bandwidth>0</bandwidth></network>\n"
            "</advancedsettings>\n"
        )

        xml = self.module.tune_network_timeouts(existing, client_timeout=90, low_speed_time=75)

        self.assertEqual((90, 75), self.module.read_network_timeouts(xml))
        self.assertIn("<memorysize>52428800</memorysize>", xml)
        self.assertIn("<bandwidth>0</bandwidth>", xml)
        self.assertEqual(1, xml.count("<network>"))
        self.assertEqual(1, xml.count("<curlclienttimeout>"))

    def test_timeouts_are_sufficient_only_when_both_values_reach_the_target(self):
        self.assertFalse(self.module.timeouts_are_sufficient(""))
        self.assertFalse(
            self.module.timeouts_are_sufficient(
                "<advancedsettings><network><curlclienttimeout>120</curlclienttimeout></network></advancedsettings>"
            )
        )
        self.assertFalse(
            self.module.timeouts_are_sufficient(
                "<advancedsettings><network><curlclienttimeout>120</curlclienttimeout>"
                "<curllowspeedtime>20</curllowspeedtime></network></advancedsettings>"
            )
        )
        self.assertTrue(
            self.module.timeouts_are_sufficient(
                "<advancedsettings><network><curlclienttimeout>300</curlclienttimeout>"
                "<curllowspeedtime>120</curllowspeedtime></network></advancedsettings>"
            )
        )

    def test_read_ignores_values_that_are_not_numbers(self):
        xml = "<advancedsettings><network><curllowspeedtime>soon</curllowspeedtime></network></advancedsettings>"

        self.assertEqual((None, None), self.module.read_network_timeouts(xml))

    def test_rejects_a_document_that_is_not_advancedsettings(self):
        with self.assertRaises(ValueError):
            self.module.tune_network_timeouts("<settings/>")


if __name__ == "__main__":
    unittest.main()
