import tempfile
import unittest
from datetime import date
from pathlib import Path

from water_reporter import build_digest, load_daily_orders, parse_sandstone_orders, save_daily_orders


SAMPLE_HTML = """
<html>
  <body>
    <table>
      <tr><th>Canal</th><th>Member</th><th>Amount</th></tr>
      <tr><td>Sandstone</td><td>Neighbor A</td><td>10</td></tr>
      <tr><td>South Bench</td><td>Neighbor B</td><td>5</td></tr>
      <tr><td>Sandstone Canal</td><td>Neighbor C</td><td>7</td></tr>
    </table>
  </body>
</html>
"""


class WaterReporterTests(unittest.TestCase):
    def test_parse_sandstone_orders_filters_to_sandstone(self):
        orders = parse_sandstone_orders(SAMPLE_HTML)
        self.assertEqual(2, len(orders))
        self.assertEqual({"Neighbor A", "Neighbor C"}, {order["Member"] for order in orders})

    def test_save_and_load_daily_orders(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            target_dir = Path(tmp_dir)
            report_date = date(2026, 5, 27)
            expected_orders = [{"Canal": "Sandstone", "Member": "Neighbor A", "Amount": "10"}]

            path = save_daily_orders(target_dir, report_date, expected_orders)

            self.assertTrue(path.exists())
            self.assertEqual(expected_orders, load_daily_orders(target_dir, report_date))

    def test_build_digest_identifies_previous_order_flow(self):
        todays = [{"Canal": "Sandstone", "Member": "Neighbor A", "Amount": "10"}]
        prior = [
            {"Canal": "Sandstone", "Member": "Neighbor A", "Amount": "8"},
            {"Canal": "Sandstone", "Member": "Neighbor D", "Amount": "6"},
        ]

        digest = build_digest(date(2026, 5, 27), todays, prior)

        self.assertEqual(["Neighbor A"], digest.active_today)
        self.assertEqual(["Neighbor D"], digest.previous_order_flow)
        self.assertIn("Still receiving water", digest.body)


if __name__ == "__main__":
    unittest.main()
