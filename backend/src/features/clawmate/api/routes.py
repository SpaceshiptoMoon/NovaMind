"""
ClawMate API 路由

提供 Web 终端能力：命令执行、文件操作、Session 管理、AI 对话。
所有端点需要 JWT 认证。
"""

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from src.features.user.api.auth import get_current_user
from src.features.clawmate.api.dependencies import (
    get_session_manager,
    get_user_environment,
    get_file_operations,
    get_chat_service,
)
from src.features.clawmate.core.session_manager import SessionManager
from src.features.clawmate.core.environment import LocalEnvironment
from src.features.clawmate.core.file_operations import FileOperations
from src.features.clawmate.core.config import ClawMateConfig
from src.features.clawmate.core.chat_service import ClawMateChatService
from src.features.clawmate.schemas.clawmate_schema import (
    SessionInitRequest,
    SessionStatusResponse,
    SessionDestroyResponse,
    ExecuteRequest,
    ExecuteResponse,
    FileReadRequest,
    FileWriteRequest,
    FileAppendRequest,
    DirListRequest,
    FileSearchRequest,
    GrepRequest,
    FileDeleteRequest,
    FileMoveRequest,
    FileCopyRequest,
    DirCreateRequest,
    FileOperationResponse,
    ClawMateChatRequest,
)
from src.features.clawmate.api.exceptions import CommandBlockedError
from src.features.clawmate.core.command_safety import check_command_safety
from src.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)

router = APIRouter()


# ==================== 工具函数 ====================


def _get_user_id(current_user: dict) -> int:
    return current_user["id"]


def _check_blocked(command: str, config: ClawMateConfig):
    """检查命令是否在黑名单中"""
    cmd_lower = command.lower().strip()
    for blocked in config.blocked_commands:
        if blocked.lower() in cmd_lower:
            raise CommandBlockedError()


def _load_config() -> ClawMateConfig:
    """加载 ClawMate 配置"""
    return ClawMateConfig.from_yaml()


# ==================== Session 管理 ====================


@router.post(
    "/session/init",
    response_model=SessionStatusResponse,
    summary="初始化 Session",
    description="初始化或重置用户的终端环境",
)
async def init_session(
    data: SessionInitRequest,
    current_user: dict = Depends(get_current_user),
    manager: SessionManager = Depends(get_session_manager),
):
    user_id = _get_user_id(current_user)

    # 销毁旧 session（如果存在）
    manager.destroy(user_id)

    # 创建新环境
    env = manager.get_or_create(user_id, cwd=data.cwd)
    status = manager.get_status(user_id)

    logger.info("ClawMate session 已初始化", user_id=user_id, session_id=env.session_id)
    return SessionStatusResponse(**status)


@router.post(
    "/session/execute",
    response_model=ExecuteResponse,
    summary="执行命令",
    description="在用户终端环境中执行 Shell 命令",
)
async def execute_command(
    data: ExecuteRequest,
    current_user: dict = Depends(get_current_user),
    env: LocalEnvironment = Depends(get_user_environment),
    manager: SessionManager = Depends(get_session_manager),
):
    user_id = _get_user_id(current_user)

    # 安全检查（两层：配置黑名单 + 命令安全正则检测）
    config = _load_config()
    _check_blocked(data.command, config)

    # 两级命令安全检测（硬封锁 + 危险模式）
    safe, reason = check_command_safety(data.command)
    if not safe:
        raise CommandBlockedError()

    # 更新活跃时间
    manager.touch(user_id)

    # 执行
    timeout = data.timeout or config.default_timeout
    result = env.execute(data.command, timeout=timeout)

    # 截断输出
    output = result["output"]
    if len(output) > config.max_output_size:
        output = output[: config.max_output_size] + f"\n... (输出已截断，共 {len(result['output'])} 字符)"

    return ExecuteResponse(
        output=output,
        returncode=result["returncode"],
        cwd=result["cwd"],
    )


@router.get(
    "/session/status",
    response_model=SessionStatusResponse,
    summary="获取 Session 状态",
    description="获取当前终端 session 的状态信息",
)
async def get_session_status(
    current_user: dict = Depends(get_current_user),
    manager: SessionManager = Depends(get_session_manager),
):
    user_id = _get_user_id(current_user)
    status = manager.get_status(user_id)

    if status is None:
        from src.features.clawmate.api.exceptions import SessionNotInitializedError
        raise SessionNotInitializedError()

    return SessionStatusResponse(**status)


@router.delete(
    "/session",
    response_model=SessionDestroyResponse,
    summary="销毁 Session",
    description="销毁当前终端 session，释放资源",
)
async def destroy_session(
    current_user: dict = Depends(get_current_user),
    manager: SessionManager = Depends(get_session_manager),
):
    user_id = _get_user_id(current_user)
    destroyed = manager.destroy(user_id)

    return SessionDestroyResponse(
        destroyed=destroyed,
        session_id=None,
    )


# ==================== 文件操作 ====================


@router.post(
    "/files/read",
    summary="读取文件",
    description="读取指定文件的内容，支持分页",
)
async def read_file(
    data: FileReadRequest,
    ops: FileOperations = Depends(get_file_operations),
):
    return await ops.read_file(
        path=data.path,
        offset=data.offset,
        limit=data.limit,
    )


@router.post(
    "/files/write",
    response_model=FileOperationResponse,
    summary="写入文件",
    description="写入文件内容（覆盖），可自动创建父目录",
)
async def write_file(
    data: FileWriteRequest,
    ops: FileOperations = Depends(get_file_operations),
):
    result = await ops.write_file(
        path=data.path,
        content=data.content,
        create_dirs=data.create_dirs,
    )
    return FileOperationResponse(**result)


@router.post(
    "/files/append",
    response_model=FileOperationResponse,
    summary="追加文件",
    description="追加内容到文件末尾",
)
async def append_file(
    data: FileAppendRequest,
    ops: FileOperations = Depends(get_file_operations),
):
    result = await ops.append_file(
        path=data.path,
        content=data.content,
    )
    return FileOperationResponse(**result)


@router.post(
    "/files/list",
    summary="列出目录",
    description="列出指定目录下的文件和子目录",
)
async def list_dir(
    data: DirListRequest,
    ops: FileOperations = Depends(get_file_operations),
):
    return await ops.list_dir(
        path=data.path,
        pattern=data.pattern,
        show_hidden=data.show_hidden,
    )


@router.post(
    "/files/search",
    summary="搜索文件",
    description="按文件名模式搜索文件",
)
async def search_files(
    data: FileSearchRequest,
    ops: FileOperations = Depends(get_file_operations),
):
    return await ops.search_files(
        path=data.path,
        pattern=data.pattern,
        max_results=data.max_results,
    )


@router.post(
    "/files/grep",
    summary="搜索文件内容",
    description="在文件中搜索匹配指定模式的内容",
)
async def grep_files(
    data: GrepRequest,
    ops: FileOperations = Depends(get_file_operations),
):
    return await ops.grep(
        path=data.path,
        pattern=data.pattern,
        file_pattern=data.file_pattern,
        max_results=data.max_results,
        context_lines=data.context_lines,
    )


@router.post(
    "/files/delete",
    response_model=FileOperationResponse,
    summary="删除文件",
    description="删除文件或空目录",
)
async def delete_file(
    data: FileDeleteRequest,
    ops: FileOperations = Depends(get_file_operations),
):
    result = await ops.delete(path=data.path)
    return FileOperationResponse(**result)


@router.post(
    "/files/move",
    response_model=FileOperationResponse,
    summary="移动/重命名",
    description="移动或重命名文件/目录",
)
async def move_file(
    data: FileMoveRequest,
    ops: FileOperations = Depends(get_file_operations),
):
    result = await ops.move(
        source=data.source,
        destination=data.destination,
    )
    return FileOperationResponse(**result)


@router.post(
    "/files/copy",
    response_model=FileOperationResponse,
    summary="复制",
    description="复制文件或目录",
)
async def copy_file(
    data: FileCopyRequest,
    ops: FileOperations = Depends(get_file_operations),
):
    result = await ops.copy(
        source=data.source,
        destination=data.destination,
    )
    return FileOperationResponse(**result)


@router.post(
    "/files/create-dir",
    response_model=FileOperationResponse,
    summary="创建目录",
    description="创建目录（含父目录）",
)
async def create_dir(
    data: DirCreateRequest,
    ops: FileOperations = Depends(get_file_operations),
):
    result = await ops.create_dir(path=data.path)
    return FileOperationResponse(**result)


# ==================== AI 对话 ====================


@router.post(
    "/chat",
    summary="AI 对话（SSE 流式）",
    description="与 ClawMate AI 助手进行流式对话。自动创建 session，无需先调用初始化接口。",
)
async def chat(
    data: ClawMateChatRequest,
    current_user: dict = Depends(get_current_user),
    service: ClawMateChatService = Depends(get_chat_service),
):
    user_id = _get_user_id(current_user)
    return StreamingResponse(
        service.chat_stream(
            user_id=user_id,
            content=data.content,
            model=data.model,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
