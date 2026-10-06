"""OpenAI 兼容网关请求 schema：对齐官方 /v1/chat/completions 请求形状。

兼容性优先：未知字段静默忽略（extra="ignore"，官方 SDK 会随版本附带新字段，
如 reasoning_effort/web_search_options，拒绝即破坏兼容）；content 兼容官方
多模态数组形状（list part 的 text 部件提取拼接）。
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ChatMessage(BaseModel):
    """单条对话消息（OpenAI Chat Completions 格式）。"""

    model_config = ConfigDict(extra="ignore")

    role: Literal["system", "user", "assistant", "tool", "developer"]
    content: str | list[dict[str, Any]] | None = None
    name: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None

    def to_openai_dict(self) -> dict[str, Any]:
        """归一化为 OpenAI dict：content 数组提取 text 部件拼接为纯文本。

        NovaMind 各协议客户端的统一入口吃纯文本 content（多模态部件由
        上游协议适配层处理），网关在此收口一次。
        """
        content = self.content
        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    parts.append(part["text"])
            content = "\n".join(parts)
        msg: dict[str, Any] = {"role": self.role, "content": content}
        if self.name is not None:
            msg["name"] = self.name
        if self.tool_calls is not None:
            msg["tool_calls"] = self.tool_calls
        if self.tool_call_id is not None:
            msg["tool_call_id"] = self.tool_call_id
        return msg


class ChatCompletionRequest(BaseModel):
    """POST /v1/chat/completions 请求体。"""

    model_config = ConfigDict(extra="ignore")

    model: str = Field(min_length=1)
    messages: list[ChatMessage] = Field(min_length=1)
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    stream: bool = False
    tools: list[dict[str, Any]] | None = None
    tool_choice: str | dict[str, Any] | None = None
    # NovaMind 扩展（DashScope enable_thinking 同名惯例）：显式开启思考
    enable_thinking: bool = False
