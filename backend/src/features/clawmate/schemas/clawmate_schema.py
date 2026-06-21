"""
ClawMate Schema

请求和响应的 Pydantic 模型
"""

from typing import Optional, List
from pydantic import BaseModel, Field


# ==================== Session ====================


class SessionInitRequest(BaseModel):
    """初始化 session 请求"""
    cwd: str = Field(default="~", description="初始工作目录")


class SessionStatusResponse(BaseModel):
    """Session 状态响应"""
    model_config = {"extra": "ignore"}

    session_id: str = Field(..., description="Session ID")
    cwd: str = Field(..., description="当前工作目录")
    is_alive: bool = Field(..., description="环境是否有效")
    idle_seconds: float = Field(..., description="空闲时间（秒）")
    history_count: int = Field(default=0, description="对话历史消息数量")


class SessionDestroyResponse(BaseModel):
    """销毁 session 响应"""
    destroyed: bool = Field(..., description="是否成功销毁")
    session_id: Optional[str] = Field(None, description="被销毁的 Session ID")


# ==================== 命令执行 ====================


class ExecuteRequest(BaseModel):
    """执行命令请求"""
    command: str = Field(..., min_length=1, max_length=10000, description="要执行的命令")
    timeout: Optional[int] = Field(None, ge=1, le=300, description="超时时间（秒）")


class ExecuteResponse(BaseModel):
    """命令执行响应"""
    output: str = Field(..., description="命令输出")
    returncode: int = Field(..., description="退出码")
    cwd: str = Field(..., description="执行后的当前目录")


# ==================== 文件操作 ====================


class FileReadRequest(BaseModel):
    """读取文件请求"""
    path: str = Field(..., description="文件路径")
    offset: int = Field(default=0, ge=0, description="起始行号")
    limit: int = Field(default=2000, ge=1, le=5000, description="最大读取行数")


class FileWriteRequest(BaseModel):
    """写入文件请求"""
    path: str = Field(..., description="文件路径")
    content: str = Field(..., description="文件内容")
    create_dirs: bool = Field(default=False, description="是否自动创建父目录")


class FileAppendRequest(BaseModel):
    """追加文件请求"""
    path: str = Field(..., description="文件路径")
    content: str = Field(..., description="追加内容")


class DirListRequest(BaseModel):
    """列出目录请求"""
    path: str = Field(default=".", description="目录路径")
    pattern: str = Field(default="*", description="文件名过滤（glob）")
    show_hidden: bool = Field(default=False, description="是否显示隐藏文件")


class FileSearchRequest(BaseModel):
    """搜索文件请求"""
    path: str = Field(..., description="搜索根目录")
    pattern: str = Field(..., description="文件名模式（如 *.py）")
    max_results: int = Field(default=50, ge=1, le=500, description="最大结果数")


class GrepRequest(BaseModel):
    """搜索文件内容请求"""
    path: str = Field(..., description="搜索根目录")
    pattern: str = Field(..., description="搜索的正则表达式")
    file_pattern: str = Field(default="*", description="文件名过滤（如 *.py）")
    max_results: int = Field(default=30, ge=1, le=200, description="最大匹配数")
    context_lines: int = Field(default=2, ge=0, le=10, description="上下文行数")


class FileDeleteRequest(BaseModel):
    """删除请求"""
    path: str = Field(..., description="文件或空目录路径")


class FileMoveRequest(BaseModel):
    """移动/重命名请求"""
    source: str = Field(..., description="源路径")
    destination: str = Field(..., description="目标路径")


class FileCopyRequest(BaseModel):
    """复制请求"""
    source: str = Field(..., description="源路径")
    destination: str = Field(..., description="目标路径")


class DirCreateRequest(BaseModel):
    """创建目录请求"""
    path: str = Field(..., description="目录路径")


# ==================== 通用响应 ====================


class FileOperationResponse(BaseModel):
    """文件操作通用响应"""
    model_config = {"extra": "ignore"}

    error: Optional[str] = Field(None, description="错误信息")
    path: Optional[str] = Field(None, description="操作路径")
    source: Optional[str] = Field(None, description="源路径（移动/复制操作）")
    destination: Optional[str] = Field(None, description="目标路径（移动/复制操作）")
    deleted: Optional[bool] = Field(None, description="是否已删除")
    moved: Optional[bool] = Field(None, description="是否已移动")
    copied: Optional[bool] = Field(None, description="是否已复制")
    created: Optional[bool] = Field(None, description="是否已创建")
    type: Optional[str] = Field(None, description="操作对象类型（file/directory）")


# ==================== AI 对话 ====================


class ClawMateChatRequest(BaseModel):
    """ClawMate AI 对话请求"""
    content: str = Field(..., min_length=1, max_length=50000, description="用户消息")
    model: Optional[str] = Field(None, description="LLM 模型名称，不传则使用默认模型")
