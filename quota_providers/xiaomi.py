"""Xiaomi MiMo Token Plan quota fetcher — plugin standalone copy.

Xiaomi has no API-key-authenticated quota endpoint.  The authoritative numbers
live behind the logged-in ``platform.xiaomimimo.com`` web console:

    GET https://platform.xiaomimimo.com/api/v1/balance
    GET https://platform.xiaomimimo.com/api/v1/tokenPlan/detail
    GET https://platform.xiaomimimo.com/api/v1/tokenPlan/usage

Those requests require the console session cookies
``api-platform_serviceToken`` and ``userId`` (plus the optional
``api-platform_ph`` / ``api-platform_slh``).  We read the Chromium-family
cookie store locally, decrypt it through the browser's Safe Storage key, and
send only those four cookie names.  No API key is used, no cookie is logged,
and the browser database is opened from a temporary copy so a running browser
is never disturbed.

The Token Plan key itself (``tp-...``) works for inference at
``https://token-plan-sgp.xiaomimimo.com/v1`` but returns 404 on every usage
path; the platform API rejects it and requires the web session.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .base import AccountBalance, QuotaResult, QuotaWindow, build_unavailable, urlopen_no_redirect

_PROVIDER_ID = "xiaomi-token-plan-sgp"
_BASE_URL = "https://platform.xiaomimimo.com/api/v1"
_COOKIE_NAMES = (
    "api-platform_serviceToken",
    "userId",
    "api-platform_ph",
    "api-platform_slh",
)
_REQUIRED_COOKIES = {"api-platform_serviceToken", "userId"}
_TIMEOUT_S = 12.0
_COOKIE_BRIDGE = Path(__file__).resolve().parents[1] / "scripts" / "xiaomi_cookie.py"


def _bridge_header() -> tuple[Optional[str], Optional[str]]:
    """Read the browser session with a Python that has crypto+secretstorage.

    Hermes' bundled interpreter is deliberately minimal; the desktop Python
    normally has both packages.  The helper returns only the selected cookies.
    """
    if not _COOKIE_BRIDGE.is_file():
        return None, "browser-session-unreadable"
    candidates = [shutil.which("python3"), "/usr/bin/python3"]
    seen: set[str] = set()
    for executable in candidates:
        if not executable or executable in seen:
            continue
        seen.add(executable)
        try:
            completed = subprocess.run(
                [executable, str(_COOKIE_BRIDGE)],
                capture_output=True,
                text=True,
                timeout=20,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if completed.returncode != 0 or not (completed.stdout or "").strip():
            continue
        try:
            payload = json.loads(completed.stdout)
        except ValueError:
            continue
        if isinstance(payload, dict) and isinstance(payload.get("header"), str) and payload["header"].strip():
            return payload["header"].strip(), None
        reason = payload.get("reason") if isinstance(payload, dict) else None
        return None, str(reason or "browser-session-unreadable")
    return None, "browser-session-unreadable"


def _cookie_header() -> tuple[Optional[str], Optional[str]]:
    """Return a console-session Cookie header and an optional failure reason."""
    override = (os.environ.get("XIAOMI_MIMO_COOKIE") or "").strip()
    if override:
        return override, None
    try:
        from .browser_cookies import ChromeCookieError, load_chrome_cookie_header

        header = load_chrome_cookie_header("xiaomimimo.com", _COOKIE_NAMES)
        if header:
            present = {
                part.split("=", 1)[0].strip()
                for part in header.split(";")
                if "=" in part
            }
            if _REQUIRED_COOKIES.issubset(present):
                return header, None
        return None, "browser-session-required"
    except Exception as exc:  # noqa: BLE001 - browser store is optional
        reason = getattr(exc, "reason", None)
        reason = str(reason or "browser-session-unreadable")
        if reason in {
            "chrome-crypto-missing",
            "chrome-decrypt-failed",
            "chrome-keychain-denied",
            "browser-session-unreadable",
        }:
            return _bridge_header()
        return None, reason


def _get(path: str, cookie: str, *, timeout: float = _TIMEOUT_S) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    request = urllib.request.Request(
        f"{_BASE_URL}/{path}",
        headers={
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Cookie": cookie,
            "Origin": "https://platform.xiaomimimo.com",
            "Referer": "https://platform.xiaomimimo.com/#/console/balance",
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36"
            ),
            "x-timeZone": "UTC+02:00",
        },
        method="GET",
    )
    try:
        with urlopen_no_redirect(request, timeout=timeout) as response:
            body = response.read(1024 * 1024 + 1)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403) or 300 <= exc.code < 400:
            return None, "login-required"
        return None, f"http-{exc.code}"
    except Exception as exc:  # noqa: BLE001 - fail-open by contract
        return None, f"fetch-error:{type(exc).__name__}"
    if len(body) > 1024 * 1024:
        return None, "response-too-large"
    try:
        payload = json.loads(body)
    except Exception:
        return None, "bad-json"
    if not isinstance(payload, dict):
        return None, "bad-json"
    code = payload.get("code")
    if code in (401, 403):
        return None, "login-required"
    if code not in (None, 0):
        return None, f"api-{code}"
    data = payload.get("data")
    return (data, None) if isinstance(data, dict) else (None, "no-data")


def _num(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _iso(value: Any) -> Optional[str]:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc).isoformat()
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _compact(number: float) -> str:
    if number >= 1_000_000_000:
        return f"{number / 1_000_000_000:.1f}B"
    if number >= 1_000_000:
        return f"{number / 1_000_000:.1f}M"
    if number >= 1_000:
        return f"{number / 1_000:.1f}K"
    return f"{number:,.0f}"


def parse_usage(
    balance: Optional[dict[str, Any]],
    detail: Optional[dict[str, Any]],
    usage: Optional[dict[str, Any]],
) -> QuotaResult:
    detail = detail or {}
    usage = usage or {}
    plan_name = detail.get("planName") or detail.get("planCode")
    plan = str(plan_name).strip() if isinstance(plan_name, str) and plan_name.strip() else None
    period_end = _iso(detail.get("currentPeriodEnd"))
    windows: list[QuotaWindow] = []
    details: list[str] = []
    if period_end:
        details.append(f"Plan period ends {period_end[:10]}")
    if detail.get("expired") is True:
        details.append("Token Plan is marked expired")

    month = usage.get("monthUsage")
    items = month.get("items") if isinstance(month, dict) else None
    chosen = None
    for item in items if isinstance(items, list) else ():
        if not isinstance(item, dict):
            continue
        used = _num(item.get("used"))
        limit = _num(item.get("limit"))
        if used is not None and limit is not None and limit > 0:
            chosen = (item, used, limit)
            break
    if chosen is not None:
        item, used, limit = chosen
        used_percent = max(0.0, min(100.0, used / limit * 100.0))
        reset = _iso(month.get("resetAt") or month.get("resetTime")) if isinstance(month, dict) else None
        windows.append(
            QuotaWindow(
                label="Monthly tokens",
                used_percent=round(used_percent, 4),
                reset_at=reset,
            )
        )
        details.append(f"Tokens: {_compact(used)} of {_compact(limit)} used")

    balances: list[AccountBalance] = []
    if isinstance(balance, dict):
        total = balance.get("balance")
        if total is not None:
            currency = str(balance.get("currency") or "USD").strip() or "USD"
            balances.append(
                AccountBalance(
                    currency=currency,
                    total_balance=str(total),
                    granted_balance=str(balance.get("giftBalance")) if balance.get("giftBalance") is not None else None,
                    topped_up_balance=str(balance.get("cashBalance")) if balance.get("cashBalance") is not None else None,
                )
            )
            details.append(f"Wallet: {currency} {total}")

    if not windows and not details and not balances:
        return build_unavailable(_PROVIDER_ID, "no-data")
    return QuotaResult(
        label=_PROVIDER_ID,
        windows=windows,
        plan=plan,
        details=details,
        account_balances=balances,
    )


def fetch_xiaomi_quota() -> QuotaResult:
    cookie, reason = _cookie_header()
    if not cookie:
        return build_unavailable(
            _PROVIDER_ID,
            reason or "browser-session-required",
            details=[
                "Xiaomi Token Plan has no API-key usage endpoint; "
                "log in to platform.xiaomimimo.com in a supported browser."
            ],
        )

    balance, balance_reason = _get("balance", cookie)
    detail, _detail_reason = _get("tokenPlan/detail", cookie)
    usage, usage_reason = _get("tokenPlan/usage", cookie)
    if balance is None and detail is None and usage is None:
        return build_unavailable(
            _PROVIDER_ID,
            balance_reason or usage_reason or "no-data",
            details=["Xiaomi platform session is present but its usage API failed."],
        )
    return parse_usage(balance, detail, usage)


from .registry import register as _register  # noqa: E402

_register(_PROVIDER_ID)(fetch_xiaomi_quota)
