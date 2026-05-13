"""
结构化工具执行结果

替代现有的裸 str 返回值，支持多种内容类型和元数据。
"""
import json
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ToolResultStatus(str, Enum):
    """工具执行状态"""
    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"
    PERMISSION_DENIED = "permission_denied"


class ToolResult(BaseModel):
    """
    结构化工具执行结果

    封装工具执行的完整信息：
    - status: 执行状态
    - content: 文本结果（主要输出）
    - data: 结构化数据（可选，如搜索结果列表）
    - duration_ms: 执行耗时
    - error_message: 错误信息
    - metadata: 扩展元数据（如截断标记）
    """

    status: ToolResultStatus = ToolResultStatus.SUCCESS
    content: str = ""
    data: Optional[Dict[str, Any]] = None
    duration_ms: int = 0
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def to_llm_content(self) -> str:
        """转换为 LLM 可消费的文本"""
        if self.status == ToolResultStatus.ERROR:
            return f"工具执行失败：{self.error_message}"

        if self.data:
            return json.dumps(self.data, ensure_ascii=False, indent=2)

        return self.content
