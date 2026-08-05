"""
统一工具定义模型

所有工具（内置工具/MCP/自定义）统一为 ToolDefinition，
可通过 to_openai_format() 输出 LLM 需要的格式。
"""
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ToolSource(str, Enum):
    """工具来源"""
    BUILTIN = "builtin"
    MCP = "mcp"
    CUSTOM = "custom"


class ToolParameter(BaseModel):
    """工具参数定义"""
    type: str = "string"
    description: str = ""
    enum: Optional[List[str]] = None
    default: Optional[Any] = None


class ToolDefinition(BaseModel):
    """
    统一工具定义模型

    所有工具统一为这个模型，
    可通过 to_openai_format() 输出 LLM function calling 格式。
    """

    name: str
    description: str
    parameters: Dict[str, ToolParameter] = Field(default_factory=dict)
    required: List[str] = Field(default_factory=list)
    source: ToolSource = ToolSource.BUILTIN
    source_ref: Optional[str] = None  # 来源标识（如 MCP server_name）
    timeout_ms: int = 30000
    dangerous: bool = False

    def to_openai_format(self) -> Dict[str, Any]:
        """转换为 OpenAI function calling 格式"""
        properties: Dict[str, Any] = {}
        for name, param in self.parameters.items():
            prop: Dict[str, Any] = {"type": param.type}
            if param.description:
                prop["description"] = param.description
            if param.enum:
                prop["enum"] = param.enum
            if param.default is not None:
                prop["default"] = param.default
            properties[name] = prop

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": self.required,
                },
            },
        }
