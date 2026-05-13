"""
QA模块的异常处理器

异常处理器通过 startup.py 中的 register_module_exceptions 统一注册。
此处仅保留 LLM 服务特殊处理器。
"""


# ========== LLM 服务特殊处理器（包含原始错误信息）==========

async def llm_service_exception_handler(request, exc):
    """处理LLM服务异常（包含原始错误详情）"""
    from src.core.middleware.base_exception_handler import _build_trace_context, logger
    from fastapi.responses import JSONResponse
    from src.shared.utils.time_utils import now_china

    ctx = _build_trace_context(request)
    trace_id = ctx.get("trace_id", "no-trace")

    error_detail = exc.to_dict()

    # 如果有原始错误，添加详细信息
    if getattr(exc, "original_error", None):
        error_detail["original_error"] = str(exc.original_error)

    logger.error(
        "LLM服务错误",
        error_code=exc.code,
        error_message=exc.message,
        **ctx,
    )
    return JSONResponse(
        status_code=500,
        content={"error": error_detail, "timestamp": now_china().isoformat()},
    )
