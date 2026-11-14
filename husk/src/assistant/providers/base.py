from __future__ import annotations

from dataclasses import dataclass, field
from typing import AsyncIterator, Protocol


@dataclass(frozen=True)
class ChatMessageInput:
    role: str
    content: str


@dataclass(frozen=True)
class GenerationOptions:
    model: str
    temperature: float = 0.7
    max_output_tokens: int = 2048


@dataclass(frozen=True)
class Usage:
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass
class Completion:
    text: str
    usage: Usage = field(default_factory=Usage)


@dataclass
class StreamChunk:
    delta: str = ""
    usage: Usage | None = None


class ChatProvider(Protocol):
    async def complete(self, messages: list[ChatMessageInput], options: GenerationOptions,
                       api_key: str | None, base_url: str | None = None) -> Completion: ...

    def stream(self, messages: list[ChatMessageInput], options: GenerationOptions,
               api_key: str | None, base_url: str | None = None) -> AsyncIterator[StreamChunk]: ...
