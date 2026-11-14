from __future__ import annotations

from collections.abc import AsyncIterator

from anthropic import AsyncAnthropic
from google import genai
from google.genai import types
from openai import AsyncOpenAI, BadRequestError

from assistant.providers.base import ChatMessageInput, Completion, GenerationOptions, StreamChunk, Usage


def _split_system(messages: list[ChatMessageInput]) -> tuple[str, list[dict]]:
    system = "\n".join(m.content for m in messages if m.role == "system")
    chat = [{"role": m.role, "content": m.content} for m in messages if m.role != "system"]
    return system, chat


class OpenAIAdapter:
    """OpenAI and any OpenAI-compatible server (LM Studio, vLLM, Ollama's /v1 endpoint...)."""

    def __init__(self, *, use_completion_tokens: bool = False):
        # api.openai.com rejects `max_tokens` for newer models; compatible servers only know it.
        self._token_param = "max_completion_tokens" if use_completion_tokens else "max_tokens"

    def _kwargs(self, messages, options, *, with_temperature=True, **extra):
        kwargs = {
            "model": options.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            self._token_param: options.max_output_tokens,
            **extra,
        }
        if with_temperature:
            kwargs["temperature"] = options.temperature
        return kwargs

    @staticmethod
    def _client(api_key, base_url):
        return AsyncOpenAI(api_key=api_key or "not-needed", base_url=base_url)

    async def _create(self, client, messages, options, **extra):
        try:
            return await client.chat.completions.create(**self._kwargs(messages, options, **extra))
        except BadRequestError as exc:
            # Some models (e.g. reasoning models) only accept the default temperature, and some
            # servers don't know stream_options.  Retry once without the offending argument.
            text = str(exc).lower()
            if "temperature" in text:
                return await client.chat.completions.create(**self._kwargs(messages, options, with_temperature=False, **extra))
            if "stream_options" in text and "stream_options" in extra:
                extra = {k: v for k, v in extra.items() if k != "stream_options"}
                return await client.chat.completions.create(**self._kwargs(messages, options, **extra))
            raise

    async def complete(self, messages, options, api_key, base_url=None) -> Completion:
        client = self._client(api_key, base_url)
        response = await self._create(client, messages, options)
        usage = getattr(response, "usage", None)
        return Completion(
            response.choices[0].message.content or "" if response.choices else "",
            Usage(getattr(usage, "prompt_tokens", None), getattr(usage, "completion_tokens", None)),
        )

    async def stream(self, messages, options, api_key, base_url=None) -> AsyncIterator[StreamChunk]:
        client = self._client(api_key, base_url)
        stream = await self._create(client, messages, options, stream=True, stream_options={"include_usage": True})
        async for chunk in stream:
            usage = getattr(chunk, "usage", None)
            if usage is not None:
                yield StreamChunk(usage=Usage(usage.prompt_tokens, usage.completion_tokens))
            if chunk.choices:  # the final usage-only chunk has no choices
                delta = chunk.choices[0].delta.content
                if delta:
                    yield StreamChunk(delta=delta)


class AnthropicAdapter:
    async def complete(self, messages, options, api_key, base_url=None) -> Completion:
        client = AsyncAnthropic(api_key=api_key, base_url=base_url)
        system, chat = _split_system(messages)
        response = await client.messages.create(
            model=options.model, max_tokens=options.max_output_tokens, temperature=options.temperature,
            system=system or "", messages=chat,
        )
        text = "".join(b.text for b in response.content if getattr(b, "type", None) == "text")
        return Completion(text, Usage(response.usage.input_tokens, response.usage.output_tokens))

    async def stream(self, messages, options, api_key, base_url=None) -> AsyncIterator[StreamChunk]:
        client = AsyncAnthropic(api_key=api_key, base_url=base_url)
        system, chat = _split_system(messages)
        async with client.messages.stream(
            model=options.model, max_tokens=options.max_output_tokens, temperature=options.temperature,
            system=system or "", messages=chat,
        ) as stream:
            async for part in stream.text_stream:
                yield StreamChunk(delta=part)
            final = await stream.get_final_message()
            yield StreamChunk(usage=Usage(final.usage.input_tokens, final.usage.output_tokens))


class GeminiAdapter:
    @staticmethod
    def _request(messages, options):
        system = "\n".join(m.content for m in messages if m.role == "system")
        contents = [
            types.Content(role="user" if m.role == "user" else "model", parts=[types.Part(text=m.content)])
            for m in messages if m.role != "system"
        ]
        config = types.GenerateContentConfig(
            temperature=options.temperature, max_output_tokens=options.max_output_tokens,
            system_instruction=system or None,
        )
        return contents, config

    @staticmethod
    def _usage(meta) -> Usage | None:
        if meta is None:
            return None
        return Usage(getattr(meta, "prompt_token_count", None), getattr(meta, "candidates_token_count", None))

    async def complete(self, messages, options, api_key, base_url=None) -> Completion:
        client = genai.Client(api_key=api_key)
        contents, config = self._request(messages, options)
        result = await client.aio.models.generate_content(model=options.model, contents=contents, config=config)
        return Completion(result.text or "", self._usage(getattr(result, "usage_metadata", None)) or Usage())

    async def stream(self, messages, options, api_key, base_url=None) -> AsyncIterator[StreamChunk]:
        client = genai.Client(api_key=api_key)
        contents, config = self._request(messages, options)
        stream = await client.aio.models.generate_content_stream(model=options.model, contents=contents, config=config)
        last_usage = None
        async for part in stream:
            if part.text:
                yield StreamChunk(delta=part.text)
            last_usage = self._usage(getattr(part, "usage_metadata", None)) or last_usage
        if last_usage:
            yield StreamChunk(usage=last_usage)
