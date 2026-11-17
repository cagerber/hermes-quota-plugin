"""Offline tests for the Xiaomi MiMo Token Plan quota fetcher."""

from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quota_providers import xiaomi as mod  # noqa: E402


_BALANCE = {
    "balance": "49.90",
    "currency": "USD",
    "giftBalance": "0.00",
    "cashBalance": "49.90",
}
_DETAIL = {
    "planCode": "standard:year",
    "planName": "Standard",
    "currentPeriodEnd": "2027-09-26 23:59:59",
    "expired": False,
}
_USAGE = {
    "monthUsage": {
        "percent": 0.0014,
        "items": [
            {"name": "month_total_token", "used": 178552001, "limit": 132000000000, "percent": 0.0014}
        ],
    }
}


class XiaomiParsingTests(unittest.TestCase):
    def test_monthly_token_percentage_uses_counts(self):
        result = mod.parse_usage(_BALANCE, _DETAIL, _USAGE)
        self.assertIsNone(result.unavailable_reason)
        self.assertEqual(result.plan, "Standard")
        self.assertEqual(len(result.windows), 1)
        self.assertEqual(result.windows[0].label, "Monthly tokens")
        self.assertAlmostEqual(result.windows[0].used_percent, 0.1353, places=4)
        self.assertIsNone(result.windows[0].reset_at)
        self.assertIn("178.6M of 132.0B", " ".join(result.details))
        self.assertEqual(result.account_balances[0].currency, "USD")
        self.assertEqual(result.account_balances[0].total_balance, "49.90")

    def test_balance_without_usage_is_still_a_card(self):
        result = mod.parse_usage(_BALANCE, None, None)
        self.assertIsNone(result.unavailable_reason)
        self.assertEqual(result.windows, [])
        self.assertEqual(result.account_balances[0].total_balance, "49.90")
        self.assertTrue(result.has_data())


class XiaomiSessionTests(unittest.TestCase):
    def test_missing_browser_session_is_truthful(self):
        with mock.patch.object(mod, "_cookie_header", return_value=(None, "browser-session-required")):
            result = mod.fetch_xiaomi_quota()
        self.assertEqual(result.unavailable_reason, "browser-session-required")
        self.assertIn("no API-key usage endpoint", " ".join(result.details))

    def test_fetch_combines_balance_detail_and_usage(self):
        def fake_get(path, cookie, **kwargs):
            return {
                "balance": (_BALANCE, None),
                "tokenPlan/detail": (_DETAIL, None),
                "tokenPlan/usage": (_USAGE, None),
            }[path]

        with mock.patch.object(mod, "_cookie_header", return_value=("session=test", None)), \
                mock.patch.object(mod, "_get", side_effect=fake_get):
            result = mod.fetch_xiaomi_quota()
        self.assertIsNone(result.unavailable_reason)
        self.assertEqual(result.plan, "Standard")
        self.assertEqual(result.windows[0].label, "Monthly tokens")


if __name__ == "__main__":
    unittest.main(verbosity=2)
