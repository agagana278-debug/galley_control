"""Configurable multi-provider LLM client with tool-calling, history, streaming, and graceful error reporting."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable, Iterator, Optional

import httpx

from app.config import settings

logger = logging.getLogger("galley_control.llm")


def _provider_name() -> str:
    return (settings.llm_provider or "gemini").strip().lower()


def _openai_compatible_endpoint(provider: str) -> tuple[str, str]:
    if provider == "groq":
        return "https://api.groq.com/openai/v1/chat/completions", "llama-3.3-70b-versatile"
    if provider == "openrouter":
        return "https://openrouter.ai/api/v1/chat/completions", "openai/gpt-4o-mini"
    return "https://api.openai.com/v1/chat/completions", "gpt-4o-mini"


def generate_llm_text(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 320,
) -> Optional[str]:
    """Single-turn convenience helper returning generated text or None on unconfigured/failure."""
    res = chat_with_tools_and_history(
        system_prompt=system_prompt,
        history=[],
        user_message=user_prompt,
        tools=[],
        tool_executor=None,
        max_tokens=max_tokens,
    )
    return res["text"] if res["ok"] else None


def _run_gemini_tools_loop(
    *,
    api_key: str,
    model: str,
    system_prompt: str,
    history: list[dict[str, str]],
    user_message: str,
    tools: list[dict[str, Any]],
    tool_executor: Callable[[str, dict[str, Any]], dict[str, Any]] | None,
    max_tokens: int,
    timeout: float,
) -> dict[str, Any]:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}
    contents: list[dict[str, Any]] = []
    for turn in history:
        role = "model" if turn["role"] == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": turn["content"]}]})
    contents.append({"role": "user", "parts": [{"text": user_message}]})

    gemini_tools = None
    if tools:
        declarations = []
        for t in tools:
            decl: dict[str, Any] = {
                "name": t["name"],
                "description": t["description"],
            }
            params = t.get("parameters") or {}
            if params.get("properties"):
                decl["parameters"] = params
            declarations.append(decl)
        gemini_tools = [{"functionDeclarations": declarations}]

    tools_used: list[str] = []
    for _step in range(5):
        payload: dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": contents,
            "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.35},
        }
        if gemini_tools:
            payload["tools"] = gemini_tools

        resp = None
        for attempt in range(3):
            try:
                resp = httpx.post(url, headers=headers, json=payload, timeout=timeout)
                if resp.status_code == 503 and attempt < 2:
                    time.sleep(1.0 * (attempt + 1))
                    continue
                resp.raise_for_status()
                break
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 503 and attempt < 2:
                    time.sleep(1.0 * (attempt + 1))
                    continue
                raise

        data = resp.json()
        candidates = data.get("candidates") or []
        if not candidates:
            return {"ok": False, "text": None, "tools_used": tools_used, "error": "Empty model candidates."}

        parts = candidates[0].get("content", {}).get("parts", [])
        fn_calls = [p["functionCall"] for p in parts if "functionCall" in p]
        if fn_calls and tool_executor:
            contents.append({"role": "model", "parts": parts})
            response_parts = []
            for fc in fn_calls:
                fname = fc.get("name", "")
                fargs = fc.get("args") or {}
                tools_used.append(fname)
                result_data = tool_executor(fname, fargs)
                safe_result = json.loads(json.dumps(result_data, default=str))
                response_parts.append(
                    {
                        "functionResponse": {
                            "name": fname,
                            "response": {"result": safe_result},
                        }
                    }
                )
            contents.append({"role": "user", "parts": response_parts})
            continue

        text = "".join(
            p.get("text", "") for p in parts if not p.get("thought")
        ).strip()
        if text:
            return {"ok": True, "text": text, "tools_used": tools_used, "error": None}
        return {"ok": False, "text": None, "tools_used": tools_used, "error": "Model returned no text."}

    return {"ok": False, "text": None, "tools_used": tools_used, "error": "Exceeded maximum tool steps."}


def _run_openai_tools_loop(
    *,
    provider: str,
    api_key: str,
    model: str,
    system_prompt: str,
    history: list[dict[str, str]],
    user_message: str,
    tools: list[dict[str, Any]],
    tool_executor: Callable[[str, dict[str, Any]], dict[str, Any]] | None,
    max_tokens: int,
    timeout: float,
) -> dict[str, Any]:
    url, default_model = _openai_compatible_endpoint(provider)
    resolved_model = model or default_model
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    for turn in history:
        messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": user_message})

    oai_tools = (
        [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["parameters"],
                },
            }
            for t in tools
        ]
        if tools
        else None
    )

    tools_used: list[str] = []
    for _step in range(5):
        payload: dict[str, Any] = {
            "model": resolved_model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.35,
        }
        if oai_tools:
            payload["tools"] = oai_tools
            payload["tool_choice"] = "auto"

        resp = httpx.post(url, headers=headers, json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            return {"ok": False, "text": None, "tools_used": tools_used, "error": "Empty OpenAI choices."}

        msg = choices[0].get("message", {})
        tool_calls = msg.get("tool_calls") or []
        if tool_calls and tool_executor:
            messages.append(msg)
            for tc in tool_calls:
                fn = tc.get("function", {})
                fname = fn.get("name", "")
                raw_args = fn.get("arguments") or "{}"
                try:
                    parsed_args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                except Exception:
                    parsed_args = {}
                tools_used.append(fname)
                result_data = tool_executor(fname, parsed_args)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.get("id", fname),
                        "content": json.dumps(result_data, default=str),
                    }
                )
            continue

        content = (msg.get("content") or "").strip()
        if content:
            return {"ok": True, "text": content, "tools_used": tools_used, "error": None}
        return {"ok": False, "text": None, "tools_used": tools_used, "error": "Empty assistant message."}

    return {"ok": False, "text": None, "tools_used": tools_used, "error": "Exceeded maximum tool steps."}


def _run_anthropic_tools_loop(
    *,
    api_key: str,
    model: str,
    system_prompt: str,
    history: list[dict[str, str]],
    user_message: str,
    tools: list[dict[str, Any]],
    tool_executor: Callable[[str, dict[str, Any]], dict[str, Any]] | None,
    max_tokens: int,
    timeout: float,
) -> dict[str, Any]:
    url = "https://api.anthropic.com/v1/messages"
    resolved_model = model or "claude-3-5-haiku-latest"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    messages: list[dict[str, Any]] = [
        {"role": "assistant" if t["role"] == "assistant" else "user", "content": t["content"]}
        for t in history
    ]
    messages.append({"role": "user", "content": user_message})

    anth_tools = (
        [
            {
                "name": t["name"],
                "description": t["description"],
                "input_schema": t["parameters"],
            }
            for t in tools
        ]
        if tools
        else None
    )

    tools_used: list[str] = []
    for _step in range(5):
        payload: dict[str, Any] = {
            "model": resolved_model,
            "system": system_prompt,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.35,
        }
        if anth_tools:
            payload["tools"] = anth_tools

        resp = httpx.post(url, headers=headers, json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        blocks = data.get("content") or []
        tool_uses = [b for b in blocks if b.get("type") == "tool_use"]
        if tool_uses and tool_executor:
            messages.append({"role": "assistant", "content": blocks})
            tool_results = []
            for tu in tool_uses:
                fname = tu.get("name", "")
                tools_used.append(fname)
                res_data = tool_executor(fname, tu.get("input") or {})
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tu.get("id", ""),
                        "content": json.dumps(res_data, default=str),
                    }
                )
            messages.append({"role": "user", "content": tool_results})
            continue

        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()
        if text:
            return {"ok": True, "text": text, "tools_used": tools_used, "error": None}
        return {"ok": False, "text": None, "tools_used": tools_used, "error": "Empty Anthropic output."}

    return {"ok": False, "text": None, "tools_used": tools_used, "error": "Exceeded maximum tool steps."}


def chat_with_tools_and_history(
    *,
    system_prompt: str,
    history: list[dict[str, str]],
    user_message: str,
    tools: list[dict[str, Any]],
    tool_executor: Callable[[str, dict[str, Any]], dict[str, Any]] | None,
    max_tokens: int = 650,
) -> dict[str, Any]:
    """Run multi-turn + tool-calling completion against the configured LLM provider."""
    api_key = settings.llm_api_key
    provider = _provider_name()
    model = settings.llm_model
    timeout = settings.llm_timeout_seconds

    if not api_key:
        return {
            "ok": False,
            "text": None,
            "provider": provider,
            "model": model,
            "tools_used": [],
            "error": "LLM_API_KEY is not configured on the backend.",
        }

    try:
        if provider in ("", "gemini", "google"):
            resolved_model = model or "gemini-2.5-flash"
            res = _run_gemini_tools_loop(
                api_key=api_key,
                model=resolved_model,
                system_prompt=system_prompt,
                history=history,
                user_message=user_message,
                tools=tools,
                tool_executor=tool_executor,
                max_tokens=max_tokens,
                timeout=timeout,
            )
            return {**res, "provider": "gemini", "model": resolved_model}

        if provider in ("openai", "groq", "openrouter"):
            res = _run_openai_tools_loop(
                provider=provider,
                api_key=api_key,
                model=model,
                system_prompt=system_prompt,
                history=history,
                user_message=user_message,
                tools=tools,
                tool_executor=tool_executor,
                max_tokens=max_tokens,
                timeout=timeout,
            )
            return {**res, "provider": provider, "model": model or "default"}

        if provider == "anthropic":
            resolved_model = model or "claude-3-5-haiku-latest"
            res = _run_anthropic_tools_loop(
                api_key=api_key,
                model=resolved_model,
                system_prompt=system_prompt,
                history=history,
                user_message=user_message,
                tools=tools,
                tool_executor=tool_executor,
                max_tokens=max_tokens,
                timeout=timeout,
            )
            return {**res, "provider": "anthropic", "model": resolved_model}

        return {
            "ok": False,
            "text": None,
            "provider": provider,
            "model": model,
            "tools_used": [],
            "error": f"Unsupported LLM_PROVIDER '{provider}'.",
        }
    except httpx.TimeoutException:
        logger.warning("LLM request timed out (%s/%s).", provider, model)
        return {
            "ok": False,
            "text": None,
            "provider": provider,
            "model": model,
            "tools_used": [],
            "error": f"LLM provider request timed out after {timeout}s.",
        }
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        logger.warning("LLM HTTP error %s from %s.", code, provider)
        if code == 429:
            err_msg = f"{provider} API rate limit or quota exceeded (HTTP 429). Please retry shortly."
        elif code in (401, 403):
            err_msg = f"Invalid or unauthorized {provider} API key (HTTP {code})."
        elif code == 404:
            err_msg = f"Configured model '{model}' was not found on {provider} (HTTP 404)."
        else:
            err_msg = f"LLM provider returned HTTP {code}."
        return {
            "ok": False,
            "text": None,
            "provider": provider,
            "model": model,
            "tools_used": [],
            "error": err_msg,
        }
    except httpx.RequestError as exc:
        logger.warning("LLM transport error (%s): %s", provider, type(exc).__name__)
        return {
            "ok": False,
            "text": None,
            "provider": provider,
            "model": model,
            "tools_used": [],
            "error": f"Network error reaching {provider} ({type(exc).__name__}).",
        }
    except Exception as exc:
        logger.warning("Unexpected LLM client error (%s): %s", provider, type(exc).__name__)
        return {
            "ok": False,
            "text": None,
            "provider": provider,
            "model": model,
            "tools_used": [],
            "error": "AI provider temporarily unavailable.",
        }


def stream_grounded_synthesis(
    *,
    system_prompt: str,
    history: list[dict[str, str]],
    user_message: str,
    grounded_context: dict[str, Any],
    max_tokens: int = 650,
) -> Iterator[str]:
    """Stream tokens via provider SSE when configured & grounded context is already resolved."""
    api_key = settings.llm_api_key
    provider = _provider_name()
    model = settings.llm_model
    timeout = settings.llm_timeout_seconds
    if not api_key:
        return

    grounded_prompt = (
        f"{user_message}\n\n"
        f"[VERIFIED_DATABASE_CONTEXT_JSON]\n{json.dumps(grounded_context, default=str)}"
    )

    if provider in ("", "gemini", "google"):
        resolved_model = model or "gemini-2.5-flash"
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{resolved_model}:streamGenerateContent?alt=sse"
        )
        headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}
        contents = [
            {"role": "model" if t["role"] == "assistant" else "user", "parts": [{"text": t["content"]}]}
            for t in history
        ]
        contents.append({"role": "user", "parts": [{"text": grounded_prompt}]})
        payload = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": contents,
            "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.35},
        }
        with httpx.stream("POST", url, headers=headers, json=payload, timeout=timeout) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line or not line.startswith("data:"):
                    continue
                raw = line[5:].strip()
                if not raw or raw == "[DONE]":
                    continue
                chunk = json.loads(raw)
                for cand in chunk.get("candidates") or []:
                    for part in cand.get("content", {}).get("parts", []):
                        if part.get("thought"):
                            continue
                        txt = part.get("text")
                        if txt:
                            yield txt
        return

    if provider in ("openai", "groq", "openrouter"):
        url, default_model = _openai_compatible_endpoint(provider)
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend({"role": t["role"], "content": t["content"]} for t in history)
        messages.append({"role": "user", "content": grounded_prompt})
        payload = {
            "model": model or default_model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.35,
            "stream": True,
        }
        with httpx.stream("POST", url, headers=headers, json=payload, timeout=timeout) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line or not line.startswith("data:"):
                    continue
                raw = line[5:].strip()
                if raw == "[DONE]":
                    break
                chunk = json.loads(raw)
                delta = (chunk.get("choices") or [{}])[0].get("delta", {}).get("content")
                if delta:
                    yield delta
