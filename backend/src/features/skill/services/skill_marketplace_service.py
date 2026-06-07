"""
技能广场服务 — 上传、发布、安装、评价、搜索
"""
import asyncio
import io
import json
import zipfile
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.middleware.structured_logging import get_logger
from src.features.skill.models.skill import (
    SkillDefinition, SkillVersion, SkillReview, SkillInstallation,
    SkillSource, SkillVisibility, SkillStatus, ReviewStatus,
)
from src.features.skill.exceptions import (
    SkillNotFoundError,
    SkillAlreadyExistsError,
    SkillNotPublishedError,
    SkillAccessDeniedError,
    SkillAlreadyInstalledError,
    SkillNotInstalledError,
    InvalidSkillFormatError,
    SkillReviewRejectedError,
)
from src.features.skill.repository.skill_repository import (
    SkillRepository, SkillVersionRepository, SkillReviewRepository, SkillInstallationRepository,
)
from src.features.skill.services.skill_parser import extract_skill_zip, validate_skill_md, ExtractedSkill
from src.features.skill.services.skill_checker import SkillSecurityChecker
from src.shared.utils.time_utils import now_china
from src.shared.prompts import PromptManager, PromptTemplate
from src.shared.ai_models.base_model import BaseLLM

logger = get_logger(__name__)


class SkillMarketplaceService:
    """技能广场服务"""

    def __init__(
        self,
        db: AsyncSession,
        minio_client=None,
        security_checker: Optional[SkillSecurityChecker] = None,
        model_config_service: Optional[Any] = None,
    ):
        self.db = db
        self.minio = minio_client
        self.checker = security_checker or SkillSecurityChecker()
        self.model_config_service = model_config_service
        self.skill_repo = SkillRepository(db)
        self.version_repo = SkillVersionRepository(db)
        self.review_repo = SkillReviewRepository(db)
        self.install_repo = SkillInstallationRepository(db)

    async def cleanup(self):
        pass

    # ==================== 上传 ====================

    async def upload_skill(self, user_id: int, zip_bytes: bytes) -> SkillDefinition:
        """
        上传技能 ZIP 包

        流程：解压 → 解析 SKILL.md → 存 MinIO → 写 DB（PENDING）→ 后台异步审查
        """
        # 1. 解压解析
        try:
            extracted = extract_skill_zip(zip_bytes)
        except ValueError as e:
            raise InvalidSkillFormatError(str(e))

        parsed = extracted.parsed

        # 2. 检查名称冲突
        existing = await self.skill_repo.get_by_name(user_id, parsed.name)
        if existing:
            raise SkillAlreadyExistsError(parsed.name)

        # 2b. 清理同名的软删除记录，释放唯一约束
        await self.skill_repo.hard_delete_by_name(user_id, parsed.name)

        # 3. 创建 DB 记录（状态为 PENDING，等待后台审查）
        skill = await self.skill_repo.create(
            user_id=user_id,
            name=parsed.name,
            display_name=parsed.display_name,
            description=parsed.description,
            license=parsed.license,
            allowed_tools=parsed.allowed_tools,
            frontmatter_raw=parsed.frontmatter_raw,
            body_markdown=parsed.body_markdown,
            category=parsed.category,
            tags=parsed.tags,
            version=1,
            skill_source=SkillSource.CUSTOM,
            visibility=SkillVisibility.PRIVATE,
            status=SkillStatus.DRAFT,
            review_status=ReviewStatus.PENDING,
            review_result=None,
        )

        # 4. 上传文件到 MinIO
        resource_manifest = await self._upload_skill_files(
            skill.id, 1, extracted,
        )

        # 5. 创建版本记录
        await self.version_repo.create(
            skill_id=skill.id,
            version=1,
            frontmatter_raw=parsed.frontmatter_raw,
            body_markdown=parsed.body_markdown,
            allowed_tools=parsed.allowed_tools,
            resource_manifest=resource_manifest,
            version_note="初始版本",
        )

        await self.db.commit()
        logger.info("技能上传成功，等待后台审查", skill_id=skill.id, name=parsed.name)

        # 6. 后台异步审查
        self._start_background_review(skill.id, parsed.body_markdown, parsed.frontmatter_raw)

        return skill

    async def update_skill_version(
        self, user_id: int, skill_id: int, zip_bytes: bytes,
    ) -> SkillDefinition:
        """上传新版本 ZIP 更新已有技能"""
        skill = await self.skill_repo.get_by_id(skill_id)
        if not skill:
            raise SkillNotFoundError(skill_id)
        if skill.user_id != user_id:
            raise SkillAccessDeniedError(skill_id)

        # 解压解析
        try:
            extracted = extract_skill_zip(zip_bytes)
        except ValueError as e:
            raise InvalidSkillFormatError(str(e))

        parsed = extracted.parsed

        # 校验 name 一致性
        if parsed.name != skill.name:
            raise InvalidSkillFormatError(f"ZIP 中的 name '{parsed.name}' 与技能 '{skill.name}' 不一致")

        new_version = skill.version + 1

        # 上传文件到 MinIO
        resource_manifest = await self._upload_skill_files(
            skill.id, new_version, extracted,
        )

        # 更新主记录（重置为 PENDING，等待后台审查）
        await self.skill_repo.update(
            skill_id,
            display_name=parsed.display_name,
            description=parsed.description,
            license=parsed.license,
            allowed_tools=parsed.allowed_tools,
            frontmatter_raw=parsed.frontmatter_raw,
            body_markdown=parsed.body_markdown,
            category=parsed.category,
            tags=parsed.tags,
            version=new_version,
            review_status=ReviewStatus.PENDING,
            review_result=None,
            reviewed_at=None,
            # 已发布状态下更新版本后变回 DRAFT
            **({"status": SkillStatus.DRAFT} if skill.status == SkillStatus.PUBLISHED else {}),
        )

        # 创建版本记录
        await self.version_repo.create(
            skill_id=skill_id,
            version=new_version,
            frontmatter_raw=parsed.frontmatter_raw,
            body_markdown=parsed.body_markdown,
            allowed_tools=parsed.allowed_tools,
            resource_manifest=resource_manifest,
        )

        await self.db.commit()
        logger.info("技能版本更新成功，等待后台审查", skill_id=skill_id, version=new_version)

        # 后台异步审查
        self._start_background_review(skill_id, parsed.body_markdown, parsed.frontmatter_raw)

        return await self.skill_repo.get_by_id(skill_id)

    # ==================== 发布/取消 ====================

    async def publish_skill(self, user_id: int, skill_id: int) -> SkillDefinition:
        """发布技能"""
        skill = await self.skill_repo.get_by_id(skill_id)
        if not skill:
            raise SkillNotFoundError(skill_id)
        if skill.user_id != user_id:
            raise SkillAccessDeniedError(skill_id)
        if skill.review_status == ReviewStatus.REJECTED:
            raise SkillReviewRejectedError("安全审查未通过，请修改后重新上传")
        if skill.review_status == ReviewStatus.SUSPICIOUS:
            raise SkillReviewRejectedError("技能待人工审核，请等待管理员审核")
        if skill.review_status == ReviewStatus.PENDING:
            raise SkillReviewRejectedError("技能正在安全审查中，请等待审核完成后再发布")

        skill = await self.skill_repo.update(
            skill_id,
            status=SkillStatus.PUBLISHED,
            visibility=SkillVisibility.PUBLIC,
        )
        await self.db.commit()
        return skill

    async def unpublish_skill(self, user_id: int, skill_id: int) -> SkillDefinition:
        """取消发布"""
        skill = await self.skill_repo.get_by_id(skill_id)
        if not skill:
            raise SkillNotFoundError(skill_id)
        if skill.user_id != user_id:
            raise SkillAccessDeniedError(skill_id)

        skill = await self.skill_repo.update(
            skill_id,
            status=SkillStatus.DRAFT,
            visibility=SkillVisibility.PRIVATE,
        )
        await self.db.commit()
        return skill

    # ==================== 安装/卸载 ====================

    async def install_skill(
        self, user_id: int, skill_id: int, agent_id: int,
        agent_repository=None,
    ) -> SkillInstallation:
        """安装技能到 Agent"""
        skill = await self.skill_repo.get_by_id(skill_id)
        if not skill:
            raise SkillNotFoundError(skill_id)
        if skill.status != SkillStatus.PUBLISHED and skill.skill_source != SkillSource.BUILTIN:
            raise SkillNotPublishedError(skill_id)

        # 校验 Agent 归属
        if agent_repository:
            agent = await agent_repository.get_by_id(agent_id)
            if not agent:
                from src.features.agent.api.exceptions import AgentNotFoundError
                raise AgentNotFoundError(agent_id)
            if agent.user_id is not None and agent.user_id != user_id:
                raise SkillAccessDeniedError(skill_id)

        # 检查是否已安装
        existing = await self.install_repo.get_by_skill_and_agent(skill_id, agent_id)
        if existing:
            raise SkillAlreadyInstalledError(skill_id, agent_id)

        # 创建安装记录
        installation = await self.install_repo.create(
            skill_id=skill_id,
            agent_id=agent_id,
            user_id=user_id,
        )

        # 更新安装计数
        await self.skill_repo.increment_install_count(skill_id)

        # 更新 Agent 的 enabled_tools（如果有 agent_repository）
        if agent_repository:
            agent = await agent_repository.get_by_id(agent_id)
            if agent:
                enabled = list(agent.enabled_tools or [])
                skill_ref = f"skill__{skill.id}_{skill.name}"
                if skill_ref not in enabled:
                    enabled.append(skill_ref)
                # 追加技能引用的工具
                if skill.allowed_tools:
                    for tool_name in skill.allowed_tools:
                        if tool_name not in enabled:
                            enabled.append(tool_name)
                await agent_repository.update(agent_id, enabled_tools=enabled)

        await self.db.commit()
        return installation

    async def uninstall_skill(
        self, user_id: int, skill_id: int, agent_id: int,
        agent_repository=None,
    ) -> bool:
        """从 Agent 卸载技能"""
        existing = await self.install_repo.get_by_skill_and_agent(skill_id, agent_id)
        if not existing:
            raise SkillNotInstalledError(skill_id, agent_id)

        deleted = await self.install_repo.delete_installation(skill_id, agent_id)
        if deleted:
            await self.skill_repo.decrement_install_count(skill_id)

            # 更新 Agent 的 enabled_tools
            if agent_repository:
                agent = await agent_repository.get_by_id(agent_id)
                if agent:
                    skill = await self.skill_repo.get_by_id(skill_id)
                    enabled = list(agent.enabled_tools or [])
                    skill_ref = f"skill__{skill_id}_{skill.name}" if skill else f"skill__{skill_id}"
                    enabled = [s for s in enabled if s != skill_ref]
                    # 清理安装时追加的 allowed_tools，仅移除当前技能对应且不属于其他已安装技能的工具
                    if skill and skill.allowed_tools:
                        other_skills = await self.install_repo.list_by_agent(agent_id)
                        other_tool_refs = set()
                        for install in other_skills:
                            if install.skill_id != skill_id:
                                skill_def = await self.skill_repo.get_by_id(install.skill_id)
                                if skill_def and skill_def.allowed_tools:
                                    for tool in skill_def.allowed_tools:
                                        other_tool_refs.add(tool)
                        # 仅移除不属于其他已安装技能的工具
                        enabled = [s for s in enabled if s in other_tool_refs or s not in skill.allowed_tools]
                    await agent_repository.update(agent_id, enabled_tools=enabled)

        await self.db.commit()
        return deleted

    # ==================== 查询 ====================

    async def get_skill(self, skill_id: int, user_id: int = None) -> Optional[SkillDefinition]:
        skill = await self.skill_repo.get_by_id(skill_id)
        if not skill:
            return None
        # 私有技能仅所有者可查看
        if skill.visibility == SkillVisibility.PRIVATE and user_id is not None and skill.user_id != user_id:
            return None
        return skill

    async def list_my_skills(
        self, user_id: int, status: Optional[int] = None,
        limit: int = 20, offset: int = 0,
    ) -> Tuple[List[SkillDefinition], int]:
        return await self.skill_repo.list_by_user(user_id, status, limit, offset)

    async def list_marketplace(
        self, keyword: Optional[str] = None, category: Optional[str] = None,
        tags: Optional[str] = None, sort: str = "newest",
        limit: int = 20, offset: int = 0,
    ) -> Tuple[List[SkillDefinition], int]:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
        return await self.skill_repo.list_marketplace(keyword, category, tag_list, sort, limit, offset)

    async def list_categories(self) -> List[str]:
        """获取所有已上架技能的去重分类列表"""
        return await self.skill_repo.get_distinct_categories()

    async def list_tags(self) -> List[str]:
        """获取所有已上架技能的常用标签列表"""
        return await self.skill_repo.get_common_tags()

    async def ai_search(
        self, query: str, user_id: int, limit: int = 20, offset: int = 0,
    ) -> Dict[str, Any]:
        """AI 智能搜索：LLM 理解自然语言意图 → 结构化参数搜索"""
        llm_client = await self._get_llm_client(user_id)
        if not llm_client:
            return await self._fallback_ai_search(
                query, limit, offset,
                "AI 搜索功能不可用，已自动使用关键词搜索",
            )

        # 获取可用分类作为 prompt 上下文
        categories = await self.skill_repo.get_distinct_categories()

        # 格式化 prompt
        prompt = PromptManager.format_prompt(
            PromptTemplate.SKILL_AI_SEARCH.value,
            query=query,
            categories=", ".join(categories) if categories else "暂无分类",
        )

        # 调用 LLM 解析意图
        try:
            response = await asyncio.wait_for(
                llm_client.generate_text(
                    prompt=prompt,
                    max_tokens=512,
                    temperature=0.1,
                    response_format={"type": "json_object"},
                ),
                timeout=15,
            )
            parsed = json.loads(response)
        except (json.JSONDecodeError, asyncio.TimeoutError, Exception) as e:
            logger.warning("AI 搜索 LLM 解析失败，降级为关键词搜索", error=str(e))
            return await self._fallback_ai_search(
                query, limit, offset,
                f"AI 解析失败，已自动使用关键词搜索: {query}",
            )

        # 映射 LLM 输出到搜索参数
        keywords_raw = parsed.get("keywords") or [query]
        keywords = " ".join(keywords_raw) if isinstance(keywords_raw, list) else query
        category = parsed.get("category") or None
        tags_raw = parsed.get("tags") or None
        sort = parsed.get("sort", "newest")
        intent_summary = parsed.get("intent_summary", "")

        # 校验 sort
        valid_sorts = {"newest", "popular", "rating", "name"}
        if sort not in valid_sorts:
            sort = "newest"

        # 处理 tags
        tag_list = None
        if tags_raw and isinstance(tags_raw, list):
            tag_list = [t.strip() for t in tags_raw if t.strip()]

        # 执行搜索
        skills, total = await self.skill_repo.list_marketplace(
            keyword=keywords,
            category=category if category and category != "null" else None,
            tags=tag_list,
            sort=sort,
            limit=limit,
            offset=offset,
        )

        # 构建解释
        explanation = intent_summary or f"根据您的查询，已搜索匹配以下关键词的技能: {keywords}"
        filters = []
        if category:
            filters.append(f"分类: {category}")
        if tag_list:
            filters.append(f"标签: {', '.join(tag_list)}")
        if filters:
            explanation += f"（筛选条件: {'; '.join(filters)}）"

        return {
            "items": skills,
            "total": total,
            "limit": limit,
            "offset": offset,
            "explanation": explanation,
            "ai_query": {
                "keywords": keywords_raw if isinstance(keywords_raw, list) else [query],
                "category": category,
                "tags": tag_list,
                "sort": sort,
                "intent_summary": intent_summary,
            },
        }

    async def _fallback_ai_search(
        self, query: str, limit: int, offset: int, explanation: str,
    ) -> Dict[str, Any]:
        """AI 搜索降级：使用关键词搜索"""
        skills, total = await self.skill_repo.list_marketplace(
            keyword=query, limit=limit, offset=offset,
        )
        return {
            "items": skills,
            "total": total,
            "limit": limit,
            "offset": offset,
            "explanation": explanation,
            "ai_query": {
                "keywords": [query],
                "category": None,
                "tags": None,
                "sort": "newest",
                "intent_summary": "",
            },
        }

    async def list_installed(self, agent_id: int) -> List[SkillInstallation]:
        return await self.install_repo.list_by_agent(agent_id)

    # ==================== 评价 ====================

    async def create_review(
        self, user_id: int, skill_id: int, rating: int, content: Optional[str],
    ) -> SkillReview:
        skill = await self.skill_repo.get_by_id(skill_id)
        if not skill:
            raise SkillNotFoundError(skill_id)

        review = await self.review_repo.create_or_update(skill_id, user_id, rating, content)

        # 更新评分统计
        avg, count = await self.review_repo.get_rating_stats(skill_id)
        await self.skill_repo.update(skill_id, rating_avg=round(avg, 2), rating_count=count)

        await self.db.commit()
        return review

    async def list_reviews(
        self, skill_id: int, limit: int = 20, offset: int = 0,
    ) -> Tuple[List[SkillReview], int]:
        return await self.review_repo.list_by_skill(skill_id, limit, offset)

    async def delete_review(self, user_id: int, skill_id: int) -> bool:
        deleted = await self.review_repo.delete_review(user_id, skill_id)
        if deleted:
            avg, count = await self.review_repo.get_rating_stats(skill_id)
            await self.skill_repo.update(skill_id, rating_avg=round(avg, 2), rating_count=count)
        await self.db.commit()
        return deleted

    # ==================== 删除 ====================

    async def delete_skill(self, user_id: int, skill_id: int) -> bool:
        skill = await self.skill_repo.get_by_id(skill_id)
        if not skill:
            raise SkillNotFoundError(skill_id)
        if skill.user_id != user_id:
            raise SkillAccessDeniedError(skill_id)
        result = await self.skill_repo.soft_delete(skill_id)
        await self.db.commit()
        return result

    # ==================== 管理员审核 ====================

    async def list_pending_review(
        self, limit: int = 20, offset: int = 0,
    ) -> Tuple[List[SkillDefinition], int]:
        """列出待人工审核的技能（SUSPICIOUS 状态）"""
        return await self.skill_repo.list_by_review_status(
            ReviewStatus.SUSPICIOUS, limit, offset,
        )

    async def approve_skill(self, skill_id: int) -> SkillDefinition:
        """管理员批准技能（SUSPICIOUS → APPROVED）"""
        skill = await self.skill_repo.get_by_id(skill_id)
        if not skill:
            raise SkillNotFoundError(skill_id)
        updated = await self.skill_repo.update(
            skill_id,
            review_status=ReviewStatus.APPROVED,
            reviewed_at=now_china(),
        )
        await self.db.commit()
        return updated

    async def reject_skill(self, skill_id: int, reason: Optional[str] = None) -> SkillDefinition:
        """管理员拒绝技能（SUSPICIOUS → REJECTED）"""
        skill = await self.skill_repo.get_by_id(skill_id)
        if not skill:
            raise SkillNotFoundError(skill_id)
        update_kwargs = {
            "review_status": ReviewStatus.REJECTED,
            "reviewed_at": now_china(),
        }
        if reason and skill.review_result:
            result = dict(skill.review_result)
            result["admin_reason"] = reason
            update_kwargs["review_result"] = result
        updated = await self.skill_repo.update(skill_id, **update_kwargs)
        await self.db.commit()
        return updated

    # ==================== 下载 ====================

    async def download_skill(self, skill_id: int) -> bytes:
        """从 MinIO 打包技能为 ZIP 供下载"""
        skill = await self.skill_repo.get_by_id(skill_id)
        if not skill:
            raise SkillNotFoundError(skill_id)

        # 获取版本信息
        version = await self.version_repo.get_version(skill_id, skill.version)

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            # 写入 SKILL.md
            skill_md_content = f"---\n{skill.frontmatter_raw}\n---\n\n{skill.body_markdown}"
            zf.writestr("SKILL.md", skill_md_content)

            # 从 MinIO 下载资源文件
            if version and version.resource_manifest and self.minio:
                for res_info in version.resource_manifest:
                    path = res_info.get("path", "")
                    if not path:
                        continue
                    # 优先使用 storage_key，否则拼装路径
                    object_name = res_info.get("storage_key") or f"skills/{skill_id}/v{skill.version}/{path}"
                    try:
                        data = await self._download_minio_file(object_name)
                        zf.writestr(path, data)
                    except Exception as e:
                        logger.error("下载资源文件失败，ZIP将不完整", path=path, error=str(e))

        return buf.getvalue()

    # ==================== 内部方法 ====================

    async def _get_llm_client(self, user_id: int, model_name: Optional[str] = None) -> Optional[BaseLLM]:
        """获取用户的 LLM 客户端（用于 AI 搜索）

        优先使用指定模型，否则使用用户默认模型
        """
        if not self.model_config_service:
            return None
        if not model_name:
            try:
                model_name = await self.model_config_service.get_user_default_model_name(user_id, "llm")
            except Exception:
                model_name = None
        if not model_name:
            return None
        try:
            return await self.model_config_service.get_llm_client_by_model(user_id, model_name)
        except Exception as e:
            logger.warning("获取 LLM 客户端失败", error=str(e))
            return None

    def _start_background_review(self, skill_id: int, body_markdown: str, frontmatter_raw: str) -> None:
        """启动后台异步审查任务（使用独立的数据库会话）"""
        async def _do_review():
            from src.core.database.database import get_session_factory
            session_factory = get_session_factory()
            async with session_factory() as db:
                try:
                    review_result = await self.checker.check(body_markdown, frontmatter_raw)
                    review_data = {
                        "rules": {
                            "passed": review_result.rule_result.passed if review_result.rule_result else True,
                            "matches": review_result.rule_result.matches if review_result.rule_result else [],
                        },
                        "llm": {
                            "level": review_result.llm_result.level if review_result.llm_result else None,
                            "reason": review_result.llm_result.reason if review_result.llm_result else None,
                        },
                    }
                    repo = SkillRepository(db)
                    await repo.update(
                        skill_id,
                        review_status=review_result.status,
                        review_result=review_data,
                        reviewed_at=now_china(),
                    )
                    await db.commit()
                    logger.info("技能后台审查完成", skill_id=skill_id, review_status=review_result.status)
                except Exception as e:
                    logger.error("技能后台审查失败", skill_id=skill_id, error=str(e))

        task = asyncio.ensure_future(_do_review())
        task.add_done_callback(lambda t: t.exception() if not t.cancelled() and t.exception() else None)

    async def _upload_skill_files(
        self, skill_id: int, version: int, extracted: ExtractedSkill,
    ) -> List[dict]:
        """上传技能文件到 MinIO，返回 resource_manifest"""
        manifest = []
        prefix = f"skills/{skill_id}/v{version}"

        # SKILL.md 的 manifest 条目
        manifest.append({
            "path": "SKILL.md",
            "type": "skill_md",
            "size": len(extracted.skill_md_content.encode("utf-8")),
            "storage_key": f"{prefix}/SKILL.md",
        })

        if not self.minio:
            # MinIO 不可用时只记录文件信息
            for res in extracted.resources:
                manifest.append({"path": res.path, "type": res.type, "size": res.size, "storage_key": f"{prefix}/{res.path}"})
            return manifest

        bucket = self.minio.default_bucket
        await self.minio.ensure_bucket_exists(bucket)

        # 上传 SKILL.md 原文件
        skill_md_bytes = extracted.skill_md_content.encode("utf-8")
        await self._upload_minio_file(
            bucket, f"{prefix}/SKILL.md",
            skill_md_bytes, "text/markdown",
        )

        # 上传资源文件
        for res in extracted.resources:
            object_name = f"{prefix}/{res.path}"
            await self._upload_minio_file(bucket, object_name, res.content)
            manifest.append({"path": res.path, "type": res.type, "size": res.size, "storage_key": object_name})

        return manifest

    async def _upload_minio_file(
        self, bucket: str, object_name: str, data: bytes,
        content_type: str = "application/octet-stream",
    ):
        """上传单个文件到 MinIO"""
        await asyncio.to_thread(
            self.minio.client.put_object,
            bucket,
            object_name,
            io.BytesIO(data),
            len(data),
            content_type=content_type,
        )

    async def _download_minio_file(self, object_name: str) -> bytes:
        """从 MinIO 下载单个文件"""
        bucket = self.minio.default_bucket
        response = await asyncio.to_thread(
            self.minio.client.get_object, bucket, object_name,
        )
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()
