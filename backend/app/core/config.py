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
import re
from urllib.parse import SplitResult, parse_qs, urlsplit

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_SECRET = "development-only-change-this-secret-before-deploying"  # nosec B105  # Rejected outside local development.
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
OLLAMA_KNOWN_ENDPOINT_SUFFIXES = ("/api/chat", "/api/generate", "/v1/chat/completions")
_OLLAMA_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,119}$")
_OLLAMA_KEEP_ALIVE_RE = re.compile(r"^-?[0-9]+(?:\.[0-9]+)?(?:ns|us|ms|s|m|h)?$")


def _ollama_url_problem(value: str) -> str | None:
    """Return why ``value`` cannot be an Ollama server base URL, or ``None``."""
    if not value:
        return "OLLAMA_BASE_URL must name a scheme and host, e.g. http://192.168.1.50:11434"
    if "*" in value or any(ch.isspace() for ch in value):
        return "OLLAMA_BASE_URL must not contain wildcards or spaces"
    parts = urlsplit(value)
    if parts.scheme.lower() not in {"http", "https"}:
        return "the scheme must be http or https"
    if not parts.hostname:
        return "a host or LAN IP address is required"
    if parts.username or parts.password:
        return "credentials must not be embedded in OLLAMA_BASE_URL; use OLLAMA_API_KEY instead"
    if parts.query or parts.fragment:
        return "query strings and fragments are not allowed in OLLAMA_BASE_URL"
    if ".." in (parts.path or "").split("/"):
        return "relative '..' segments are not allowed in OLLAMA_BASE_URL"
    try:
        port = parts.port
    except ValueError:
        return "the port must be a number between 1 and 65535"
    if port is not None and not 1 <= port <= 65535:
        return "the port must be a number between 1 and 65535"
    return None


def _ollama_path_problem(value: str, name: str) -> str | None:
    """Validate an Ollama API route path such as ``/api/chat`` or ``/api/tags``."""
    if not value or not value.startswith("/"):
        return f"{name} must start with '/', e.g. /api/chat"
    if value.startswith("//") or "://" in value or any(ch.isspace() for ch in value):
        return f"{name} must be a relative path on OLLAMA_BASE_URL, without scheme or spaces"
    parts = urlsplit(value)
    if parts.query or parts.fragment:
        return f"{name} must not contain query parameters or fragments"
    if ".." in parts.path.split("/"):
        return f"{name} must not contain '..' path segments"
    return None


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
    # Optional application-layer Host allowlist. Nginx is the primary Compose
    # control; Render sets its exact service hostname to protect direct access.
    allowed_hosts: str = ""
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
    # Entry checks on daily cost sheets. They are advice computed from the
    # workspace's own sheets: no model, no outside service. Turning them off
    # hides every finding and stops the profile refresh.
    entry_checks_enabled: bool = True
    # How many sheets of the same AFE, nearest in date, a sheet is compared with.
    entry_check_history_sheets: int = 30
    # Workspace item profiles: how far back they read the cost ledger, and how
    # long one is used before it is rebuilt.
    entry_check_profile_window_days: int = 730
    entry_check_profile_max_age_hours: int = 24
    # Offline LAN AI model (Ollama running on this host or another machine on the
    # same local network). Off by default so every module runs deterministically
    # without any network call until an operator enables it in .env.
    ollama_enabled: bool = False
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_api_path: str = "/api/chat"
    ollama_tags_path: str = "/api/tags"
    ollama_model: str = "qwen3:4b-q4_K_M"
    # Optional Bearer credential when the LAN Ollama host sits behind an auth proxy.
    ollama_api_key: str = ""
    # Separate TCP connect budget so an offline LAN PC raises a clear alert quickly,
    # while read/generation waits long enough for local model loading and inference.
    ollama_connect_timeout_seconds: int = 5
    ollama_timeout_seconds: int = 90
    ollama_temperature: float = 0.1
    ollama_top_p: float = 0.9
    ollama_repeat_penalty: float = 1.08
    ollama_num_ctx: int = 8192
    ollama_max_tokens: int = 1200
    # Qwen3 reasoning-trace toggle. False asks Ollama to skip long internal thinking
    # blocks so compact models such as qwen3:4b-q4_K_M respond promptly on LAN hardware.
    ollama_think: bool = False
    ollama_keep_alive: str = "15m"
    # Optional PEM CA bundle path when OLLAMA_BASE_URL uses https:// with a private CA.
    ollama_ca_cert: str = ""
    # Read-only, per-workspace indexes built from approved PDFs by the operator.
    ai_knowledge_directory: str = ""
    # Optional unattended seeding for a first boot with no terminal. Leave blank to be asked.
    seed_org_slug: str = ""
    seed_org_name: str = ""
    seed_owner_name: str = ""
    seed_admin_email: str = ""
    seed_admin_password: str = ""

    # ------------------------------------------------------------------ helpers
    @field_validator("allowed_hosts")
    @classmethod
    def validate_allowed_hosts(cls, value: str) -> str:
        """Store exact hostnames only; never ports, schemes, paths or wildcards."""
        hosts: list[str] = []
        for item in value.split(","):
            host = item.strip().lower().rstrip(".")
            if not host:
                continue
            valid_hostname = re.fullmatch(
                r"(?=.{1,253}$)[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?",
                host,
            )
            if not valid_hostname or ".." in host or any(
                label.startswith("-") or label.endswith("-") for label in host.split(".")
            ):
                raise ValueError(
                    f"ALLOWED_HOSTS entry {item!r} is invalid; use an exact hostname without scheme, port or wildcard"
                )
            if host not in hosts:
                hosts.append(host)
        return ",".join(hosts)

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
    def allowed_host_list(self) -> list[str]:
        return [host for host in self.allowed_hosts.split(",") if host]

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

    @property
    def ollama_endpoint_label(self) -> str:
        """Safe ``scheme://host[:port][/prefix]`` display label with zero credentials."""
        parts = urlsplit((self.ollama_base_url or "").strip())
        if not parts.scheme or not parts.hostname:
            return ""
        scheme = parts.scheme.lower()
        host = parts.hostname.lower()
        if ":" in host:
            host = f"[{host}]"
        try:
            port = parts.port
        except ValueError:
            port = None
        netloc = f"{host}:{port}" if port is not None else host
        prefix = (parts.path or "").rstrip("/")
        return f"{scheme}://{netloc}{prefix}"

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
        if not 5 <= self.entry_check_history_sheets <= 120:
            raise ValueError("ENTRY_CHECK_HISTORY_SHEETS must be between 5 and 120")
        if not 30 <= self.entry_check_profile_window_days <= 3650:
            raise ValueError("ENTRY_CHECK_PROFILE_WINDOW_DAYS must be between 30 and 3650")
        if not 1 <= self.entry_check_profile_max_age_hours <= 720:
            raise ValueError("ENTRY_CHECK_PROFILE_MAX_AGE_HOURS must be between 1 and 720")

        base_url = (self.ollama_base_url or "").strip().rstrip("/")
        url_problem = _ollama_url_problem(base_url)
        if url_problem:
            raise ValueError(f"OLLAMA_BASE_URL {self.ollama_base_url!r} is invalid: {url_problem}")
        api_path = (self.ollama_api_path or "").strip() or "/api/chat"
        if len(api_path) > 1:
            api_path = api_path.rstrip("/")
        path_problem = _ollama_path_problem(api_path, "OLLAMA_API_PATH")
        if path_problem:
            raise ValueError(path_problem)
        # Gracefully accept a full endpoint URL pasted into OLLAMA_BASE_URL (e.g.
        # http://192.168.1.50:11434/api/chat) without duplicating the route suffix.
        parsed_base = urlsplit(base_url)
        base_path = (parsed_base.path or "").rstrip("/")
        for suffix in OLLAMA_KNOWN_ENDPOINT_SUFFIXES:
            if base_path.lower().endswith(suffix):
                trimmed_prefix = base_path[: -len(suffix)]
                host = parsed_base.hostname.lower() if parsed_base.hostname else ""
                if ":" in host:
                    host = f"[{host}]"
                netloc = f"{host}:{parsed_base.port}" if parsed_base.port is not None else host
                base_url = f"{parsed_base.scheme.lower()}://{netloc}{trimmed_prefix}"
                if api_path == "/api/chat":
                    api_path = suffix
                break
        tags_path = (self.ollama_tags_path or "").strip() or "/api/tags"
        if len(tags_path) > 1:
            tags_path = tags_path.rstrip("/")
        tags_problem = _ollama_path_problem(tags_path, "OLLAMA_TAGS_PATH")
        if tags_problem:
            raise ValueError(tags_problem)
        model_name = re.sub(r"\s*:\s*", ":", (self.ollama_model or "").strip())
        if not _OLLAMA_MODEL_RE.fullmatch(model_name):
            raise ValueError(
                f"OLLAMA_MODEL {self.ollama_model!r} is invalid; specify a model tag such as 'qwen3:4b-q4_K_M'"
            )
        keep_alive = (self.ollama_keep_alive or "").strip()
        if keep_alive and not _OLLAMA_KEEP_ALIVE_RE.fullmatch(keep_alive):
            raise ValueError("OLLAMA_KEEP_ALIVE must be a duration such as '15m', '1h', '300s' or '0'")
        if not 1 <= self.ollama_connect_timeout_seconds <= 60:
            raise ValueError("OLLAMA_CONNECT_TIMEOUT_SECONDS must be between 1 and 60")
        if not 5 <= self.ollama_timeout_seconds <= 300:
            raise ValueError("OLLAMA_TIMEOUT_SECONDS must be between 5 and 300")
        if self.ollama_connect_timeout_seconds > self.ollama_timeout_seconds:
            raise ValueError("OLLAMA_CONNECT_TIMEOUT_SECONDS must not exceed OLLAMA_TIMEOUT_SECONDS")
        if not 0.0 <= self.ollama_temperature <= 1.0:
            raise ValueError("OLLAMA_TEMPERATURE must be between 0.0 and 1.0")
        if not 1024 <= self.ollama_num_ctx <= 65536:
            raise ValueError("OLLAMA_NUM_CTX must be between 1024 and 65536")
        if not 128 <= self.ollama_max_tokens <= 8192:
            raise ValueError("OLLAMA_MAX_TOKENS must be between 128 and 8192")
        self.ollama_base_url = base_url
        self.ollama_api_path = api_path
        self.ollama_tags_path = tags_path
        self.ollama_model = model_name
        self.ollama_keep_alive = keep_alive
        self.ollama_api_key = (self.ollama_api_key or "").strip()
        self.ollama_ca_cert = (self.ollama_ca_cert or "").strip()

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

        if self.environment in {"staging", "production"} and self.database_url.startswith("postgresql"):
            sslmodes = parse_qs(urlsplit(self.database_url).query, keep_blank_values=True).get("sslmode", [])
            if len(sslmodes) != 1 or sslmodes[0] not in {"require", "verify-ca", "verify-full"}:
                raise ValueError(
                    "DATABASE_URL must contain exactly one secure sslmode=require, verify-ca or verify-full "
                    "outside development/test"
                )
        return self

    # ------------------------------------------------------------------ masking
    _SECRET_FIELDS = ("secret_key", "seed_admin_password", "database_url", "seed_admin_email", "ollama_api_key")

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
