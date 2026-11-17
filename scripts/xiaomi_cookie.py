#!/usr/bin/env python3
"""Out-of-process browser-cookie reader for the Xiaomi quota fetcher.

Hermes' bundled Python 3.14 does not ship ``cryptography`` or
``secretstorage``, while the desktop Python usually does.  This helper is
invoked only when the in-process reader reports a crypto/keyring failure.  It
prints a single JSON object; the cookie value stays in the pipe and is never
logged by the caller.

Usage: python3 scripts/xiaomi_cookie.py
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from quota_providers.browser_cookies import ChromeCookieError, load_chrome_cookie_header
except Exception as exc:  # noqa: BLE001 - report a typed failure to the caller
    print(json.dumps({"reason": f"helper-import:{type(exc).__name__}"}))
    raise SystemExit(0)

NAMES = (
    "api-platform_serviceToken",
    "userId",
    "api-platform_ph",
    "api-platform_slh",
)


def main() -> int:
    try:
        header = load_chrome_cookie_header("xiaomimimo.com", NAMES)
    except ChromeCookieError as exc:
        print(json.dumps({"reason": exc.reason}))
        return 0
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"reason": f"helper-error:{type(exc).__name__}"}))
        return 0
    if not header:
        print(json.dumps({"reason": "browser-session-required"}))
        return 0
    print(json.dumps({"header": header}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
