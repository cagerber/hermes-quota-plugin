"""Regression tests for Anthropic usage using an OAuth-only resolver."""

from __future__ import annotations

import os
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quota_providers import builtin  # noqa: E402


class AnthropicOAuthUsageTests(unittest.TestCase):
    def test_usage_payload_uses_oauth_resolver_not_api_key_resolver(self):
        with mock.patch.object(builtin, "_core_anthropic_oauth_token", return_value="synthetic-oauth") as oauth, \
                mock.patch.object(builtin, "_core_anthropic_token", return_value="synthetic-api-key") as api_key, \
                mock.patch.object(builtin, "_core_anthropic_is_oauth", return_value=True), \
                mock.patch.object(builtin, "_request_anthropic_usage", return_value=({"limits": []}, None)) as request:
            payload, reason = builtin._anthropic_usage_payload()
        self.assertEqual(payload, {"limits": []})
        self.assertIsNone(reason)
        oauth.assert_called_once_with()
        api_key.assert_not_called()
        request.assert_called_once_with("synthetic-oauth")

    def test_oauth_helper_never_falls_back_to_api_key(self):
        fake = types.ModuleType("agent.anthropic_credentials")
        fake._first_env = lambda *args: ""
        fake._resolve_anthropic_pool_token = lambda **kwargs: None
        fake.read_claude_code_credentials = lambda: {"accessToken": "synthetic-oauth"}
        fake._resolve_claude_code_token_from_credentials = lambda creds: "synthetic-oauth"
        with mock.patch.dict(sys.modules, {"agent.anthropic_credentials": fake}):
            self.assertEqual(builtin._core_anthropic_oauth_token(), "synthetic-oauth")


if __name__ == "__main__":
    unittest.main(verbosity=2)
