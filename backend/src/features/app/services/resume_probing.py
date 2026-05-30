"""
S10-S11: 自动追问引擎

LLM 自问自答，模拟面试官和候选人的多轮追问。
广度：每个知识点独立提问（可并行）。
深度：逐轮追问，每轮基于上一轮的回答深入挖掘。

重试与降级策略：
- 每次LLM调用：指数退避重试3次（2s → 4s → 8s）
- 重试耗尽后：降级到系统模型，遍历所有系统模型（每个重试1次）
"""
import asyncio
import json
from typing import Optional

from src.core.middleware.structured_logging import get_logger
from src.shared.ai_models.llm import BaseLLM
from src.shared.prompts import PromptTemplate, PromptManager
from src.features.app.schemas.resume_schema import (
    StructuredResume, ProbingPlan, KnowledgePoint, JDAnalysis,
)
from src.features.app.services.resume_parser import _extract_json

logger = get_logger(__name__)

# ==================== 常量 ====================

MAX_RETRIES = 3              # 主模型最大重试次数
RETRY_BASE_DELAY = 2         # 指数退避基础延迟（秒）
FALLBACK_MAX_RETRIES = 1     # 降级模型每个最多重试次数


class AutoProbingEngine:
    """自动化追问引擎 — LLM 自问自答，带重试与降级"""

    def __init__(
        self,
        llm_client: BaseLLM,
        user_id: int = 0,
        bg_db=None,
        max_concurrent: int = 3,
    ):
        self.llm = llm_client
        self.user_id = user_id
        self.bg_db = bg_db
        self._semaphore = asyncio.Semaphore(max_concurrent)
        # 降级模型缓存：{model_name: BaseLLM}
        self._fallback_clients: dict[str, BaseLLM] = {}
        self._fallback_models_loaded = False

    async def _load_fallback_models(self):
        """从数据库加载系统可用模型列表，排除当前主模型"""
        if self._fallback_models_loaded or not self.bg_db:
            return

        self._fallback_models_loaded = True
        try:
            from src.features.user.services.model_config_service import ModelConfigService
            svc = ModelConfigService(self.bg_db)
            configs = await svc.repo.list_system_configs("llm")
            current_model = getattr(self.llm, 'model', '')

            for cfg in configs:
                if cfg.model == current_model:
                    continue
                try:
                    client = await svc.get_llm_client_by_model(self.user_id, cfg.model)
                    self._fallback_clients[cfg.model] = client
                    logger.info("降级模型已加载", fallback_model=cfg.model)
                except Exception as e:
                    logger.warning("降级模型加载失败", model=cfg.model, error=str(e))
        except Exception as e:
            logger.warning("加载降级模型列表失败", error=str(e))

    async def _call_llm_with_retry(self, prompt: str, max_tokens: int | None = None, **kwargs) -> str:
        """
        带重试和降级的 LLM 调用。

        策略：
        1. 主模型指数退避重试 MAX_RETRIES 次
        2. 主模型耗尽后，遍历系统降级模型（每个重试 FALLBACK_MAX_RETRIES 次）
        """
        generate_kwargs = {**kwargs}
        if max_tokens is not None:
            generate_kwargs["max_tokens"] = max_tokens

        # --- 阶段1：主模型重试 ---
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                return await self.llm.generate_text(
                    prompt=prompt, **generate_kwargs,
                )
            except Exception as e:
                if attempt < MAX_RETRIES:
                    delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
                    logger.warning(
                        "主模型调用失败，退避重试",
                        model=getattr(self.llm, 'model', 'unknown'),
                        attempt=f"{attempt}/{MAX_RETRIES}",
                        delay_s=delay,
                        error=str(e)[:200],
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        "主模型重试耗尽，准备降级",
                        model=getattr(self.llm, 'model', 'unknown'),
                        attempts=MAX_RETRIES,
                        error=str(e)[:200],
                    )

        # --- 阶段2：降级到系统模型 ---
        await self._load_fallback_models()

        for model_name, client in self._fallback_clients.items():
            for attempt in range(1, FALLBACK_MAX_RETRIES + 1):
                try:
                    result = await client.generate_text(
                        prompt=prompt, **generate_kwargs,
                    )
                    logger.info("降级模型调用成功", fallback_model=model_name)
                    return result
                except Exception as e:
                    if attempt < FALLBACK_MAX_RETRIES:
                        delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
                        logger.warning(
                            "降级模型调用失败，重试",
                            fallback_model=model_name,
                            attempt=f"{attempt}/{FALLBACK_MAX_RETRIES}",
                            delay_s=delay,
                            error=str(e)[:200],
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.warning(
                            "降级模型重试耗尽",
                            fallback_model=model_name,
                            error=str(e)[:200],
                        )

        # 所有模型都失败
        raise RuntimeError(f"所有模型均不可用（主模型 + {len(self._fallback_clients)} 个降级模型）")

    async def probe_all(
        self,
        resume_session_id: str,
        structured_resume: StructuredResume,
        probing_plan: ProbingPlan,
        jd_analysis: Optional[JDAnalysis],
        bg_db=None,
    ) -> list[dict]:
        """对所有 KP 并行执行自问自答"""
        kps = sorted(probing_plan.knowledge_points, key=lambda k: k.probing_weight, reverse=True)

        resume_summary = structured_resume.resume_summary or self._make_resume_summary(structured_resume)

        async def _probe_one(kp: KnowledgePoint) -> dict:
            async with self._semaphore:
                return await self._probe_kp(kp, resume_summary, jd_analysis)

        tasks = [_probe_one(kp) for kp in kps]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        records = []
        for kp, result in zip(kps, results):
            if isinstance(result, Exception):
                logger.error("知识点追问失败", kp_id=kp.id, kp_name=kp.name, error=str(result))
                records.append({
                    "kp_id": kp.id, "kp_name": kp.name,
                    "module": kp.module, "source": kp.source,
                    "qa_pairs": [], "status": "failed", "error": str(result),
                })
            else:
                records.append(result)

        return records

    async def _probe_kp(
        self,
        kp: KnowledgePoint,
        resume_summary: str,
        jd_analysis: Optional[JDAnalysis],
    ) -> dict:
        """单个 KP：逐轮追问，每轮基于上一轮回答深入挖掘"""
        # 构建预设问题链段落
        probing_chain_section = ""
        if kp.probing_chain:
            chain_lines = "\n".join(f"  - {q}" for q in kp.probing_chain[:5])
            probing_chain_section = f"- 预设问题链:\n{chain_lines}"

        # 构建 JD 上下文
        jd_context_section = ""
        if jd_analysis:
            relevant_skills = [
                s for s in jd_analysis.required_skills + jd_analysis.preferred_skills
                if s.name.lower() in kp.name.lower() or kp.name.lower() in s.name.lower()
            ]
            if relevant_skills:
                jd_context_section = "- JD 相关要求:\n" + "\n".join(
                    f"  - {s.name} ({s.importance}): {s.context}" for s in relevant_skills
                )

        depth = kp.allocated_rounds
        qa_pairs = []

        try:
            # 第一轮：基于知识点和简历背景提出初始问题
            first_prompt = PromptManager.format_prompt(
                PromptTemplate.RESUME_PROBE_FIRST_ROUND.value,
                kp_name=kp.name,
                kp_category=kp.category,
                kp_source=kp.source,
                kp_context=kp.context or "（无具体上下文）",
                resume_summary=resume_summary,
                probing_chain_section=probing_chain_section,
                jd_context_section=jd_context_section,
            )
            response = await self._call_llm_with_retry(
                prompt=first_prompt,
                temperature=0.7,
                response_format={"type": "json_object"},
            )
            first_data = json.loads(_extract_json(response))
            pair = {
                "round": 1,
                "question": first_data.get("question", ""),
                "answer": first_data.get("answer", ""),
                "quality_score": first_data.get("quality_score", 0.5),
            }
            qa_pairs.append(pair)

            # 后续轮：逐轮基于上一轮回答追问
            for round_num in range(2, depth + 1):
                prev = qa_pairs[-1]
                follow_prompt = PromptManager.format_prompt(
                    PromptTemplate.RESUME_PROBE_FOLLOW_UP.value,
                    kp_name=kp.name,
                    kp_category=kp.category,
                    prev_question=prev["question"],
                    prev_answer=prev["answer"],
                    prev_score=prev["quality_score"],
                )
                response = await self._call_llm_with_retry(
                    prompt=follow_prompt,
                    temperature=0.7,
                    response_format={"type": "json_object"},
                )
                follow_data = json.loads(_extract_json(response))
                pair = {
                    "round": round_num,
                    "question": follow_data.get("question", ""),
                    "answer": follow_data.get("answer", ""),
                    "quality_score": follow_data.get("quality_score", 0.5),
                }
                qa_pairs.append(pair)

            return {
                "kp_id": kp.id, "kp_name": kp.name,
                "module": kp.module, "source": kp.source,
                "qa_pairs": qa_pairs, "status": "completed",
            }
        except Exception as e:
            # 已有几轮成功的 Q&A 也保留
            logger.error("单 KP 追问失败（所有模型）", kp_id=kp.id, round=len(qa_pairs) + 1, error=str(e))
            return {
                "kp_id": kp.id, "kp_name": kp.name,
                "module": kp.module, "source": kp.source,
                "qa_pairs": qa_pairs, "status": "completed" if qa_pairs else "failed",
                "error": str(e) if not qa_pairs else None,
            }

    async def generate_evaluation(
        self,
        qa_records: list[dict],
        structured_resume: StructuredResume,
    ) -> str:
        """从所有 Q&A 生成面试准备建议（带重试降级）"""
        # 构建追问摘要
        qa_summary_parts = []
        for record in qa_records:
            if record.get("status") != "completed" or not record.get("qa_pairs"):
                continue
            qa_summary_parts.append(f"\n### {record['kp_name']}（{record['module']}）")
            for pair in record["qa_pairs"]:
                score = pair.get("quality_score", 0)
                qa_summary_parts.append(f"- Q{pair.get('round', '?')}: {pair.get('question', '')}")
                qa_summary_parts.append(f"  A: {pair.get('answer', '')}")
                qa_summary_parts.append(f"  评分: {score}")

        if not qa_summary_parts:
            return ""

        qa_summary = "\n".join(qa_summary_parts)

        prompt = PromptManager.format_prompt(
            PromptTemplate.RESUME_PROBE_EVALUATION.value,
            name=structured_resume.personal_info.name or "候选人",
            qa_summary=qa_summary,
        )

        try:
            response = await self._call_llm_with_retry(
                prompt=prompt,
                temperature=0.3,
            )
            return response.strip()
        except Exception as e:
            logger.error("面试准备建议生成失败（所有模型）", error=str(e))
            return ""

    def _make_resume_summary(self, resume: StructuredResume) -> str:
        """生成简历摘要供追问使用"""
        lines = [f"候选人: {resume.personal_info.name}"]
        if resume.personal_info.summary:
            lines.append(f"简介: {resume.personal_info.summary}")
        for w in resume.work_experience:
            lines.append(f"工作: {w.company} | {w.position} | {w.start_date}~{w.end_date}")
        for p in resume.project_experience:
            tech = ", ".join(p.tech_stack.languages + p.tech_stack.frameworks + p.tech_stack.middleware)
            lines.append(f"项目: {p.name} | 角色: {p.role} | 技术栈: {tech}")
            if p.background:
                lines.append(f"  背景: {p.background}")
            if p.challenges:
                for c in p.challenges:
                    lines.append(f"  挑战: {c.challenge} → {c.solution}")
            if p.achievements:
                for a in p.achievements:
                    lines.append(f"  成果: {a.description} {a.metric}")
        for paper in resume.publications.papers:
            lines.append(f"论文: {paper.title} | {paper.venue}")
        return "\n".join(lines)
