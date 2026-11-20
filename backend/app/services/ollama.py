"""Resilient HTTP client for an offline Ollama server on the local network.

The client speaks only to the single endpoint configured in ``.env``
(``OLLAMA_BASE_URL`` + ``OLLAMA_API_PATH`` / ``OLLAMA_TAGS_PATH``), enforces
separate TCP connect and inference timeouts, caps response sizes, never follows
redirects, never logs credentials, and translates every network, firewall, TLS,
authentication, timeout, or missing-model failure into a clear user-facing
:class:`OllamaCommunicationError`.
"""

from dataclasses import dataclass
import errno
import http.client
import json
import logging
from pathlib import Path
import re
import socket
import ssl
import time
from typing import Any
from urllib.parse import urlsplit

from app.core.config import Settings, get_settings
from app.schemas.ai import AiConnectionStatus, AiErrorCode

log = logging.getLogger("app.ollama")

MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_OUTPUT_CHARS = 16_000
MAX_LISTED_MODELS = 12

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)
_UNCLOSED_THINK_RE = re.compile(r"<think>.*\Z", re.IGNORECASE | re.DOTALL)
_CODE_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.IGNORECASE | re.DOTALL)


class OllamaCommunicationError(RuntimeError):
    """Raised whenever WellSenseIQ cannot obtain a valid reply from Ollama."""

    def __init__(
        self,
        message: str,
        *,
        code: AiErrorCode,
        endpoint: str,
        model: str,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code: AiErrorCode = code
        self.endpoint = endpoint
        self.model = model
        self.status_code = status_code


@dataclass(frozen=True)
class OllamaReply:
    """Sanitized model reply plus diagnostic timing."""

    content: str
    model: str
    endpoint: str
    duration_ms: int


@dataclass(frozen=True)
class _Target:
    scheme: str
    host: str
    port: int
    base_path: str
    label: str


def _clean_text(value: str, *, limit: int = MAX_OUTPUT_CHARS) -> str:
    return _CONTROL_RE.sub("", value or "").strip()[:limit]


def strip_thinking(value: str) -> tuple[str, bool]:
    """Remove Qwen3 ``<think>...</think>`` traces; report whether any existed."""
    raw = value or ""
    had_think = "<think>" in raw.lower()
    without_closed = _THINK_BLOCK_RE.sub("", raw)
    without_any = _UNCLOSED_THINK_RE.sub("", without_closed)
    return _clean_text(without_any), had_think


def _resolve_target(cfg: Settings) -> _Target:
    raw = (cfg.ollama_base_url or "").strip()
    parts = urlsplit(raw)
    scheme = parts.scheme.lower()
    host = parts.hostname or ""
    if scheme not in {"http", "https"} or not host:
        raise OllamaCommunicationError(
            "AI communication error: OLLAMA_BASE_URL in .env is invalid. "
            "Set it to the Ollama machine's URL (for example http://192.168.1.50:11434).",
            code="misconfigured",
            endpoint=cfg.ollama_endpoint_label or raw,
            model=cfg.ollama_model,
        )
    try:
        port = parts.port or (443 if scheme == "https" else 80)
    except ValueError as exc:
        raise OllamaCommunicationError(
            "AI communication error: OLLAMA_BASE_URL in .env has an invalid port number.",
            code="misconfigured",
            endpoint=cfg.ollama_endpoint_label or raw,
            model=cfg.ollama_model,
        ) from exc
    base_path = (parts.path or "").rstrip("/")
    display_host = f"[{host}]" if ":" in host else host
    label = f"{scheme}://{display_host}:{port}{base_path}"
    return _Target(scheme=scheme, host=host, port=port, base_path=base_path, label=label)


def _join_path(base_path: str, route_path: str) -> str:
    suffix = route_path if route_path.startswith("/") else f"/{route_path}"
    if not base_path:
        return suffix
    if base_path.lower().endswith(suffix.lower()):
        return base_path
    return f"{base_path}{suffix}"


def _tls_context(cfg: Settings, target: _Target) -> ssl.SSLContext:
    ca_path = (cfg.ollama_ca_cert or "").strip()
    if ca_path:
        path = Path(ca_path)
        if not path.is_file():
            raise OllamaCommunicationError(
                f"AI communication error: OLLAMA_CA_CERT file '{path.name}' was not found on the server.",
                code="misconfigured",
                endpoint=target.label,
                model=cfg.ollama_model,
            )
        try:
            ctx = ssl.create_default_context(cafile=str(path))
        except ssl.SSLError as exc:
            raise OllamaCommunicationError(
                f"AI communication error: could not load OLLAMA_CA_CERT for {target.label}. Verify it is a valid PEM certificate bundle.",
                code="tls_error",
                endpoint=target.label,
                model=cfg.ollama_model,
            ) from exc
    else:
        ctx = ssl.create_default_context()
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return ctx


def _extract_remote_error(raw: bytes) -> str:
    if not raw:
        return ""
    text = raw.decode("utf-8", errors="replace").strip()
    try:
        parsed = json.loads(text)
    except ValueError:
        return _clean_text(text, limit=220)
    if isinstance(parsed, dict):
        err = parsed.get("error")
        if isinstance(err, str):
            return _clean_text(err, limit=240)
        if isinstance(err, dict) and isinstance(err.get("message"), str):
            return _clean_text(err["message"], limit=240)
        if isinstance(parsed.get("detail"), str):
            return _clean_text(parsed["detail"], limit=240)
    return ""


def _network_error(
    exc: BaseException,
    *,
    target: _Target,
    model: str,
    phase: str,
    timeout_seconds: int,
) -> OllamaCommunicationError:
    if isinstance(exc, ssl.SSLError):
        return OllamaCommunicationError(
            f"AI communication error: TLS handshake with {target.label} failed. "
            "Confirm whether Ollama on the remote PC uses http:// instead of https://, or configure OLLAMA_CA_CERT in .env.",
            code="tls_error",
            endpoint=target.label,
            model=model,
        )
    if isinstance(exc, socket.gaierror):
        return OllamaCommunicationError(
            f"AI communication error: could not resolve host '{target.host}' from OLLAMA_BASE_URL. "
            "Check the hostname or enter the Ollama PC's LAN IP address in .env (for example http://192.168.1.50:11434).",
            code="dns_error",
            endpoint=target.label,
            model=model,
        )
    if isinstance(exc, ConnectionRefusedError):
        return OllamaCommunicationError(
            f"AI communication error: connection to {target.label} was refused. "
            f"Verify Ollama is running on that machine, bound to the LAN (OLLAMA_HOST=0.0.0.0:{target.port}), "
            "and check OLLAMA_BASE_URL in .env.",
            code="connection_refused",
            endpoint=target.label,
            model=model,
        )
    if isinstance(exc, (TimeoutError, socket.timeout)):
        if phase == "connect":
            return OllamaCommunicationError(
                f"AI communication error: could not reach the Ollama machine at {target.label} within {timeout_seconds}s. "
                f"Check that both PCs are on the same LAN, the IP in OLLAMA_BASE_URL (.env) is active, "
                f"and the remote firewall permits inbound TCP port {target.port}.",
                code="timeout",
                endpoint=target.label,
                model=model,
            )
        return OllamaCommunicationError(
            f"AI communication error: model '{model}' at {target.label} timed out after {timeout_seconds}s while responding. "
            "The remote PC may still be loading the model or under heavy load — retry shortly or increase OLLAMA_TIMEOUT_SECONDS in .env.",
            code="timeout",
            endpoint=target.label,
            model=model,
        )
    if isinstance(exc, OSError):
        err_no = getattr(exc, "errno", None)
        if err_no == errno.ECONNREFUSED:
            return OllamaCommunicationError(
                f"AI communication error: connection to {target.label} was refused. "
                f"Verify Ollama is running on that machine with OLLAMA_HOST=0.0.0.0:{target.port} and check OLLAMA_BASE_URL in .env.",
                code="connection_refused",
                endpoint=target.label,
                model=model,
            )
        if err_no in {errno.EHOSTUNREACH, errno.ENETUNREACH, errno.EHOSTDOWN, errno.ENETDOWN}:
            return OllamaCommunicationError(
                f"AI communication error: the Ollama machine at {target.label} is unreachable on the network. "
                f"Confirm both PCs share the same LAN, verify OLLAMA_BASE_URL in .env, and allow TCP port {target.port} through the firewall.",
                code="unreachable",
                endpoint=target.label,
                model=model,
            )
        return OllamaCommunicationError(
            f"AI communication error: network connection to {target.label} failed or was interrupted. "
            f"Verify the Ollama service on {target.host}:{target.port} is online and reachable across your LAN.",
            code="unreachable",
            endpoint=target.label,
            model=model,
        )
    return OllamaCommunicationError(
        f"AI communication error: received an invalid HTTP response from {target.label}. "
        "Confirm OLLAMA_BASE_URL points to a running Ollama server.",
        code="invalid_response",
        endpoint=target.label,
        model=model,
    )


def _request_json(
    cfg: Settings,
    *,
    method: str,
    route_path: str,
    payload: dict[str, Any] | None = None,
    read_timeout: int | None = None,
) -> tuple[int, bytes, int, _Target, str]:
    """Execute one bounded HTTP(S) call to the configured Ollama host."""
    target = _resolve_target(cfg)
    full_path = _join_path(target.base_path, route_path)
    connect_timeout = max(1, int(cfg.ollama_connect_timeout_seconds))
    effective_read_timeout = max(1, int(read_timeout if read_timeout is not None else cfg.ollama_timeout_seconds))

    headers: dict[str, str] = {
        "Accept": "application/json",
        "User-Agent": "WellSenseIQ-OllamaClient/1.0",
        "Connection": "close",
    }
    body_bytes: bytes | None = None
    if payload is not None:
        body_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if cfg.ollama_api_key:
        headers["Authorization"] = f"Bearer {cfg.ollama_api_key}"

    conn: http.client.HTTPConnection
    if target.scheme == "https":
        conn = http.client.HTTPSConnection(
            target.host,
            target.port,
            timeout=connect_timeout,
            context=_tls_context(cfg, target),
        )
    else:
        conn = http.client.HTTPConnection(target.host, target.port, timeout=connect_timeout)

    started = time.monotonic()
    phase = "connect"
    try:
        conn.connect()
        phase = "read"
        if conn.sock is not None:
            conn.sock.settimeout(effective_read_timeout)
        conn.request(method, full_path, body=body_bytes, headers=headers)
        response = conn.getresponse()
        status = int(response.status)
        raw = response.read(MAX_RESPONSE_BYTES + 1)
    except OllamaCommunicationError:
        raise
    except (
        ssl.SSLError,
        socket.gaierror,
        ConnectionRefusedError,
        TimeoutError,
        socket.timeout,
        OSError,
        http.client.HTTPException,
    ) as exc:
        budget = connect_timeout if phase == "connect" else effective_read_timeout
        err = _network_error(exc, target=target, model=cfg.ollama_model, phase=phase, timeout_seconds=budget)
        log.warning("Ollama %s %s%s failed (%s): %s", method, target.label, route_path, err.code, type(exc).__name__)
        raise err from exc
    finally:
        conn.close()

    elapsed_ms = max(0, int((time.monotonic() - started) * 1000))
    if len(raw) > MAX_RESPONSE_BYTES:
        raise OllamaCommunicationError(
            f"AI communication error: response from {target.label} exceeded the 2 MB safety limit.",
            code="invalid_response",
            endpoint=target.label,
            model=cfg.ollama_model,
            status_code=status,
        )
    return status, raw, elapsed_ms, target, full_path


def _raise_for_status(
    status: int,
    raw: bytes,
    *,
    target: _Target,
    full_path: str,
    model: str,
) -> None:
    if 200 <= status < 300:
        return
    remote_detail = _extract_remote_error(raw)
    if 300 <= status < 400:
        raise OllamaCommunicationError(
            f"AI communication error: {target.label}{full_path} returned an unexpected redirect (HTTP {status}). "
            "Point OLLAMA_BASE_URL directly at the Ollama service.",
            code="bad_endpoint",
            endpoint=target.label,
            model=model,
            status_code=status,
        )
    if status in {401, 403}:
        raise OllamaCommunicationError(
            f"AI communication error: the Ollama server at {target.label} rejected authentication (HTTP {status}). "
            "Verify OLLAMA_API_KEY in .env.",
            code="auth_error",
            endpoint=target.label,
            model=model,
            status_code=status,
        )
    if status == 404:
        lower = remote_detail.lower()
        if "model" in lower and ("not found" in lower or "pull" in lower or "exist" in lower):
            raise OllamaCommunicationError(
                f"AI communication error: connected to Ollama at {target.label}, but model '{model}' is not installed on that machine. "
                f"Run 'ollama pull {model}' on the Ollama PC or update OLLAMA_MODEL in .env.",
                code="model_missing",
                endpoint=target.label,
                model=model,
                status_code=status,
            )
        raise OllamaCommunicationError(
            f"AI communication error: connected to {target.label}, but endpoint '{full_path}' returned HTTP 404. "
            "Verify OLLAMA_BASE_URL and OLLAMA_API_PATH in .env (default /api/chat).",
            code="bad_endpoint",
            endpoint=target.label,
            model=model,
            status_code=status,
        )
    if status == 405:
        raise OllamaCommunicationError(
            f"AI communication error: endpoint '{full_path}' on {target.label} rejected the HTTP method (405). "
            "Verify OLLAMA_API_PATH in .env (default /api/chat).",
            code="bad_endpoint",
            endpoint=target.label,
            model=model,
            status_code=status,
        )
    suffix = f" ({remote_detail})" if remote_detail else ""
    raise OllamaCommunicationError(
        f"AI communication error: the Ollama server at {target.label} returned HTTP {status}{suffix}. "
        "Check Ollama logs and available memory on the remote PC.",
        code="server_error",
        endpoint=target.label,
        model=model,
        status_code=status,
    )


def _decode_json(raw: bytes, *, target: _Target, model: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise OllamaCommunicationError(
            f"AI communication error: received a non-JSON response from {target.label}. "
            "Verify OLLAMA_BASE_URL and OLLAMA_API_PATH point to an Ollama API endpoint.",
            code="invalid_response",
            endpoint=target.label,
            model=model,
        ) from exc
    if not isinstance(parsed, dict):
        raise OllamaCommunicationError(
            f"AI communication error: received an unexpected payload shape from {target.label}.",
            code="invalid_response",
            endpoint=target.label,
            model=model,
        )
    return parsed


def _model_matches(configured: str, installed: list[str]) -> bool:
    wanted = configured.strip().lower()
    available = {name.strip().lower() for name in installed if name.strip()}
    if wanted in available:
        return True
    if ":" not in wanted and f"{wanted}:latest" in available:
        return True
    return False


def _parse_model_names(payload: dict[str, Any]) -> list[str]:
    names: list[str] = []
    models = payload.get("models")
    if isinstance(models, list):
        for entry in models:
            if isinstance(entry, dict):
                raw_name = entry.get("name") or entry.get("model") or ""
                if isinstance(raw_name, str):
                    cleaned = _clean_text(raw_name, limit=120)
                    if cleaned and cleaned not in names:
                        names.append(cleaned)
    data = payload.get("data")
    if isinstance(data, list):
        for entry in data:
            if isinstance(entry, dict) and isinstance(entry.get("id"), str):
                cleaned = _clean_text(entry["id"], limit=120)
                if cleaned and cleaned not in names:
                    names.append(cleaned)
    return names


def ensure_enabled(settings: Settings | None = None) -> Settings:
    cfg = settings or get_settings()
    if not cfg.ollama_enabled:
        raise OllamaCommunicationError(
            "Offline AI model is not enabled in server configuration. "
            "Set OLLAMA_ENABLED=true and OLLAMA_BASE_URL=http://<ollama-pc-ip>:11434 in .env, then restart the API.",
            code="disabled",
            endpoint=cfg.ollama_endpoint_label,
            model=cfg.ollama_model,
        )
    return cfg


def check_status(*, probe: bool = False, settings: Settings | None = None) -> AiConnectionStatus:
    """Return the configured Ollama posture and optionally verify LAN connectivity."""
    cfg = settings or get_settings()
    endpoint = cfg.ollama_endpoint_label
    base = AiConnectionStatus(
        enabled=bool(cfg.ollama_enabled),
        provider="ollama",
        model=cfg.ollama_model,
        endpoint=endpoint,
        api_path=cfg.ollama_api_path,
        timeout_seconds=cfg.ollama_timeout_seconds,
    )
    if not cfg.ollama_enabled:
        base.status = "disabled"
        base.error_code = "disabled"
        base.message = (
            "Offline Ollama AI is disabled. Set OLLAMA_ENABLED=true and OLLAMA_BASE_URL in .env "
            "to connect to the LAN model host."
        )
        return base
    if not probe:
        base.status = "configured"
        base.message = f"Configured for Ollama model '{cfg.ollama_model}' at {endpoint}."
        return base

    probe_read_timeout = min(max(5, cfg.ollama_connect_timeout_seconds * 2), 15)
    try:
        status_code, raw, latency_ms, target, full_path = _request_json(
            cfg,
            method="GET",
            route_path=cfg.ollama_tags_path,
            read_timeout=probe_read_timeout,
        )
        if status_code == 404 and cfg.ollama_tags_path == "/api/tags" and cfg.ollama_api_path.startswith("/v1/"):
            status_code, raw, latency_ms, target, full_path = _request_json(
                cfg,
                method="GET",
                route_path="/v1/models",
                read_timeout=probe_read_timeout,
            )
        _raise_for_status(status_code, raw, target=target, full_path=full_path, model=cfg.ollama_model)
        payload = _decode_json(raw, target=target, model=cfg.ollama_model)
    except OllamaCommunicationError as exc:
        base.probed = True
        base.reachable = exc.code in {"model_missing", "auth_error", "bad_endpoint", "server_error"}
        base.status = "error"
        base.error_code = exc.code
        base.message = exc.message
        return base

    installed = _parse_model_names(payload)
    matched = _model_matches(cfg.ollama_model, installed)
    base.probed = True
    base.reachable = True
    base.latency_ms = latency_ms
    base.installed_models = installed[:MAX_LISTED_MODELS]
    base.model_available = matched
    if not matched:
        family = cfg.ollama_model.split(":", 1)[0].lower()
        similar = [name for name in installed if name.lower().startswith(family)]
        hint = f" Available matching tags on that host: {', '.join(similar[:4])}." if similar else ""
        base.status = "error"
        base.error_code = "model_missing"
        base.message = (
            f"AI communication error: reached Ollama at {target.label} ({latency_ms} ms), "
            f"but model '{cfg.ollama_model}' is not installed on that machine. "
            f"Run 'ollama pull {cfg.ollama_model}' on the Ollama PC or update OLLAMA_MODEL in .env.{hint}"
        )
        return base

    base.status = "ready"
    base.message = f"Connected to Ollama at {target.label} ({latency_ms} ms) · model '{cfg.ollama_model}' ready."
    return base


def _build_payload(
    cfg: Settings,
    *,
    system_prompt: str,
    user_prompt: str,
    json_mode: bool,
    max_tokens: int | None,
    temperature: float | None,
    include_think: bool = True,
    think: bool | None = None,
) -> tuple[str, dict[str, Any]]:
    api_path = cfg.ollama_api_path
    lower_path = api_path.lower()
    temp = cfg.ollama_temperature if temperature is None else max(0.0, min(1.0, float(temperature)))
    tokens = cfg.ollama_max_tokens if max_tokens is None else max(64, min(8192, int(max_tokens)))

    thinking = cfg.ollama_think if think is None else think
    qwen3 = cfg.ollama_model.lower().rsplit("/", 1)[-1].startswith("qwen3")
    if lower_path.endswith("/v1/chat/completions"):
        if qwen3 and not thinking:
            user_prompt += "\n/no_think"
        payload: dict[str, Any] = {
            "model": cfg.ollama_model,
            "stream": False,
            "temperature": temp,
            "max_tokens": tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        return "openai", payload

    options: dict[str, Any] = {
        "temperature": temp,
        "top_p": float(getattr(cfg, "ollama_top_p", 0.9)),
        "repeat_penalty": float(getattr(cfg, "ollama_repeat_penalty", 1.08)),
        "num_ctx": int(cfg.ollama_num_ctx),
        "num_predict": tokens,
    }
    if lower_path.endswith("/api/generate"):
        gen_payload: dict[str, Any] = {
            "model": cfg.ollama_model,
            "system": system_prompt,
            "prompt": user_prompt,
            "stream": False,
            "options": options,
        }
        if include_think:
            gen_payload["think"] = thinking
        if cfg.ollama_keep_alive:
            gen_payload["keep_alive"] = cfg.ollama_keep_alive
        if json_mode:
            gen_payload["format"] = "json"
        return "generate", gen_payload

    chat_payload: dict[str, Any] = {
        "model": cfg.ollama_model,
        "stream": False,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "options": options,
    }
    if include_think:
        chat_payload["think"] = thinking
    if cfg.ollama_keep_alive:
        chat_payload["keep_alive"] = cfg.ollama_keep_alive
    if json_mode:
        chat_payload["format"] = "json"
    return "chat", chat_payload


def _extract_reply_text(protocol: str, payload: dict[str, Any]) -> tuple[str, str]:
    remote_model = ""
    if isinstance(payload.get("model"), str):
        remote_model = _clean_text(payload["model"], limit=120)
    if protocol == "openai":
        choices = payload.get("choices")
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            msg = choices[0].get("message")
            if isinstance(msg, dict) and isinstance(msg.get("content"), str):
                return msg["content"], remote_model
        return "", remote_model
    if protocol == "generate":
        resp = payload.get("response")
        return (resp if isinstance(resp, str) else ""), remote_model
    msg = payload.get("message")
    if isinstance(msg, dict):
        content = msg.get("content")
        if isinstance(content, str):
            return content, remote_model
    if isinstance(payload.get("response"), str):
        return payload["response"], remote_model
    return "", remote_model


def chat(
    *,
    system_prompt: str,
    user_prompt: str,
    json_mode: bool = False,
    max_tokens: int | None = None,
    temperature: float | None = None,
    settings: Settings | None = None,
    think: bool | None = None,
) -> OllamaReply:
    """Send a single-turn grounded request to the configured LAN Ollama model."""
    cfg = ensure_enabled(settings)
    protocol, payload = _build_payload(
        cfg,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        json_mode=json_mode,
        max_tokens=max_tokens,
        temperature=temperature,
        include_think=True,
        think=think,
    )
    status_code, raw, elapsed_ms, target, full_path = _request_json(
        cfg,
        method="POST",
        route_path=cfg.ollama_api_path,
        payload=payload,
    )
    # Compatibility fallback for older Ollama servers that reject the top-level
    # `think` boolean introduced alongside Qwen3 thinking models: append Qwen3's
    # native `/no_think` control token when thinking is disabled so compact models
    # like qwen3:1.7b spend their full token budget on the grounded answer.
    if status_code == 400 and "think" in payload and "think" in _extract_remote_error(raw).lower():
        thinking = cfg.ollama_think if think is None else think
        is_qwen3 = cfg.ollama_model.lower().rsplit("/", 1)[-1].startswith("qwen3")
        fallback_user = f"{user_prompt}\n/no_think" if not thinking and is_qwen3 else user_prompt
        protocol, fallback_payload = _build_payload(
            cfg,
            system_prompt=system_prompt,
            user_prompt=fallback_user,
            json_mode=json_mode,
            max_tokens=max_tokens,
            temperature=temperature,
            include_think=False,
            think=think,
        )
        status_code, raw, retry_ms, target, full_path = _request_json(
            cfg,
            method="POST",
            route_path=cfg.ollama_api_path,
            payload=fallback_payload,
        )
        elapsed_ms += retry_ms

    _raise_for_status(status_code, raw, target=target, full_path=full_path, model=cfg.ollama_model)
    parsed = _decode_json(raw, target=target, model=cfg.ollama_model)
    if isinstance(parsed.get("error"), str) and parsed["error"].strip():
        err_text = _clean_text(parsed["error"], limit=240)
        code: AiErrorCode = "model_missing" if "not found" in err_text.lower() and "model" in err_text.lower() else "server_error"
        raise OllamaCommunicationError(
            f"AI communication error: Ollama at {target.label} reported an error: {err_text}",
            code=code,
            endpoint=target.label,
            model=cfg.ollama_model,
        )

    raw_text, remote_model = _extract_reply_text(protocol, parsed)
    cleaned, had_think = strip_thinking(raw_text)
    if not cleaned:
        if had_think or (
            isinstance(parsed.get("message"), dict)
            and isinstance(parsed["message"].get("thinking"), str)
            and parsed["message"]["thinking"].strip()
        ):
            raise OllamaCommunicationError(
                f"AI communication error: model '{cfg.ollama_model}' at {target.label} spent its entire token budget on internal reasoning and returned no answer. "
                "Set OLLAMA_THINK=false or increase OLLAMA_MAX_TOKENS in .env.",
                code="invalid_response",
                endpoint=target.label,
                model=cfg.ollama_model,
            )
        raise OllamaCommunicationError(
            f"AI communication error: model '{cfg.ollama_model}' at {target.label} returned an empty response. "
            "Verify the model is healthy on the Ollama PC and retry.",
            code="invalid_response",
            endpoint=target.label,
            model=cfg.ollama_model,
        )

    return OllamaReply(
        content=cleaned,
        model=remote_model or cfg.ollama_model,
        endpoint=target.label,
        duration_ms=elapsed_ms,
    )


def extract_json_object(text: str) -> dict[str, Any] | None:
    """Extract a JSON object from plain JSON, fenced JSON, or wrapped model prose."""
    candidate = (text or "").strip()
    if not candidate:
        return None
    try:
        parsed = json.loads(candidate)
        if isinstance(parsed, dict):
            return parsed
    except ValueError:
        pass

    fenced = _CODE_FENCE_RE.search(candidate)
    if fenced:
        try:
            parsed = json.loads(fenced.group(1))
            if isinstance(parsed, dict):
                return parsed
        except ValueError:
            pass

    start = candidate.find("{")
    while start != -1:
        depth = 0
        in_string = False
        escaped = False
        for idx in range(start, len(candidate)):
            ch = candidate[idx]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    snippet = candidate[start : idx + 1]
                    try:
                        parsed = json.loads(snippet)
                        if isinstance(parsed, dict):
                            return parsed
                    except ValueError:
                        break
        start = candidate.find("{", start + 1)
    return None
