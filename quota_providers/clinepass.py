"""ClinePass subscription quota fetcher — plugin standalone copy.

ClinePass exposes the same three windows shown in the Cline dashboard:

    GET https://api.cline.bot/api/v1/users/me/plan/usage-limits
    GET https://api.cline.bot/api/v1/users/me/plan

The first response carries ``data.limits[]`` with ``type`` (``five_hour``,
``weekly``, ``monthly``), ``percentUsed`` and ``resetsAt``.  The second adds
the plan display name and the billing-period end.

The token is the Hermes credential-pool entry for the ``clinepass`` model
provider (OAuth import or ``CLINE_API_KEY``).  The fetcher never writes to the
pool and never logs the token.  It deliberately does not import the ClinePass
model-provider plugin: the quota collector must work when only the quota
plugin is installed.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Optional

from .base import QuotaResult, QuotaWindow, build_unavailable, urlopen_no_redirect

_PROVIDER_ID = "clinepass"
_BASE_URL = "https://api.cline.bot/api/v1"
_LABELS = {
    "five_hour": "5-hour",
    "weekly": "Weekly",
    "monthly": "Monthly",
}
_ORDER = ("five_hour", "weekly", "monthly")


def resolve_token() -> Optional[str]:
    """Resolve the ClinePass token without changing the credential pool."""
    try:
        from agent.credential_pool import load_pool

        entry = load_pool(_PROVIDER_ID).select()
        token = getattr(entry, "runtime_api_key", None) if entry else None
        if isinstance(token, str) and token.strip():
            return token.strip()
    except Exception:  # noqa: BLE001 - standalone/older Hermes has no pool entry
        pass
    try:
        from agent.secret_scope import get_secret

        token = get_secret("CLINE_API_KEY")
        if isinstance(token, str) and token.strip():
            return token.strip()
    except Exception:  # noqa: BLE001 - no Hermes secret scope
        pass
    token = os.environ.get("CLINE_API_KEY", "")
    return token.strip() or None


def _get(path: str, token: str, *, timeout: float = 8.0) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    request = urllib.request.Request(
        f"{_BASE_URL}/{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "hermes-quota-plugin",
        },
        method="GET",
    )
    try:
        with urlopen_no_redirect(request, timeout=timeout) as response:
            body = response.read(1024 * 1024 + 1)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            return None, "auth-failed"
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
    if payload.get("success") is False:
        return None, "no-data"
    data = payload.get("data")
    return (data, None) if isinstance(data, dict) else (None, "no-data")


def _iso(value: Any) -> Optional[str]:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _percent(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return max(0.0, min(100.0, float(value)))


def parse_limits(limits_data: dict[str, Any], plan_data: Optional[dict[str, Any]]) -> QuotaResult:
    rows = {
        str(row.get("type")): row
        for row in (limits_data.get("limits") or [])
        if isinstance(row, dict)
    }
    windows: list[QuotaWindow] = []
    seen: set[str] = set()
    for kind in (*_ORDER, *(key for key in rows if key not in _ORDER)):
        if kind in seen:
            continue
        seen.add(kind)
        row = rows.get(kind)
        if not isinstance(row, dict):
            continue
        used = _percent(row.get("percentUsed"))
        if used is None:
            continue
        windows.append(
            QuotaWindow(
                label=_LABELS.get(kind, kind.replace("_", " ").title()),
                used_percent=round(used, 2),
                reset_at=_iso(row.get("resetsAt")),
            )
        )
    if not windows:
        return build_unavailable(_PROVIDER_ID, "no-data")

    plan = (plan_data or {}).get("plan")
    plan_name = plan.get("displayName") if isinstance(plan, dict) else None
    details: list[str] = []
    period_end = _iso((plan_data or {}).get("currentPeriodEnd"))
    if period_end:
        details.append(f"Billing period renews {period_end[:10]}")
    return QuotaResult(
        label=_PROVIDER_ID,
        windows=windows,
        plan=str(plan_name).strip() if isinstance(plan_name, str) and plan_name.strip() else "ClinePass",
        details=details,
    )


def fetch_clinepass_quota() -> QuotaResult:
    token = resolve_token()
    if not token:
        return build_unavailable(_PROVIDER_ID, "no-credentials")

    limits_data, reason = _get("users/me/plan/usage-limits", token)
    if limits_data is None:
        return build_unavailable(_PROVIDER_ID, reason or "no-data")

    plan_data: Optional[dict[str, Any]] = None
    plan_result, _plan_reason = _get("users/me/plan", token, timeout=5.0)
    if plan_result is not None:
        plan_data = plan_result
    return parse_limits(limits_data, plan_data)


from .registry import register as _register  # noqa: E402

_register(_PROVIDER_ID)(fetch_clinepass_quota)
