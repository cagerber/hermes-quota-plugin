#!/usr/bin/env python3
"""Read the Antigravity OAuth blob from the Linux Secret Service.

Antigravity 1.5 stores its token through zalando/go-keyring in the login
collection (service ``gemini``, username ``antigravity``) instead of writing
the legacy ``antigravity-oauth-token`` file. The value is the same raw JSON
dict the file reader expects.

Only the secret bytes are returned, base64-wrapped, so the caller can decode
them without text-encoding surprises. The secret is never logged.
"""

import base64
import json
import sys


def main() -> int:
    try:
        import secretstorage
    except Exception:
        print(json.dumps({"reason": "secretstorage-unavailable"}))
        return 0
    try:
        bus = secretstorage.dbus_init()
        for collection in secretstorage.get_all_collections(bus):
            for item in collection.get_all_items():
                attrs = item.get_attributes() or {}
                if attrs.get("service") != "gemini" or attrs.get("username") != "antigravity":
                    continue
                if getattr(item, "is_locked", lambda: False)():
                    print(json.dumps({"reason": "keyring-locked"}))
                    return 0
                secret = item.get_secret()
                if not secret:
                    print(json.dumps({"reason": "secret-empty"}))
                    return 0
                print(json.dumps({"secret_b64": base64.b64encode(secret).decode("ascii")}))
                return 0
        print(json.dumps({"reason": "secret-not-found"}))
    except Exception as exc:  # noqa: BLE001 - report a reason, never the secret
        print(json.dumps({"reason": f"secret-read-failed:{type(exc).__name__}"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
