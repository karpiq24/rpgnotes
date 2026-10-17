from __future__ import annotations

import logging
import time
from collections import Counter, defaultdict
from collections.abc import Callable
from typing import Any, TypeVar

from google import genai
from google.genai import types
from pydantic import BaseModel

log = logging.getLogger("rpgnotes")

T = TypeVar("T")
_Schema = TypeVar("_Schema", bound=BaseModel)

_client: genai.Client | None = None
_service_tier = "standard"
# Flex requests may queue for minutes; the SDK timeout is in milliseconds.
_FLEX_TIMEOUT_MS = 15 * 60 * 1000
_FLEX_RETRY_DELAY = 30.0

# Token usage per model for this run: input / cached / output / thinking.
_usage: defaultdict[str, Counter[str]] = defaultdict(Counter)


def configure(api_key: str, service_tier: str = "standard") -> None:
    """Create the shared Gemini client (google-genai SDK).

    `service_tier="flex"` runs every request on the half-price Flex tier and
    falls back to the standard tier when Flex keeps failing (Flex has no
    server-side fallback and returns 503 when at capacity).
    """
    global _client, _service_tier
    _service_tier = service_tier.strip().lower()
    timeout = _FLEX_TIMEOUT_MS if _service_tier == "flex" else None
    _client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=timeout))


def _get_client() -> genai.Client:
    if _client is None:
        raise RuntimeError("Gemini client not configured; call llm.configure(api_key) first.")
    return _client


def call_with_retry(
    fn: Callable[..., T],
    *args: object,
    max_retries: int = 3,
    base_delay: float = 5.0,
    **kwargs: object,
) -> T:
    """Call `fn` with exponential backoff. Raises the last exception on exhaustion."""
    for attempt in range(1, max_retries + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            if attempt == max_retries:
                raise
            delay = base_delay * (2 ** (attempt - 1))
            log.warning(
                "Gemini API error (attempt %d/%d): %s. Retrying in %.0fs…",
                attempt,
                max_retries,
                e,
                delay,
            )
            time.sleep(delay)
    raise RuntimeError("unreachable")


def _record_usage(model: str, tier: str, response: types.GenerateContentResponse) -> None:
    meta = response.usage_metadata
    if meta is None:
        return
    counts = {
        "input": meta.prompt_token_count or 0,
        "cached": meta.cached_content_token_count or 0,
        "output": meta.candidates_token_count or 0,
        "thinking": meta.thoughts_token_count or 0,
    }
    _usage[model].update(counts)
    _usage[model]["calls"] += 1
    log.info(
        "Gemini %s (%s): input %d (cached %d), output %d, thinking %d tokens.",
        model,
        tier,
        counts["input"],
        counts["cached"],
        counts["output"],
        counts["thinking"],
    )


def log_usage_summary() -> None:
    """Log this run's token totals per model (thinking is billed as output)."""
    for model, counts in _usage.items():
        log.info(
            "Gemini usage %s: %d call(s), input %d (cached %d), output %d + thinking %d tokens.",
            model,
            counts["calls"],
            counts["input"],
            counts["cached"],
            counts["output"],
            counts["thinking"],
        )


def _generate(
    model: str,
    contents: Any,
    config: types.GenerateContentConfig,
    parse: Callable[[types.GenerateContentResponse], T],
) -> T:
    """Run one request with retries; on Flex, fall back to standard after repeated failures."""

    def once(tier_config: types.GenerateContentConfig, tier: str) -> T:
        response = _get_client().models.generate_content(
            model=model, contents=contents, config=tier_config
        )
        _record_usage(model, tier, response)
        return parse(response)

    if _service_tier == "flex":
        flex_config = config.model_copy(update={"service_tier": types.ServiceTier.FLEX})
        try:
            return call_with_retry(once, flex_config, "flex", base_delay=_FLEX_RETRY_DELAY)
        except Exception as e:
            log.warning("Flex request failed (%s). Retrying on the standard tier.", e)
    return call_with_retry(once, config, "standard")


def _config(
    system_instruction: str,
    temperature: float | None,
    thinking_level: str | None,
    **extra: Any,
) -> types.GenerateContentConfig:
    """`None` keeps the model default for temperature and thinking.

    Google recommends leaving Gemini 3+ models at their default temperature;
    lower values can cause looping or degraded reasoning.
    """
    return types.GenerateContentConfig(
        system_instruction=system_instruction or None,
        temperature=temperature,
        thinking_config=(
            types.ThinkingConfig(thinking_level=thinking_level)  # type: ignore[arg-type]
            if thinking_level
            else None
        ),
        **extra,
    )


def image_part(data: bytes, mime_type: str) -> types.Part:
    return types.Part.from_bytes(data=data, mime_type=mime_type)


def generate_text(
    *,
    model: str,
    contents: Any,
    system_instruction: str = "",
    temperature: float | None = None,
    thinking_level: str | None = None,
) -> str:
    """One text completion, retried on API errors and empty responses."""

    def parse(response: types.GenerateContentResponse) -> str:
        text = response.text
        if not text or not text.strip():
            raise RuntimeError("Gemini returned an empty response.")
        return text

    return _generate(
        model, contents, _config(system_instruction, temperature, thinking_level), parse
    )


def generate_structured(
    *,
    model: str,
    contents: Any,
    schema: type[_Schema],
    system_instruction: str = "",
    temperature: float | None = None,
    thinking_level: str | None = None,
) -> _Schema:
    """JSON output constrained to `schema`; a reply that fails validation is retried."""
    config = _config(
        system_instruction,
        temperature,
        thinking_level,
        response_mime_type="application/json",
        response_json_schema=schema.model_json_schema(),
    )

    def parse(response: types.GenerateContentResponse) -> _Schema:
        return schema.model_validate_json(response.text or "")

    return _generate(model, contents, config, parse)
