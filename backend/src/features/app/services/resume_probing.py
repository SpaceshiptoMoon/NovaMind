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
from src.features.app.schemas.resume_schema import (
    StructuredResume, ProbingPlan, KnowledgePoint, JDAnalysis,
)
from src.features.app.services.resume_parser import _extract_json

logger = get_logger(__name__)

# ==================== 常量 ====================

MAX_RETRIES = 3              # 主模型最大重试次数
RETRY_BASE_DELAY = 2         # 指数退避基础延迟（秒）
FALLBACK_MAX_RETRIES = 1     # 降级模型每个最多重试次数

# ==================== Prompt 模板 ====================

# 第一轮：基于知识点和简历背景提出初始问题
FIRST_ROUND_PROMPT = """你同时扮演面试官和候选人两个角色，围绕候选人的「{kp_name}」经验提出第一个问题并回答。

## 候选人简历摘要
{resume_summary}

## 当前知识点
- 名称: {kp_name}
- 类别: {kp_category}
- 来源: {kp_source}
{probing_chain_section}
{jd_context_section}

## 提问策略（按类别）

### 如果类别是 project（项目深挖）
围绕项目整体，从以下维度切入：
- 架构与选型：为什么选择这个架构/技术栈？考虑过哪些替代方案？
- 问题与挑战：遇到的最大技术挑战是什么？
- 方案与方法：用什么技术解决了什么问题？为什么选这个技术？
- 指标与验证：简历中的量化指标是怎么测出来的？用的什么测试工具？测试环境和流程是怎样的？有对比基线吗？数据采集方式是什么？
- 反思与改进：如果重新设计会怎么做？

### 如果类别是 tech_in_project（项目中的技术追问）
围绕项目中使用的具体技术，必须关联项目实际场景：
- 你在这个项目中用这个技术做了什么？解决什么问题？
- 为什么选这个技术而不是其他方案？（对比权衡）
- 使用过程中遇到什么坑？怎么解决的？
- 如果业务量翻倍，这个技术方案还能撑住吗？

### 如果类别是 fundamental（基础扎实度）
验证底层理解：
- 核心原理是什么？底层机制是怎样的？
- 常见使用场景和最佳实践
- 和同类技术的对比优劣势
- 生产环境中的注意事项

## 通用规则
1. 面试官基于简历中该技术/项目的实际描述提出问题
2. 候选人基于简历中描述的实际经验回答（不编造不夸大，没有涉及的内容如实说明）
3. quality_score 表示回答深度（0-1）：纯理论回答 0.3-0.5，有项目经验佐证 0.6-0.8，有量化数据和深度分析 0.8-1.0
4. 只输出 JSON

输出 JSON 格式：
{{
  "question": "面试官的问题",
  "answer": "候选人的回答",
  "quality_score": 0.7
}}
"""

# 后续轮：基于上一轮的回答进行追问深挖
FOLLOW_UP_PROMPT = """你同时扮演面试官和候选人两个角色。基于上一轮候选人的回答，提出一个更深入的追问并回答。

## 当前知识点
- 名称: {kp_name}
- 类别: {kp_category}

## 上一轮 Q&A
**Q**: {prev_question}
**A**: {prev_answer}
**评分**: {prev_score}

## 追问规则
1. 面试官必须针对上一轮回答中的具体内容进行追问，不要泛泛而问
2. 追问方向（任选其一，选择最能深入挖掘的方向）：
   - 回答中提到的技术细节：追问底层原理或实现机制
   - 回答中提到的方案选择：追问为什么这样选，有没有考虑过其他方案
   - 回答中提到的指标/数据：追问是怎么测的，对比基线是什么，测试方法论
   - 回答中提到的挑战：追问具体怎么解决的，踩了什么坑
   - 回答中的薄弱点：候选人回答模糊或浅显的地方，进一步追问
3. 候选人基于简历中的实际经验回答（不编造不夸大）
4. 如果上一轮回答已经很深入（score >= 0.8），追问可以转向相关联的延伸话题
5. quality_score 表示本轮回答深度（0-1）：纯理论回答 0.3-0.5，有项目经验佐证 0.6-0.8，有量化数据和深度分析 0.8-1.0
6. 只输出 JSON

输出 JSON 格式：
{{
  "question": "面试官的追问",
  "answer": "候选人的回答",
  "quality_score": 0.7
}}
"""

EVALUATION_PROMPT = """你是一个面试准备顾问。根据以下自动追问的 Q&A 记录，生成一份面向候选人的面试准备建议报告。

## 候选人
{name}

## 追问记录摘要
{qa_summary}

请输出 Markdown 格式的报告，包含以下章节：

## 面试准备建议

### 项目经验准备
（针对每个项目的追问表现，给出具体的准备建议：哪些问题回答得好可以重点展示，哪些问题需要补充准备）

### 技术深度补充
（追问中暴露的技术薄弱点，给出需要重点复习的知识点和学习建议）

### 基础知识巩固
（基础扎实度测试中表现不足的地方，给出需要巩固的方向）

### 高频考点预测
（基于简历和追问情况，预测面试中最可能被问到的问题 Top 5）

### 表达建议
（如何更好地用 STAR 法则描述项目经验，如何量化成果）
"""


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

        resume_summary = self._make_resume_summary(structured_resume)

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
            first_prompt = FIRST_ROUND_PROMPT.format(
                kp_name=kp.name,
                kp_category=kp.category,
                kp_source=kp.source,
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
                follow_prompt = FOLLOW_UP_PROMPT.format(
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

        prompt = EVALUATION_PROMPT.format(
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
