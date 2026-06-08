import tempfile
import unittest
from datetime import date
from pathlib import Path

from water_reporter import build_digest, load_daily_orders, parse_sandstone_orders, save_daily_orders


SAMPLE_PDF_TEXT = """
Some header text

Sandstone*
*Sandstone
12345
Smith, John
1.50
*Sandstone
67890
Jones, Mary
0.75
Total Cfs (Sandstone) 2.25

South Bench
99999
Other, Person
3.00
"""


class WaterReporterTests(unittest.TestCase):
    def test_parse_sandstone_orders_filters_to_sandstone(self):
        orders = parse_sandstone_orders(SAMPLE_PDF_TEXT)
        self.assertEqual(2, len(orders))
        self.assertEqual({"Smith, John", "Jones, Mary"}, {order["name"] for order in orders})

    def test_save_and_load_daily_orders(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            target_dir = Path(tmp_dir)
            report_date = date(2026, 5, 27)
            expected_orders = [{"acct_num": "12345", "ditch_gate": "Sandstone", "name": "Smith, John", "cfs": "1.50"}]

            path = save_daily_orders(target_dir, report_date, expected_orders, "https://example.com/6-8.pdf")

            self.assertTrue(path.exists())
            self.assertEqual(expected_orders, load_daily_orders(target_dir, report_date))

    def test_build_digest_identifies_previous_order_flow(self):
        todays = [{"acct_num": "12345", "ditch_gate": "Sandstone", "name": "Smith, John", "cfs": "1.50"}]
        prior = [
            {"acct_num": "12345", "ditch_gate": "Sandstone", "name": "Smith, John", "cfs": "1.20"},
            {"acct_num": "99999", "ditch_gate": "Sandstone", "name": "Jones, Mary", "cfs": "0.75"},
        ]

        digest = build_digest(date(2026, 5, 27), todays, prior)

        self.assertEqual(["Smith, John"], digest.active_today)
        self.assertEqual(["Jones, Mary"], digest.previous_order_flow)
        self.assertIn("Still receiving water", digest.body)


if __name__ == "__main__":
    unittest.main()
