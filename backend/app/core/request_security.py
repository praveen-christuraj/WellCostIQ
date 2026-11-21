"""Client identity and per-client request budgets.

``request.client.host`` is the only address the transport actually knows. A
``X-Forwarded-For`` header is attacker-controlled text unless the immediate peer
is a proxy we configured, so it is honoured **only** when the connecting address
is in ``TRUSTED_PROXY_IPS`` — and then the rightmost address that is not itself a
trusted proxy is used. This closes the ``X-Forwarded-For`` rotation bypass that
let an unauthenticated caller reset a recovery budget, and it stops forged
addresses from entering the audit trail.
"""
import hashlib
import hmac
import ipaddress
from datetime import timedelta

from fastapi import HTTPException, Request
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.time import utcnow
from app.models import PasswordResetAttempt


def _network(value: str):
    try:
        return ipaddress.ip_network(value.strip(), strict=False)
    except ValueError:
        return None


def _trusted(value: str, networks) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return any(address in network for network in networks if network is not None)


def _valid(value: str) -> bool:
    try:
        ipaddress.ip_address(value.strip())
    except ValueError:
        return False
    return True


def proxy_networks():
    return [network for network in (_network(item) for item in get_settings().trusted_proxies) if network is not None]


def client_ip(request: Request) -> str:
    """The best address available without trusting an unverified header."""
    peer = request.client.host if request.client else "unknown"
    networks = proxy_networks()
    if networks and _trusted(peer, networks):
        forwarded = request.headers.get("x-forwarded-for", "")
        candidates = [item.strip() for item in forwarded.split(",") if item.strip()]
        for candidate in reversed(candidates):
            if _valid(candidate) and not _trusted(candidate, networks):
                return candidate[:45]
        real_ip = (request.headers.get("x-real-ip") or "").strip()
        if _valid(real_ip) and not _trusted(real_ip, networks):
            return real_ip[:45]
    return peer[:45]


def client_key(request: Request, action: str) -> str:
    """Keyed digest of one client's budget for one action; never the raw address."""
    return hmac.new(
        get_settings().secret_key.encode(),
        f"{action}:{client_ip(request)}".encode(),
        hashlib.sha256,
    ).hexdigest()


def throttle(
    db: Session, request: Request, action: str, limit: int, *,
    window_minutes: int | None = None, subject: str | None = None,
) -> None:
    """Atomically spend a sliding-window budget in an independent transaction.

    PostgreSQL serializes each keyed client/action with an advisory xact lock;
    SQLite serializes writers with BEGIN IMMEDIATE. Business state in ``db`` is
    never committed here. Edge throttling is still required for volumetric abuse.
    """
    window = window_minutes or get_settings().throttle_window_minutes
    key = client_key(request, action) if subject is None else hmac.new(
        get_settings().secret_key.encode(), f"account:{action}:{subject}".encode(), hashlib.sha256,
    ).hexdigest()
    with Session(bind=db.get_bind()) as ledger:
        dialect = ledger.get_bind().dialect.name
        if dialect == "postgresql":
            lock_id = int.from_bytes(bytes.fromhex(key)[:8], "big", signed=True)
            ledger.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_id})
        elif dialect == "sqlite":
            ledger.execute(text("BEGIN IMMEDIATE"))
        else:
            raise RuntimeError("Request budgets require PostgreSQL or SQLite")
        now = utcnow()
        count = ledger.scalar(
            select(func.count(PasswordResetAttempt.id)).where(
                PasswordResetAttempt.ip_hash == key,
                PasswordResetAttempt.attempted_at >= now - timedelta(minutes=window),
            )
        ) or 0
        if count >= limit:
            raise HTTPException(
                429, f"Too many attempts. Wait {window} minutes and try again.",
                headers={"Retry-After": str(window * 60)},
            )
        ledger.add(PasswordResetAttempt(ip_hash=key, attempted_at=now))
        retention = timedelta(days=max(1, (window + 1439) // 1440))
        ledger.execute(delete(PasswordResetAttempt).where(PasswordResetAttempt.attempted_at < now - retention))
        ledger.commit()
