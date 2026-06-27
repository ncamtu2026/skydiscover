"""OpenAI-compatible LLM backend (Chat Completions + Responses API)."""

import asyncio
import base64
import logging
import os
import sys
import tempfile
import time
import uuid as _uuid
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

import openai

from skydiscover.config import LLMModelConfig
from skydiscover.llm.base import LLMInterface, LLMResponse
from skydiscover.llm.responses_utils import (
    convert_messages_to_responses_input,
    extract_responses_output,
)

logger = logging.getLogger("skydiscover.llm")

REASONING_MODEL_PREFIXES = (
    "o1-",
    "o1",
    "o3-",
    "o3",
    "o4-",
    "gpt-5-",
    "gpt-5",
    "gpt-oss-120b",
    "gpt-oss-20b",
)

GOOGLE_AI_STUDIO_DOMAIN = "generativelanguage.googleapis.com"

_OPENAI_API_PREFIXES = (
    "https://api.openai.com",
    "https://eu.api.openai.com",
    "https://apac.api.openai.com",
)


def is_openai_reasoning_model(model_name: str, api_base: str) -> bool:
    """Check if a model is an OpenAI reasoning model requiring special parameters."""
    api_base_lower = (api_base or "").lower()
    is_openai_api = (
        any(api_base_lower.startswith(p) for p in _OPENAI_API_PREFIXES)
        or ".openai.azure.com" in api_base_lower
    )
    return is_openai_api and model_name.lower().startswith(REASONING_MODEL_PREFIXES)


class OpenAILLM(LLMInterface):
    """LLM backend using OpenAI-compatible APIs (Chat Completions + Responses)."""

    def __init__(self, model_cfg: Optional[LLMModelConfig] = None):
        self.model = model_cfg.name
        self.temperature = model_cfg.temperature
        self.top_p = model_cfg.top_p
        self.max_tokens = model_cfg.max_tokens
        self.timeout = model_cfg.timeout
        self.retries = model_cfg.retries
        self.retry_delay = model_cfg.retry_delay
        self.api_base = model_cfg.api_base
        self.api_key = model_cfg.api_key
        self.reasoning_effort = getattr(model_cfg, "reasoning_effort", None)
        self.thinking = getattr(model_cfg, "thinking", None)
        self.thinking_budget = getattr(model_cfg, "thinking_budget", None)
        # stream_no_text implies streaming, but with stdout echo suppressed.
        self.stream_no_text = bool(getattr(model_cfg, "stream_no_text", None) or False)
        self.stream = bool(getattr(model_cfg, "stream", None) or False) or self.stream_no_text

        max_retries = self.retries if self.retries is not None else 0
        is_azure = self.api_base and ".openai.azure.com" in self.api_base.lower()

        if is_azure:
            parsed_url = urlparse(self.api_base)
            azure_endpoint = f"{parsed_url.scheme}://{parsed_url.netloc}"
            query_params = parse_qs(parsed_url.query)
            api_version = query_params.get("api-version", ["2024-12-01-preview"])[0]

            self.client = openai.AzureOpenAI(
                azure_endpoint=azure_endpoint,
                api_key=self.api_key,
                api_version=api_version,
                timeout=self.timeout,
                max_retries=max_retries,
            )
        else:
            self.client = openai.OpenAI(
                api_key=self.api_key,
                base_url=self.api_base,
                timeout=self.timeout,
                max_retries=max_retries,
            )

        if not hasattr(logger, "_initialized_models"):
            logger._initialized_models = set()
        if self.model not in logger._initialized_models:
            api_base_str = (self.api_base or "").lower()
            if is_azure:
                provider = "AzureOpenAI"
            elif GOOGLE_AI_STUDIO_DOMAIN in api_base_str:
                provider = "Gemini"
            elif "api.anthropic.com" in api_base_str:
                provider = "Anthropic"
            elif "api.deepseek.com" in api_base_str:
                provider = "DeepSeek"
            elif "api.mistral.ai" in api_base_str:
                provider = "Mistral"
            else:
                provider = "OpenAI"
            logger.info(f"{provider} LLM: {self.model}")
            logger._initialized_models.add(self.model)

    async def generate(
        self, system_message: str, messages: List[Dict[str, Any]], **kwargs
    ) -> LLMResponse:
        """Generate a response. Pass image_output=True for image generation."""
        if kwargs.get("image_output"):
            return await self._generate_with_image(system_message, messages, **kwargs)
        text = await self._generate_text(system_message, messages, **kwargs)
        return LLMResponse(text=text)

    # ------------------------------------------------------------------
    # Text generation (Chat Completions API)
    # ------------------------------------------------------------------

    async def _generate_text(
        self, system_message: str, messages: List[Dict[str, Any]], **kwargs
    ) -> str:
        system_content = system_message if system_message is not None else ""
        formatted_messages = [{"role": "system", "content": system_content}]
        formatted_messages.extend(messages)

        is_reasoning = is_openai_reasoning_model(self.model, self.api_base)

        if is_reasoning:
            params = {
                "model": self.model,
                "messages": formatted_messages,
                "max_completion_tokens": kwargs.get("max_tokens", self.max_tokens),
            }
            reasoning_effort = kwargs.get("reasoning_effort", self.reasoning_effort)
            if reasoning_effort is not None:
                params["reasoning_effort"] = reasoning_effort
            if "verbosity" in kwargs:
                params["verbosity"] = kwargs["verbosity"]
        else:
            params = {
                "model": self.model,
                "messages": formatted_messages,
                "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            }
            temperature = kwargs.get("temperature", self.temperature)
            if temperature is not None:
                params["temperature"] = temperature
            top_p = kwargs.get("top_p", self.top_p)
            if top_p is not None:
                params["top_p"] = top_p
            reasoning_effort = kwargs.get("reasoning_effort", self.reasoning_effort)
            if reasoning_effort is not None:
                params["reasoning_effort"] = reasoning_effort

        # Add response_format if requested (e.g. {"type": "json_object"})
        response_format = kwargs.get("response_format")
        if response_format is not None:
            params["response_format"] = response_format

        # Build extra_body: start from any caller-supplied dict, then layer in
        # thinking-mode control so providers like GLM-4.7 don't burn tokens on reasoning.
        #
        # Two different switches are needed because the same model is reachable
        # through different stacks:
        #   • Zhipu / Anthropic-style cloud APIs read ``thinking: {"type": ...}``.
        #   • Self-hosted GLM/Qwen3 on vLLM or SGLang read the chat-template kwarg
        #     ``chat_template_kwargs: {"enable_thinking": bool}`` — the ``thinking``
        #     block is silently ignored there (which is why ``thinking: false`` had
        #     no effect against the local vLLM server).
        # We send both; each backend uses the one it understands and ignores the rest.
        extra_body: Dict[str, Any] = dict(kwargs.get("extra_body") or {})
        thinking = kwargs.get("thinking", self.thinking)
        if thinking is not None:
            if thinking:
                thinking_body: Dict[str, Any] = {"type": "enabled"}
                thinking_budget = kwargs.get("thinking_budget", self.thinking_budget)
                if thinking_budget:
                    _budget_map = {"low": 4096, "medium": 8000, "high": 16000}
                    budget_val = _budget_map.get(str(thinking_budget).lower(), thinking_budget)
                    thinking_body["budget_tokens"] = budget_val
            else:
                thinking_body = {"type": "disabled"}
            extra_body.setdefault("thinking", thinking_body)
            ctk = dict(extra_body.get("chat_template_kwargs") or {})
            ctk.setdefault("enable_thinking", bool(thinking))
            extra_body["chat_template_kwargs"] = ctk
        if extra_body:
            params["extra_body"] = extra_body

        if kwargs.get("stream", self.stream):
            params["stream"] = True
            params["stream_options"] = {"include_usage": True}

        retries, retry_delay, timeout = self._resolve_retry_options(**kwargs)
        attempt = 0

        while attempt <= retries:
            try:
                return await asyncio.wait_for(self._call_api(params), timeout=timeout)
            except asyncio.TimeoutError:
                if attempt < retries:
                    logger.warning(f"Timeout attempt {attempt + 1}/{retries + 1}, retrying...")
                    attempt += 1
                    await asyncio.sleep(retry_delay)
                else:
                    raise
            except Exception as e:
                downgrade_action = self._maybe_downgrade_response_format(params, e)
                if downgrade_action is not None:
                    logger.warning(
                        f"response_format downgrade applied ({downgrade_action}) after API error: {e}"
                    )
                    continue
                if attempt < retries:
                    logger.warning(f"Error attempt {attempt + 1}/{retries + 1}: {e}, retrying...")
                    attempt += 1
                    await asyncio.sleep(retry_delay)
                else:
                    raise

    def _error_mentions_response_format(self, error: Exception) -> bool:
        error_text_parts = [str(error)]

        body = getattr(error, "body", None)
        if body is not None:
            error_text_parts.append(str(body))

        response = getattr(error, "response", None)
        if response is not None:
            response_text = getattr(response, "text", None)
            if response_text:
                error_text_parts.append(str(response_text))

        error_text = " ".join(error_text_parts).lower()
        return "response_format" in error_text or "response format" in error_text

    def _maybe_downgrade_response_format(
        self, params: Dict[str, Any], error: Exception
    ) -> Optional[str]:
        if not self._error_mentions_response_format(error):
            return None

        response_format = params.get("response_format")
        if not isinstance(response_format, dict):
            return None

        format_type = response_format.get("type")
        if format_type == "json_schema":
            params["response_format"] = {"type": "json_object"}
            return "json_schema->json_object"

        if format_type == "json_object":
            params.pop("response_format", None)
            return "json_object->none"

        return None

    async def _call_api(self, params: Dict[str, Any]) -> str:
        if params.get("stream"):
            return await self._call_api_streaming(params)
        loop = asyncio.get_running_loop()
        try:
            t0 = time.perf_counter()
            response = await loop.run_in_executor(
                None, lambda: self.client.chat.completions.create(**params)
            )
            elapsed = time.perf_counter() - t0
            content = response.choices[0].message.content
            usage = getattr(response, "usage", None)
            if usage:
                out_tokens = usage.completion_tokens or 0
                total_tokens = usage.total_tokens or 0
                tok_per_s = out_tokens / elapsed if elapsed > 0 else 0
                logger.info(
                    f"LLM speed: {elapsed:.2f}s | {out_tokens} out / {total_tokens} total tokens"
                    f" | {tok_per_s:.1f} tok/s | model={params.get('model', self.model)}"
                )
            if logger.isEnabledFor(logging.DEBUG):
                messages = params.get("messages", [])
                logger.debug(f"LLM request:\n{messages}")
                logger.debug(f"LLM response:\n{content}")
            return content
        except (openai.BadRequestError, openai.APIStatusError) as exc:
            # Some Azure deployments only expose the Responses API.
            # Fall back transparently when Chat Completions is unsupported.
            if "unsupported" not in str(exc).lower() and "not found" not in str(exc).lower():
                raise
            logger.info("Chat Completions unsupported; falling back to Responses API")
            return await self._call_api_via_responses(params)

    async def _call_api_streaming(self, params: Dict[str, Any]) -> str:
        """Stream the completion, printing chunks live, and return the full text.

        The blocking SDK stream is drained in a worker thread; each delta is
        echoed to stdout so generation progress is visible in real time.
        """
        loop = asyncio.get_running_loop()
        model = params.get("model", self.model)
        # When stream_no_text is set we still drain the stream (to keep long
        # generations alive and collect usage stats) but echo nothing to stdout.
        echo = not self.stream_no_text

        def _reasoning_of(delta) -> Optional[str]:
            # Thinking providers (GLM-4.7, DeepSeek-R1, ...) stream the chain of
            # thought in a non-standard field.  The OpenAI SDK parks unknown
            # fields in ``model_extra`` rather than as plain attributes, so check
            # both before giving up — otherwise the reasoning phase looks frozen.
            for attr in ("reasoning_content", "reasoning"):
                val = getattr(delta, attr, None)
                if isinstance(val, str) and val:
                    return val
            extra = getattr(delta, "model_extra", None) or {}
            for key, val in extra.items():
                if "reasoning" in key and isinstance(val, str) and val:
                    return val
            return None

        def _drain() -> tuple:
            parts: List[str] = []
            usage = None
            in_reasoning = False
            n_chunks = 0
            label = f"[stream {model}]"
            t0 = time.perf_counter()
            if echo:
                sys.stdout.write(f"\n--- streaming [{model}] ---\n")
                sys.stdout.flush()
            for chunk in self.client.chat.completions.create(**params):
                if getattr(chunk, "usage", None):
                    usage = chunk.usage
                choices = getattr(chunk, "choices", None)
                if not choices:
                    continue
                delta = choices[0].delta
                reasoning = _reasoning_of(delta)
                if reasoning:
                    n_chunks += 1
                    if echo:
                        if not in_reasoning:
                            sys.stdout.write("\n<reasoning>\n")
                            in_reasoning = True
                        sys.stdout.write(reasoning)
                        sys.stdout.flush()
                piece = getattr(delta, "content", None)
                if piece:
                    n_chunks += 1
                    if in_reasoning:
                        if echo:
                            sys.stdout.write("\n</reasoning>\n")
                        in_reasoning = False
                    parts.append(piece)
                    if echo:
                        sys.stdout.write(piece)
                        sys.stdout.flush()
                if not echo:
                    sys.stdout.write(f"\r{label} generated {n_chunks} tokens...")
                    sys.stdout.flush()
            if echo:
                if in_reasoning:
                    sys.stdout.write("\n</reasoning>\n")
                sys.stdout.write("\n--- end stream ---\n")
                sys.stdout.flush()
            else:
                sys.stdout.write(f"\r{label} generated {n_chunks} tokens.   \n")
                sys.stdout.flush()
            return "".join(parts), usage, time.perf_counter() - t0

        content, usage, elapsed = await loop.run_in_executor(None, _drain)
        if usage:
            out_tokens = getattr(usage, "completion_tokens", 0) or 0
            total_tokens = getattr(usage, "total_tokens", 0) or 0
            tok_per_s = out_tokens / elapsed if elapsed > 0 else 0
            logger.info(
                f"LLM speed (stream): {elapsed:.2f}s | {out_tokens} out / {total_tokens} total tokens"
                f" | {tok_per_s:.1f} tok/s | model={model}"
            )
        return content

    async def _call_api_via_responses(self, params: Dict[str, Any]) -> str:
        """Translate a Chat-Completions-style *params* dict into a Responses API
        call and return the assistant text."""
        messages = params.get("messages", [])
        input_items = self._convert_to_responses_input(
            [m for m in messages if m.get("role") != "system"]
        )
        system_msg = next((m["content"] for m in messages if m.get("role") == "system"), None)
        resp_params: Dict[str, Any] = {
            "model": params.get("model", self.model),
            "input": input_items,
        }
        if system_msg:
            resp_params["instructions"] = system_msg
        if params.get("max_tokens"):
            resp_params["max_output_tokens"] = params["max_tokens"]
        if params.get("max_completion_tokens"):
            resp_params["max_output_tokens"] = params["max_completion_tokens"]
        if params.get("temperature") is not None:
            resp_params["temperature"] = params["temperature"]
        if params.get("reasoning_effort") is not None:
            resp_params["reasoning"] = {"effort": params["reasoning_effort"]}

        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None, lambda: self.client.responses.create(**resp_params)
        )
        text, _ = self._extract_responses_output(response)
        return text or ""

    def _resolve_retry_options(self, **kwargs) -> Tuple[int, int, int]:
        """Resolve retry/timeout options from kwargs, falling back to instance defaults."""
        retries = kwargs.get("retries", self.retries)
        if retries is None:
            retries = 0
        retry_delay = kwargs.get("retry_delay", self.retry_delay)
        if retry_delay is None:
            retry_delay = 2
        timeout = kwargs.get("timeout", self.timeout)
        if timeout is None:
            timeout = 300
        return retries, retry_delay, timeout

    # ------------------------------------------------------------------
    # Image generation (OpenAI Responses API)
    # ------------------------------------------------------------------

    async def _generate_with_image(
        self,
        system_message: str,
        messages: List[Dict[str, Any]],
        **kwargs,
    ) -> LLMResponse:
        output_dir = kwargs.get("output_dir", tempfile.gettempdir())
        program_id = kwargs.get("program_id", "")

        input_items = convert_messages_to_responses_input(messages)

        params: Dict[str, Any] = {
            "model": self.model,
            "input": input_items,
            "tools": [
                {
                    "type": "image_generation",
                    "quality": kwargs.get("image_quality", "medium"),
                    "size": kwargs.get("image_size", "1024x1024"),
                    "output_format": "png",
                }
            ],
        }
        if system_message:
            params["instructions"] = system_message
        is_reasoning = self.model.lower().startswith(REASONING_MODEL_PREFIXES)
        if not is_reasoning and self.temperature is not None:
            params["temperature"] = kwargs.get("temperature", self.temperature)
        if self.max_tokens is not None:
            params["max_output_tokens"] = kwargs.get("max_tokens", self.max_tokens)

        retries, retry_delay, timeout = self._resolve_retry_options(**kwargs)

        for attempt in range(retries + 1):
            try:
                response = await asyncio.wait_for(self._call_responses_api(params), timeout=timeout)
                text, image_b64, _ = extract_responses_output(response)

                image_path = None
                if image_b64:
                    os.makedirs(output_dir, exist_ok=True)
                    fname = f"{program_id or _uuid.uuid4().hex[:12]}.png"
                    image_path = os.path.join(output_dir, fname)
                    with open(image_path, "wb") as f:
                        f.write(base64.b64decode(image_b64))
                    logger.info(f"Image saved: {image_path}")

                return LLMResponse(text=text, image_path=image_path)

            except asyncio.TimeoutError:
                if attempt < retries:
                    logger.warning(
                        f"Image timeout attempt {attempt + 1}/{retries + 1}, retrying..."
                    )
                    await asyncio.sleep(retry_delay)
                else:
                    raise
            except Exception as e:
                if attempt < retries:
                    logger.warning(
                        f"Image error attempt {attempt + 1}/{retries + 1}: {e}, retrying..."
                    )
                    await asyncio.sleep(retry_delay)
                else:
                    raise

    async def _call_responses_api(self, params: Dict[str, Any]):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: self.client.responses.create(**params))
