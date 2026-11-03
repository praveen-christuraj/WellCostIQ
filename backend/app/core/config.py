"""Application settings with deployment fail-closed validation.

Security posture is decided here, once:

* ``ENVIRONMENT=production`` refuses to start with a placeholder or short
  ``SECRET_KEY``, insecure cookies, or a CORS allow-list that is not an explicit
  set of HTTPS origins. The same check applies to SQLite: a production label is a
  promise, not a database-type hint.
* CORS entries are parsed into exact ``scheme://host[:port]`` origins. Wildcards,
  paths, credentials, ``null`` and opaque values are rejected at import time, so a
  misconfigured deployment fails loudly instead of reflecting an attacker origin.
  The harmless copy/paste accidents — a trailing slash, mixed case, an explicit
  default port — are normalized to the form a browser actually sends instead of
  taking the deployment down; normalization can only ever narrow a match.
* Password lifetime, history depth, lockout thresholds and request budgets are
  configuration, not constants hidden in the routers.

``SECRET_KEY`` and the bootstrap password stay ordinary strings so callers can
use them directly, but their values are masked by ``repr``/``str`` and by
:meth:`Settings.safe_summary` so a settings object can be logged safely.
"""
from functools import lru_cache
from urllib.parse import SplitResult, urlsplit

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_SECRET = "development-only-change-this-secret-before-deploying"
ENVIRONMENTS = ("development", "test", "staging", "production")
PLACEHOLDER_SECRETS = {
    DEV_SECRET,
    "replace-with-a-random-key-of-at-least-32-characters",
    "replace-with-a-long-cryptographically-random-secret",
    "changeme",
    "secret",
    "secret-key",
}


DEFAULT_PORTS = {"http": 80, "https": 443}


def _origin_problem(value: str) -> str | None:
    """Return why ``value`` is not a browser origin, or ``None`` if it is.

    A trailing slash, host case and an explicit default port are accepted here
    because :func:`canonical_origin` rewrites them into the exact form browsers
    send; everything that would widen the allow-list is still refused.
    """
    if not value or value == "null":
        return "an origin must name a scheme and a host"
    if "*" in value:
        return "wildcards are not allowed; list each origin exactly"
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"}:
        return "the scheme must be http or https"
    if not parts.hostname:
        return "a host is required"
    if parts.username or parts.password:
        return "credentials must not be included"
    if parts.path.rstrip("/") or parts.query or parts.fragment:
        return "only scheme://host[:port] is allowed"
    try:
        port = parts.port
    except ValueError:
        return "the port must be a number between 1 and 65535"
    if port is not None and not 1 <= port <= 65535:
        return "the port must be a number between 1 and 65535"
    return None


def _rebuild_origin(parts: SplitResult) -> str:
    """Assemble ``scheme://host[:port]`` from parsed parts, dropping defaults."""
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    if ":" in host:  # IPv6 literal: the Origin header keeps the brackets
        host = f"[{host}]"
    try:
        port = parts.port
    except ValueError:
        return ""
    if port is not None and port != DEFAULT_PORTS[scheme]:
        host = f"{host}:{port}"
    return f"{scheme}://{host}"


def canonical_origin(value: str) -> str:
    """Return ``value`` as the exact ``scheme://host[:port]`` a browser sends.

    Trailing slashes, upper-case scheme/host and the scheme's default port are
    normalized away; no path, query, fragment, credential or wildcard survives.
    Anything that is not an http(s) origin returns ``""``, which cannot match an
    allow-list entry — callers fail closed instead of raising on hostile input.
    """
    origin = (value or "").strip()
    if _origin_problem(origin):
        return ""
    return _rebuild_origin(urlsplit(origin))


def origin_from_url(value: str) -> str:
    """Reduce an absolute http(s) URL to its origin, or ``""`` if it is not one.

    This is the ``Referer`` counterpart of :func:`canonical_origin`: a Referer
    names a page, so its path is expected and discarded rather than rejected.
    """
    url = (value or "").strip()
    if not url or "*" in url:
        return ""
    parts = urlsplit(url)
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
        return ""
    return _rebuild_origin(parts)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "WellCostIQ"
    app_tagline: str = "Well Cost Estimation & Tracking"
    environment: str = "development"

    database_url: str = "sqlite:///./wellcosting.db"
    secret_key: str = DEV_SECRET
    access_token_minutes: int = 15
    refresh_token_days: int = 7
    password_reset_minutes: int = 30
    secure_cookies: bool = False
    max_active_sessions: int = 10

    # Password lifecycle. ``password_max_age_days=0`` disables age expiry, which is
    # only appropriate where an external identity provider enforces rotation.
    password_min_length: int = 12
    password_max_length: int = 128
    password_history_limit: int = 5
    password_max_age_days: int = 90
    password_expiry_warning_days: int = 14
    # None means "decide from ENVIRONMENT": production requires the new account to
    # pick its own password, development keeps the shorter local flow.
    force_password_change_on_create: bool | None = None

    # Sign-in and recovery budgets (per client address, shared by API workers).
    login_attempt_limit: int = 30
    password_reset_attempt_limit: int = 10
    change_password_attempt_limit: int = 10
    forgot_password_attempt_limit: int = 5
    throttle_window_minutes: int = 15
    max_failed_logins: int = 5
    lockout_minutes: int = 15

    # Vendors/PO-SO attachments are stored in the workspace database; this caps one file.
    document_max_size_mb: int = 15
    cors_origins: str = "http://localhost:5173"
    # Uvicorn's --forwarded-allow-ips is the real control; this list decides which
    # peers' X-Forwarded-For / X-Real-IP headers are believed by the application.
    trusted_proxy_ips: str = ""
    # Swagger/ReDoc/OpenAPI are development aids; production defaults them off.
    enable_api_docs: bool | None = None
    max_json_body_mb: int = 10

    # First-run administrator bootstrap. Ask at startup when the database has no owner.
    bootstrap_admin_on_startup: bool = True
    # Backup & Recovery. Archives live under this root; only folders beneath it are writable.
    backup_directory: str = ""
    # The in-process scheduler is safe to leave on; it only acts when a workspace enables a schedule.
    backup_scheduler_enabled: bool = True
    backup_max_upload_mb: int = 2048
    # Optional unattended seeding for a first boot with no terminal. Leave blank to be asked.
    seed_org_slug: str = ""
    seed_org_name: str = ""
    seed_owner_name: str = ""
    seed_admin_email: str = ""
    seed_admin_password: str = ""

    # ------------------------------------------------------------------ helpers
    @field_validator("cors_origins")
    @classmethod
    def validate_cors_origins(cls, value: str) -> str:
        """Validate every entry and store the allow-list in canonical form.

        The stored string is what :attr:`cors_origin_list` hands to the CORS
        middleware and the origin guard, so it must be byte-identical to the
        ``Origin`` header a browser sends for the same site.
        """
        origins: list[str] = []
        for item in value.split(","):
            origin = item.strip()
            if not origin:
                continue
            problem = _origin_problem(origin)
            if problem:
                raise ValueError(f"CORS origin {origin!r} is invalid: {problem}")
            canonical = canonical_origin(origin)
            if canonical not in origins:
                origins.append(canonical)
        return ",".join(origins)

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin for origin in self.cors_origins.split(",") if origin]

    @property
    def trusted_proxies(self) -> list[str]:
        return [item.strip() for item in self.trusted_proxy_ips.split(",") if item.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def force_change_on_create(self) -> bool:
        if self.force_password_change_on_create is None:
            return self.is_production
        return self.force_password_change_on_create

    @property
    def docs_enabled(self) -> bool:
        """API documentation is public unless production says otherwise."""
        return (not self.is_production) if self.enable_api_docs is None else self.enable_api_docs

    @model_validator(mode="after")
    def validate_deployment(self):
        self.environment = self.environment.strip().lower()
        if self.environment not in ENVIRONMENTS:
            raise ValueError(f"ENVIRONMENT must be one of: {', '.join(ENVIRONMENTS)}")
        if not 5 <= self.access_token_minutes <= 120:
            raise ValueError("ACCESS_TOKEN_MINUTES must be between 5 and 120")
        if not 1 <= self.refresh_token_days <= 30:
            raise ValueError("REFRESH_TOKEN_DAYS must be between 1 and 30")
        if not 0 <= self.password_max_age_days <= 365:
            raise ValueError("PASSWORD_MAX_AGE_DAYS must be between 0 and 365")
        if not 3 <= self.password_history_limit <= 24:
            raise ValueError("PASSWORD_HISTORY_LIMIT must be between 3 and 24")
        if not 8 <= self.password_min_length <= self.password_max_length <= 128:
            raise ValueError("Password length limits must satisfy 8 <= min <= max <= 128")
        if not 1 <= self.max_failed_logins <= 20:
            raise ValueError("MAX_FAILED_LOGINS must be between 1 and 20")
        if not 1 <= self.lockout_minutes <= 1440:
            raise ValueError("LOCKOUT_MINUTES must be between 1 and 1440")

        if self.is_production:
            if not self.secret_key or self.secret_key in PLACEHOLDER_SECRETS or len(self.secret_key) < 32:
                raise ValueError(
                    "Set a unique SECRET_KEY of at least 32 characters before running in production "
                    "(generate one with: openssl rand -hex 32)"
                )
            if not self.secure_cookies:
                raise ValueError("SECURE_COOKIES must be true in production")
            origins = self.cors_origin_list
            if not origins:
                raise ValueError("CORS_ORIGINS must list the approved HTTPS front-end origin(s) in production")
            insecure = [origin for origin in origins if not origin.startswith("https://")]
            if insecure:
                raise ValueError("production CORS_ORIGINS must use https: " + ", ".join(insecure))
        elif not self.database_url.startswith("sqlite"):
            if self.secret_key.startswith("development-only") or len(self.secret_key) < 32:
                raise ValueError("Set a unique SECRET_KEY of at least 32 characters before using PostgreSQL")
        return self

    # ------------------------------------------------------------------ masking
    _SECRET_FIELDS = ("secret_key", "seed_admin_password", "database_url", "seed_admin_email")

    @classmethod
    def _mask(cls, value: str) -> str:
        if not value:
            return ""
        if "@" in value and "://" not in value:
            name, _, domain = value.partition("@")
            return f"{name[:2]}***@{domain}"
        if "://" in value:
            scheme, _, rest = value.partition("://")
            if "@" in rest:
                credentials, _, host = rest.rpartition("@")
                return f"{scheme}://***@{host}"
            return value
        return f"***{value[-4:]}" if len(value) > 6 else "***"

    def safe_summary(self) -> dict[str, str]:
        """Settings safe to log: secrets replaced with a masked marker."""
        return {key: self._mask(str(getattr(self, key, "") or "")) for key in self._SECRET_FIELDS}

    def __repr__(self) -> str:  # pragma: no cover - exercised through log assertions
        masked = self.safe_summary()
        return (
            f"Settings(environment={self.environment!r}, database_url={masked['database_url']!r}, "
            f"secret_key={masked['secret_key']!r}, secure_cookies={self.secure_cookies!r}, "
            f"cors_origins={self.cors_origins!r})"
        )

    __str__ = __repr__


@lru_cache
def get_settings() -> Settings:
    return Settings()
