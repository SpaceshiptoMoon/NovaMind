"""
S10-S11: 自动追问引擎 (V2)

核心改动：
1. 前几轮固定策略（做法→原因→结果→困难），后续自由追问
2. 传入工作单元完整上下文（公司+岗位+行业+项目）
3. 新增 generate_resume_advice() 生成简历优化建议
4. 每轮追问必须引用上一轮回答

重试与降级策略不变：
- 主模型指数退避重试3次（2s → 4s → 8s）
- 重试耗尽后：降级到系统模型
"""
import asyncio
import json
from typing import Optional

from src.core.middleware.structured_logging import get_logger
from src.shared.ai_models.llm import BaseLLM
from src.shared.prompts import PromptTemplate, PromptManager
from src.features.app.schemas.resume_schema import (
    StructuredResume, ProbingPlan, KnowledgePoint, JDAnalysis,
    WorkProjectUnit,
)
from src.features.app.services.resume_parser import _extract_json

logger = get_logger(__name__)

# ==================== 常量 ====================

MAX_RETRIES = 3              # 主模型最大重试次数
RETRY_BASE_DELAY = 2         # 指数退避基础延迟（秒）
FALLBACK_MAX_RETRIES = 1     # 降级模型每个最多重试次数

# ==================== 追问轮次策略 ====================

ROUND_STRATEGIES = {
    1: "做法策略：追问候选人具体是怎么做的。围绕简历描述的项目方案、技术选型、架构设计、实现步骤提问。",
    2: "原因策略：追问候选人为什么这么做。围绕选型理由、方案对比、权衡考量、为什么不用其他方案提问。",
    3: "结果策略：追问实际结果如何。围绕量化指标、效果对比、度量方法、数据收集过程提问。",
    4: "困难策略：追问过程中遇到的困难和解决方案。围绕具体问题场景、排查思路、解决过程、复盘总结提问。",
}


class AutoProbingEngine:
    """自动化追问引擎 V2 — 固定策略 + 自由追问"""

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
        """带重试和降级的 LLM 调用"""
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

        # 构建工作单元索引
        work_unit_map = {u.id: u for u in (probing_plan.work_units or [])}

        async def _probe_one(kp: KnowledgePoint) -> dict:
            async with self._semaphore:
                work_unit = work_unit_map.get(kp.work_unit_id) if kp.work_unit_id else None
                return await self._probe_kp(kp, resume_summary, jd_analysis, work_unit)

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
        work_unit: Optional[WorkProjectUnit] = None,
    ) -> dict:
        """单个 KP：逐轮追问，前几轮固定策略，后续自由追问"""
        # 构建工作上下文段落
        work_context_section = ""
        if work_unit:
            context_parts = []
            if work_unit.company:
                context_parts.append(f"公司: {work_unit.company}")
            if work_unit.position:
                context_parts.append(f"岗位: {work_unit.position}")
            if work_unit.company_industry:
                context_parts.append(f"公司行业: {work_unit.company_industry}")
            if work_unit.position_context:
                context_parts.append(f"岗位定位: {work_unit.position_context}")
            if work_unit.industry_context:
                context_parts.append(f"行业关注点: {work_unit.industry_context}")
            if context_parts:
                work_context_section = "## 公司/岗位背景\n" + "\n".join(f"- {p}" for p in context_parts) + "\n"

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
            # 第一轮：固定策略 - 做法
            first_prompt = PromptManager.format_prompt(
                PromptTemplate.RESUME_PROBE_FIRST_ROUND.value,
                kp_name=kp.name,
                kp_category=kp.category,
                kp_source=kp.source,
                kp_context=kp.context or "（无具体上下文）",
                resume_summary=resume_summary,
                work_context_section=work_context_section,
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

            # 后续轮：按策略追问
            for round_num in range(2, depth + 1):
                prev = qa_pairs[-1]

                # 确定当前轮次的策略
                if round_num in ROUND_STRATEGIES:
                    round_strategy = ROUND_STRATEGIES[round_num]
                else:
                    round_strategy = (
                        "自由追问策略：从上一轮回答中找一个技术细节、模糊点或值得深入的方向继续追问。"
                        "可以深挖原理、方案替代、实际案例、边界条件等。"
                    )

                follow_prompt = PromptManager.format_prompt(
                    PromptTemplate.RESUME_PROBE_FOLLOW_UP.value,
                    kp_name=kp.name,
                    kp_category=kp.category,
                    prev_question=prev["question"],
                    prev_answer=prev["answer"],
                    prev_score=prev["quality_score"],
                    round_number=round_num,
                    round_strategy=round_strategy,
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
        """S11: 从所有 Q&A 生成面试准备建议（带重试降级）"""
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

    async def generate_resume_advice(
        self,
        qa_records: list[dict],
        structured_resume: StructuredResume,
    ) -> str:
        """S11-NEW: 从追问记录生成简历优化建议"""
        # 构建追问摘要，标记低分回答为薄弱点
        qa_summary_parts = []
        for record in qa_records:
            if record.get("status") != "completed" or not record.get("qa_pairs"):
                continue
            qa_summary_parts.append(f"\n### {record['kp_name']}（{record['module']}）")
            for pair in record["qa_pairs"]:
                score = pair.get("quality_score", 0)
                weakness_marker = " ⚠️ 回答薄弱" if score < 0.6 else ""
                qa_summary_parts.append(
                    f"- Q{pair.get('round', '?')}: {pair.get('question', '')}"
                    f"{weakness_marker} [评分: {score}]"
                )
                qa_summary_parts.append(f"  A: {pair.get('answer', '')[:300]}")

        if not qa_summary_parts:
            return ""

        qa_summary = "\n".join(qa_summary_parts)

        # 构建简历摘要
        resume_summary = self._make_resume_summary(structured_resume)

        prompt = PromptManager.format_prompt(
            PromptTemplate.RESUME_OPTIMIZATION_ADVICE.value,
            name=structured_resume.personal_info.name or "候选人",
            resume_summary=resume_summary,
            qa_summary=qa_summary,
        )

        try:
            response = await self._call_llm_with_retry(
                prompt=prompt,
                temperature=0.3,
            )
            return response.strip()
        except Exception as e:
            logger.error("简历优化建议生成失败（所有模型）", error=str(e))
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
