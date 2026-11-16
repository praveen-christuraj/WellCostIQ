"""Shared contract for the offline LAN Ollama AI service."""

from typing import Literal

from pydantic import BaseModel, Field

AiStatusState = Literal["disabled", "configured", "ready", "error"]
AiErrorCode = Literal[
    "",
    "disabled",
    "misconfigured",
    "dns_error",
    "connection_refused",
    "timeout",
    "tls_error",
    "unreachable",
    "auth_error",
    "model_missing",
    "bad_endpoint",
    "server_error",
    "invalid_response",
]


class AiConnectionStatus(BaseModel):
    """Current configuration and (when probed) reachability of the Ollama host."""

    enabled: bool = False
    provider: str = "ollama"
    model: str = ""
    endpoint: str = ""
    api_path: str = "/api/chat"
    timeout_seconds: int = 90
    status: AiStatusState = "disabled"
    probed: bool = False
    reachable: bool = False
    model_available: bool | None = None
    installed_models: list[str] = Field(default_factory=list)
    latency_ms: int | None = None
    error_code: AiErrorCode = ""
    message: str = ""
