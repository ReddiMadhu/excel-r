"""
Central LLM construction: Azure OpenAI (via ChatOpenAI) and Google Gen AI,
with optional failover (RunnableWithFallbacks / with_fallbacks).

Environment:
  LLM_PROVIDER_ORDER   Comma-separated: azure, google (default: azure,google)
  LLM_FAILOVER         true/false — use next provider on failure (default: true)
  OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL  — Azure or OpenAI-compatible
  GOOGLE_API_KEY or GEMINI_API_KEY, GEMINI_MODEL — Google Gen AI
"""
from __future__ import annotations

import logging
import os
from typing import Any, List, Literal, Optional, Tuple

logger = logging.getLogger(__name__)

ProviderName = Literal["azure", "google"]

_CACHE: dict[Tuple[float, bool], Optional[Any]] = {}


def _truthy(name: str, default: bool = True) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _provider_order() -> List[ProviderName]:
    raw = os.getenv("LLM_PROVIDER_ORDER", "azure,google")
    out: List[ProviderName] = []
    for part in raw.lower().split(","):
        p = part.strip()
        if p == "azure" or p == "google":
            out.append(p)  # type: ignore[arg-type]
    return out or ["azure", "google"]


def _google_api_key() -> str:
    return (os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY") or "").strip()


def _azure_configured() -> bool:
    return bool(os.getenv("OPENAI_API_KEY", "").strip())


def _google_configured() -> bool:
    return bool(_google_api_key())


def _build_azure_chat(*, temperature: float, json_mode: bool) -> Optional[Any]:
    if not _azure_configured():
        return None
    from langchain_openai import ChatOpenAI

    kwargs: dict[str, Any] = {
        "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip(),
        "api_key": os.getenv("OPENAI_API_KEY", "").strip(),
        "temperature": temperature,
    }
    base_url = os.getenv("OPENAI_BASE_URL")
    if base_url and base_url.strip():
        kwargs["base_url"] = base_url.strip()
    if json_mode:
        kwargs["model_kwargs"] = {"response_format": {"type": "json_object"}}
    return ChatOpenAI(**kwargs)


def _build_google_chat(*, temperature: float, json_mode: bool) -> Optional[Any]:
    if not _google_configured():
        return None
    from langchain_google_genai import ChatGoogleGenerativeAI

    model = os.getenv("GEMINI_MODEL", "gemini-1.5-flash").strip()
    kwargs: dict[str, Any] = {
        "model": model,
        "google_api_key": _google_api_key(),
        "temperature": temperature,
    }
    if json_mode:
        kwargs["response_mime_type"] = "application/json"
    return ChatGoogleGenerativeAI(**kwargs)


def _build_named_model(
    name: ProviderName, *, temperature: float, json_mode: bool
) -> Optional[Tuple[str, Any]]:
    if name == "azure":
        m = _build_azure_chat(temperature=temperature, json_mode=json_mode)
        return ("azure", m) if m else None
    m = _build_google_chat(temperature=temperature, json_mode=json_mode)
    return ("google", m) if m else None


def _assemble_stack(
    models: List[Tuple[str, Any]], *, failover: bool
) -> Any:
    if not models:
        return None
    if len(models) == 1:
        return models[0][1]

    runnables = [m for _, m in models]
    labels = [lbl for lbl, _ in models]
    primary = runnables[0]
    rest = runnables[1:]

    if failover and rest:
        try:
            chain = primary.with_fallbacks(rest)
        except AttributeError:
            from langchain_core.runnables import RunnableWithFallbacks

            chain = RunnableWithFallbacks(runnable=primary, fallbacks=rest)
        logger.info(
            "LLM failover stack: primary=%s, fallbacks=%s",
            labels[0],
            ",".join(labels[1:]),
        )
        return chain

    logger.info("LLM failover disabled — using primary only: %s", labels[0])
    return primary


def get_resilient_llm(*, temperature: float, json_mode: bool = True) -> Optional[Any]:
    """
    Return a LangChain chat runnable (BaseChatModel or runnable with_fallbacks).

    Picks providers in LLM_PROVIDER_ORDER; only includes those with credentials.
    If multiple remain and LLM_FAILOVER is true, chains with_fallbacks.
    """
    key = (round(float(temperature), 6), json_mode)
    if key in _CACHE:
        return _CACHE[key]

    order = _provider_order()
    failover = _truthy("LLM_FAILOVER", True)
    built: List[Tuple[str, Any]] = []
    for name in order:
        pair = _build_named_model(name, temperature=temperature, json_mode=json_mode)
        if pair:
            built.append(pair)

    if not built:
        logger.warning(
            "No LLM provider configured (need OPENAI_API_KEY and/or GOOGLE_API_KEY|GEMINI_API_KEY)."
        )
        _CACHE[key] = None
        return None

    if len(built) == 1:
        logger.info("LLM using single provider: %s", built[0][0])
    stack = _assemble_stack(built, failover=failover)
    _CACHE[key] = stack
    return stack


def clear_llm_cache() -> None:
    """Test helper: drop cached LLM instances."""
    _CACHE.clear()


def stringify_chat_content(content: Any) -> str:
    """
    Normalize AIMessage.content to a single string.

    OpenAI returns str; Google Gen AI often returns a list of blocks
    (e.g. [{'type': 'text', 'text': '...'}]).
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                t = block.get("text")
                if isinstance(t, str):
                    parts.append(t)
                else:
                    parts.append(str(block))
            else:
                parts.append(str(block))
        return "".join(parts)
    return str(content)
