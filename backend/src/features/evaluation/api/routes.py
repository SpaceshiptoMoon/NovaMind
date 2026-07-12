"""
测评模块路由

路由前缀: /api/v1/spaces/{space_id}/knowledge-bases/{kb_id}/evaluation
"""
import io
from typing import Annotated, Literal, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, UploadFile, File, Form, Path, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from novamind.core.database.database import get_db
from novamind.features.knowledge_space.models.space_member import SpaceMember
from novamind.features.knowledge_space.api.dependencies import (
    get_current_user_id,
    validate_space_member,
    validate_space_editor,
    validate_kb_access,
)
from novamind.features.evaluation.api.dependencies import get_evaluation_service
from novamind.features.evaluation.api.exceptions import (
    EvaluationTestSetNotFoundError,
    EvaluationTaskNotFoundError,
    EvaluationTaskPendingError,
    EvaluationTaskNotCompletedError,
    EvaluationAccessDeniedError,
)


def _check_task_owner(task, member: SpaceMember) -> None:
    """校验测评任务归属：仅任务作者或空间管理员可操作。

    在端点取到 task 后调用，统一收敛越权校验，
    避免空间内任意成员越权操作他人创建的测评任务。
    """
    if task.user_id != member.user_id and not member.is_admin():
        raise EvaluationAccessDeniedError(task.id, member.user_id)
from novamind.features.evaluation.schemas.evaluation_schema import (
    EvaluationTaskCreateResponse,
    EvaluationTaskListItem,
    EvaluationTaskListResponse,
    EvaluationTaskDetailResponse,
    EvaluationReportResponse,
    EvaluationTaskCancelResponse,
    EvaluationTaskProgressResponse,
    HumanScoreRequest,
    HumanScoreResponse,
    TestSetCreateResponse,
    TestSetListItem,
    TestSetListResponse,
    TestSetDetailResponse,
    TestSetUpdateRequest,
    TestSetCasesResponse,
    TaskCreateRequest,
    TestCase,
)
from novamind.features.evaluation.models.evaluation_task import EvaluationStatus
from novamind.features.evaluation.services.evaluation_service import EvaluationService
from novamind.features.evaluation.services.test_set_parser import parse_test_set
from novamind.features.knowledge_space.schemas.member_schema import ActionResponse

router = APIRouter(tags=["知识库测评"])

ALLOWED_TEST_SET_EXTENSIONS = {".json", ".csv"}
MAX_TEST_SET_SIZE = 10 * 1024 * 1024  # 10MB


# ========== 测试集管理 ==========

@router.post(
    "/test-sets",
    status_code=201,
    response_model=TestSetCreateResponse,
    summary="上传测试集",
    description="上传测试集文件（JSON/CSV）到 MinIO",
)
async def create_test_set(
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    kb_id: Annotated[int, Path(gt=0, description="知识库ID")],
    file: UploadFile = File(..., description="测试集文件（.json 或 .csv）"),
    name: str = Form(..., description="测试集名称"),
    user_id: int = Depends(get_current_user_id),
    member: SpaceMember = Depends(validate_space_editor),
    evaluation_service: EvaluationService = Depends(get_evaluation_service),
    db: AsyncSession = Depends(get_db),
):
    await validate_kb_access(kb_id, space_id, db)

    filename = file.filename or ""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if f".{ext}" not in ALLOWED_TEST_SET_EXTENSIONS:
        from novamind.features.evaluation.api.exceptions import InvalidTestSetError
        raise InvalidTestSetError(f"不支持的文件格式: .{ext}，仅支持 {sorted(ALLOWED_TEST_SET_EXTENSIONS)}")

    content = await file.read()
    if not content:
        from novamind.features.evaluation.api.exceptions import InvalidTestSetError
        raise InvalidTestSetError("文件内容为空")

    if len(content) > MAX_TEST_SET_SIZE:
        from novamind.features.evaluation.api.exceptions import InvalidTestSetError
        raise InvalidTestSetError(f"文件大小超过限制（最大 {MAX_TEST_SET_SIZE // 1024 // 1024}MB）")

    parse_test_set(content, filename)

    test_set_obj = await evaluation_service.create_test_set(
        space_id=space_id, kb_id=kb_id, user_id=user_id,
        name=name, file_content=content, filename=filename,
    )

    return TestSetCreateResponse(
        test_set_id=test_set_obj.id, name=test_set_obj.name,
        filename=test_set_obj.filename, file_type=test_set_obj.file_type,
        file_size=test_set_obj.file_size, total_cases=test_set_obj.total_cases,
    )


@router.get(
    "/test-sets",
    response_model=TestSetListResponse,
    summary="获取测试集列表",
)
async def list_test_sets(
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    kb_id: Annotated[int, Path(gt=0, description="知识库ID")],
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    member: SpaceMember = Depends(validate_space_member),
    evaluation_service: EvaluationService = Depends(get_evaluation_service),
    db: AsyncSession = Depends(get_db),
):
    await validate_kb_access(kb_id, space_id, db)
    test_sets, total = await evaluation_service.list_test_sets(space_id, kb_id, skip, limit)
    items = [TestSetListItem.model_validate(ts) for ts in test_sets]
    return TestSetListResponse(items=items, total=total, skip=skip, limit=limit)


@router.get(
    "/test-sets/{test_set_id}",
    response_model=TestSetDetailResponse,
    summary="获取测试集详情",
)
async def get_test_set(
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    kb_id: Annotated[int, Path(gt=0, description="知识库ID")],
    test_set_id: Annotated[int, Path(gt=0, description="测试集ID")],
    member: SpaceMember = Depends(validate_space_member),
    evaluation_service: EvaluationService = Depends(get_evaluation_service),
    db: AsyncSession = Depends(get_db),
):
    await validate_kb_access(kb_id, space_id, db)
    test_set_obj = await evaluation_service.get_test_set_by_kb(test_set_id, space_id, kb_id)
    if not test_set_obj:
        raise EvaluationTestSetNotFoundError(test_set_id)
    return TestSetDetailResponse.model_validate(test_set_obj)


@router.put(
    "/test-sets/{test_set_id}",
    response_model=TestSetDetailResponse,
    summary="更新测试集",
    description="更新测试集名称",
)
async def update_test_set(
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    kb_id: Annotated[int, Path(gt=0, description="知识库ID")],
    test_set_id: Annotated[int, Path(gt=0, description="测试集ID")],
    body: TestSetUpdateRequest,
    user_id: int = Depends(get_current_user_id),
    member: SpaceMember = Depends(validate_space_editor),
    evaluation_service: EvaluationService = Depends(get_evaluation_service),
    db: AsyncSession = Depends(get_db),
):
    await validate_kb_access(kb_id, space_id, db)
    test_set_obj = await evaluation_service.update_test_set(test_set_id, space_id, kb_id, body.name)
    return TestSetDetailResponse.model_validate(test_set_obj)


@router.get(
    "/test-sets/{test_set_id}/cases",
    response_model=TestSetCasesResponse,
    summary="预览测试集用例",
    description="从 MinIO 读取测试集文件并返回用例列表",
)
async def get_test_set_cases(
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    kb_id: Annotated[int, Path(gt=0, description="知识库ID")],
    test_set_id: Annotated[int, Path(gt=0, description="测试集ID")],
    member: SpaceMember = Depends(validate_space_member),
    evaluation_service: EvaluationService = Depends(get_evaluation_service),
    db: AsyncSession = Depends(get_db),
):
    await validate_kb_access(kb_id, space_id, db)
    result = await evaluation_service.get_test_set_cases(test_set_id, space_id, kb_id)
    if not result:
        raise EvaluationTestSetNotFoundError(test_set_id)
    test_set_obj, cases = result
    return TestSetCasesResponse(
        test_set_id=test_set_obj.id,
        total_cases=len(cases),
        test_cases=[TestCase(**c) for c in cases],
    )


@router.delete(
    "/test-sets/{test_set_id}",
    response_model=ActionResponse,
    summary="删除测试集",
    description="删除指定的测试集及其关联文件",
)
async def delete_test_set(
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    kb_id: Annotated[int, Path(gt=0, description="知识库ID")],
    test_set_id: Annotated[int, Path(gt=0, description="测试集ID")],
    user_id: int = Depends(get_current_user_id),
    member: SpaceMember = Depends(validate_space_editor),
    evaluation_service: EvaluationService = Depends(get_evaluation_service),
    db: AsyncSession = Depends(get_db),
):
    await validate_kb_access(kb_id, space_id, db)
    # 校验测试集归属当前知识库，防止越权删除
    test_set_obj = await evaluation_service.get_test_set_by_kb(test_set_id, space_id, kb_id)
    if not test_set_obj:
        from novamind.features.evaluation.api.exceptions import EvaluationTestSetNotFoundError
        raise EvaluationTestSetNotFoundError(test_set_id)
    result = await evaluation_service.delete_test_set(test_set_id)
    return {"success": result, "message": "测试集已删除"}


# ========== 测评任务管理 ==========

@router.post(
    "/tasks",
    status_code=202,
    response_model=EvaluationTaskCreateResponse,
    summary="创建测评任务",
    description="基于测试集创建测评任务，自动异步执行",
)
async def create_evaluation_task(
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    kb_id: Annotated[int, Path(gt=0, description="知识库ID")],
    body: TaskCreateRequest,
    user_id: int = Depends(get_current_user_id),
    member: SpaceMember = Depends(validate_space_editor),
    evaluation_service: EvaluationService = Depends(get_evaluation_service),
    db: AsyncSession = Depends(get_db),
):
    await validate_kb_access(kb_id, space_id, db)

    test_set_obj = await evaluation_service.get_test_set_by_kb(body.test_set_id, space_id, kb_id)
    if not test_set_obj:
        raise EvaluationTestSetNotFoundError(body.test_set_id)

    config_dict = body.config.model_dump() if body.config else None

    task = await evaluation_service.create_task(
        test_set_id=body.test_set_id, user_id=user_id,
        name=body.name, config=config_dict,
    )

    return EvaluationTaskCreateResponse(
        task_id=task.id, name=task.name,
        test_set_id=task.test_set_id,
        status=EvaluationStatus(task.status).name.lower(),
        message="测评任务已创建，等待执行",
    )


@router.get(
    "/tasks",
    response_model=EvaluationTaskListResponse,
    summary="获取测评任务列表",
)
async def list_evaluation_tasks(
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    kb_id: Annotated[int, Path(gt=0, description="知识库ID")],
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    status: Annotated[Optional[int], Query(description="按状态过滤: 1-pending 2-completed 3-failed 5-running 6-cancelled")] = None,
    member: SpaceMember = Depends(validate_space_member),
    evaluation_service: EvaluationService = Depends(get_evaluation_service),
    db: AsyncSession = Depends(get_db),
):
    await validate_kb_access(kb_id, space_id, db)
    tasks, total = await evaluation_service.list_tasks(space_id, kb_id, skip, limit, status=status)
    items = [EvaluationTaskListItem.model_validate(t) for t in tasks]
    return EvaluationTaskListResponse(items=items, total=total, skip=skip, limit=limit)


@router.get(
    "/tasks/{task_id}",
    response_model=EvaluationTaskDetailResponse,
    summary="获取测评任务详情",
)
async def get_evaluation_task(
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    kb_id: Annotated[int, Path(gt=0, description="知识库ID")],
    task_id: Annotated[int, Path(gt=0, description="任务ID")],
    member: SpaceMember = Depends(validate_space_member),
    evaluation_service: EvaluationService = Depends(get_evaluation_service),
    db: AsyncSession = Depends(get_db),
):
    await validate_kb_access(kb_id, space_id, db)
    task = await evaluation_service.get_task_by_kb(task_id, space_id, kb_id)
    if not task:
        raise EvaluationTaskNotFoundError(task_id)
    _check_task_owner(task, member)
    return EvaluationTaskDetailResponse.model_validate(task)


@router.delete(
    "/tasks/{task_id}",
    response_model=ActionResponse,
    summary="删除测评任务",
    description="删除指定的测评任务及其关联结果",
)
async def delete_evaluation_task(
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    kb_id: Annotated[int, Path(gt=0, description="知识库ID")],
    task_id: Annotated[int, Path(gt=0, description="任务ID")],
    user_id: int = Depends(get_current_user_id),
    member: SpaceMember = Depends(validate_space_editor),
    evaluation_service: EvaluationService = Depends(get_evaluation_service),
    db: AsyncSession = Depends(get_db),
):
    await validate_kb_access(kb_id, space_id, db)
    # 校验任务归属当前知识库 + 作者/管理员权限，防止越权删除
    task = await evaluation_service.get_task_by_kb(task_id, space_id, kb_id)
    if not task:
        raise EvaluationTaskNotFoundError(task_id)
    _check_task_owner(task, member)
    result = await evaluation_service.delete_task(task_id)
    return {"success": result, "message": "测评任务已删除"}


@router.post(
    "/tasks/{task_id}/cancel",
    response_model=EvaluationTaskCancelResponse,
    summary="取消测评任务",
    description="取消正在执行或等待执行的测评任务",
)
async def cancel_evaluation_task(
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    kb_id: Annotated[int, Path(gt=0, description="知识库ID")],
    task_id: Annotated[int, Path(gt=0, description="任务ID")],
    user_id: int = Depends(get_current_user_id),
    member: SpaceMember = Depends(validate_space_editor),
    evaluation_service: EvaluationService = Depends(get_evaluation_service),
    db: AsyncSession = Depends(get_db),
):
    await validate_kb_access(kb_id, space_id, db)
    task = await evaluation_service.get_task_by_kb(task_id, space_id, kb_id)
    if not task:
        raise EvaluationTaskNotFoundError(task_id)
    _check_task_owner(task, member)
    task = await evaluation_service.cancel_task(task_id)
    return EvaluationTaskCancelResponse(
        task_id=task.id,
        status=EvaluationStatus(task.status).name.lower(),
    )


@router.get(
    "/tasks/{task_id}/progress",
    response_model=EvaluationTaskProgressResponse,
    summary="获取任务进度",
)
async def get_task_progress(
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    kb_id: Annotated[int, Path(gt=0, description="知识库ID")],
    task_id: Annotated[int, Path(gt=0, description="任务ID")],
    member: SpaceMember = Depends(validate_space_member),
    evaluation_service: EvaluationService = Depends(get_evaluation_service),
    db: AsyncSession = Depends(get_db),
):
    await validate_kb_access(kb_id, space_id, db)
    task = await evaluation_service.get_task_by_kb(task_id, space_id, kb_id)
    if not task:
        raise EvaluationTaskNotFoundError(task_id)
    _check_task_owner(task, member)
    progress = await evaluation_service.get_task_progress(task_id)
    return EvaluationTaskProgressResponse(**progress)


@router.post(
    "/tasks/{task_id}/scores",
    response_model=HumanScoreResponse,
    summary="提交人工评分",
)
async def submit_human_scores(
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    kb_id: Annotated[int, Path(gt=0, description="知识库ID")],
    task_id: Annotated[int, Path(gt=0, description="任务ID")],
    body: HumanScoreRequest,
    user_id: int = Depends(get_current_user_id),
    member: SpaceMember = Depends(validate_space_member),
    evaluation_service: EvaluationService = Depends(get_evaluation_service),
    db: AsyncSession = Depends(get_db),
):
    await validate_kb_access(kb_id, space_id, db)
    task = await evaluation_service.get_task_by_kb(task_id, space_id, kb_id)
    if not task:
        raise EvaluationTaskNotFoundError(task_id)
    _check_task_owner(task, member)

    updated = await evaluation_service.submit_human_scores(
        task_id=task_id,
        scores=[s.model_dump() for s in body.scores],
    )
    return HumanScoreResponse(updated_count=updated)


@router.get(
    "/tasks/{task_id}/report",
    response_model=EvaluationReportResponse,
    summary="获取测评报告",
)
async def get_evaluation_report(
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    kb_id: Annotated[int, Path(gt=0, description="知识库ID")],
    task_id: Annotated[int, Path(gt=0, description="任务ID")],
    member: SpaceMember = Depends(validate_space_member),
    evaluation_service: EvaluationService = Depends(get_evaluation_service),
    db: AsyncSession = Depends(get_db),
):
    await validate_kb_access(kb_id, space_id, db)
    # 先校验任务归属（作者或空间管理员），再取报告
    task = await evaluation_service.get_task_by_kb(task_id, space_id, kb_id)
    if not task:
        raise EvaluationTaskNotFoundError(task_id)
    _check_task_owner(task, member)
    report = await evaluation_service.get_report(task_id)
    if not report:
        raise EvaluationTaskNotFoundError(task_id)
    return EvaluationReportResponse(**report)


@router.get(
    "/tasks/{task_id}/export",
    summary="导出测评结果",
    description="导出测评结果（JSON 或 CSV 格式）",
)
async def export_evaluation_result(
    space_id: Annotated[int, Path(gt=0, description="空间ID")],
    kb_id: Annotated[int, Path(gt=0, description="知识库ID")],
    task_id: Annotated[int, Path(gt=0, description="任务ID")],
    format: Annotated[Literal["json", "csv"], Query(description="导出格式: json / csv")] = "json",
    member: SpaceMember = Depends(validate_space_member),
    evaluation_service: EvaluationService = Depends(get_evaluation_service),
    db: AsyncSession = Depends(get_db),
):
    await validate_kb_access(kb_id, space_id, db)

    task = await evaluation_service.get_task_by_kb(task_id, space_id, kb_id)
    if not task:
        raise EvaluationTaskNotFoundError(task_id)
    _check_task_owner(task, member)

    if task.status == EvaluationStatus.PENDING or task.status == EvaluationStatus.RUNNING:
        raise EvaluationTaskPendingError(task_id)

    if task.status == EvaluationStatus.FAILED:
        raise EvaluationTaskNotCompletedError(task_id, "failed")

    if task.status == EvaluationStatus.CANCELLED:
        raise EvaluationTaskNotCompletedError(task_id, "cancelled")

    result = await evaluation_service.export_result(task_id, format=format)
    if not result:
        return {"message": "暂无结果"}

    file_bytes, filename = result

    content_type = "text/csv" if format == "csv" else "application/json"
    encoded_filename = quote(filename)
    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
    }

    return StreamingResponse(
        io.BytesIO(file_bytes),
        media_type=content_type,
        headers=headers,
    )
