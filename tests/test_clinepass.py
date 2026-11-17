"""Offline tests for the ClinePass quota fetcher."""

from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quota_providers import clinepass as mod  # noqa: E402


_LIMITS = {
    "limits": [
        {"type": "five_hour", "percentUsed": 0, "resetsAt": "2026-11-17T15:45:00Z"},
        {"type": "weekly", "percentUsed": 40, "resetsAt": "2026-11-23T11:37:15Z"},
        {"type": "monthly", "percentUsed": 44, "resetsAt": "2026-12-07T16:05:08Z"},
    ]
}
_PLAN = {
    "plan": {"displayName": "Cline Pass (Monthly)"},
    "currentPeriodEnd": "2026-12-03T00:00:00Z",
}


class ClinePassParsingTests(unittest.TestCase):
    def test_three_windows_and_plan(self):
        result = mod.parse_limits(_LIMITS, _PLAN)
        self.assertIsNone(result.unavailable_reason)
        self.assertEqual(result.plan, "Cline Pass (Monthly)")
        self.assertEqual([w.label for w in result.windows], ["5-hour", "Weekly", "Monthly"])
        self.assertEqual([w.used_percent for w in result.windows], [0.0, 40.0, 44.0])
        self.assertEqual(result.windows[0].reset_at, "2026-11-17T15:45:00+00:00")
        self.assertIn("Billing period renews 2026-12-03", result.details)

    def test_missing_plan_does_not_hide_windows(self):
        result = mod.parse_limits(_LIMITS, None)
        self.assertEqual(len(result.windows), 3)
        self.assertEqual(result.plan, "ClinePass")

    def test_empty_payload_is_no_data(self):
        result = mod.parse_limits({"limits": []}, None)
        self.assertEqual(result.unavailable_reason, "no-data")


class ClinePassCredentialTests(unittest.TestCase):
    def test_no_token_is_no_credentials(self):
        with mock.patch.object(mod, "resolve_token", return_value=None):
            result = mod.fetch_clinepass_quota()
        self.assertEqual(result.unavailable_reason, "no-credentials")

    def test_fetch_uses_usage_and_plan_endpoints(self):
        calls = []

        def fake_get(path, token, **kwargs):
            calls.append(path)
            if path.endswith("usage-limits"):
                return (_LIMITS, None)
            return (_PLAN, None)

        with mock.patch.object(mod, "resolve_token", return_value="synthetic-token"), \
                mock.patch.object(mod, "_get", side_effect=fake_get):
            result = mod.fetch_clinepass_quota()
        self.assertIsNone(result.unavailable_reason)
        self.assertEqual(calls, ["users/me/plan/usage-limits", "users/me/plan"])

    def test_auth_failure_is_surfaced(self):
        with mock.patch.object(mod, "resolve_token", return_value="synthetic-token"), \
                mock.patch.object(mod, "_get", return_value=(None, "auth-failed")):
            result = mod.fetch_clinepass_quota()
        self.assertEqual(result.unavailable_reason, "auth-failed")


if __name__ == "__main__":
    unittest.main(verbosity=2)
