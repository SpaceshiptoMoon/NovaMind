"""
S5-S9 + S12: 简历分析报告生成 Pipeline (V2)

三阶段框架：
  S5:   JD 技术图谱提取（有JD时）
  S6:   工作-项目上下文合并（WorkProjectUnit）
  S6.5: 公司/岗位背景补充（搜索引擎 + LLM）
  S7:   复杂度评估 + 追问策略（自动分配轮数）
  S8:   技术前置学习（学习导向 Q&A）
  S9:   组装中间 MD 报告（三段式）
  S12:  组装最终报告（三段式 + Q&A + 简历建议）
"""
import json
from typing import Optional

from novamind.core.middleware.structured_logging import get_logger
from novamind.setting.yaml_config import get_config
from novamind.shared.ai_models.llm import BaseLLM
from novamind.shared.prompts import PromptTemplate, PromptManager
from novamind.features.app.services.resume_parser import _extract_json
from novamind.features.app.schemas.resume_schema import (
    StructuredResume, JDAnalysis, JDSkill,
    ProbingPlan, KnowledgePoint, ProjectPriority, PrefixKnowledge,
    WorkProjectUnit,
)

logger = get_logger(__name__)


class ResumeAnalyzer:
    """简历分析 + 报告生成器（V2 三阶段框架）"""

    def __init__(self, llm_client: BaseLLM):
        self.llm = llm_client
        self._search_service = None

    def _get_search_service(self):
        """懒加载搜索引擎服务（优先 Tavily，备选 DuckDuckGo）"""
        if self._search_service is not None:
            return self._search_service

        config = get_config()
        ext_config = getattr(config, 'external_search', None)

        # 尝试 Tavily（质量最高，需要 API Key）
        if ext_config and hasattr(ext_config, 'tavily') and ext_config.tavily.api_key:
            try:
                from novamind.features.deep_research.services.tavily_service import TavilySearchService
                svc = TavilySearchService()
                if svc.is_available():
                    self._search_service = svc
                    logger.info("使用 Tavily 搜索引擎补充公司背景")
                    return self._search_service
            except Exception as e:
                logger.warning("Tavily 加载失败", error=str(e))

        # 回退到 DuckDuckGo（免费）
        try:
            from novamind.features.deep_research.services.duckduckgo_service import DuckDuckGoSearchService
            svc = DuckDuckGoSearchService()
            if svc.is_available():
                self._search_service = svc
                logger.info("使用 DuckDuckGo 搜索引擎补充公司背景")
                return self._search_service
        except Exception as e:
            logger.warning("DuckDuckGo 加载失败", error=str(e))

        logger.warning("无可用搜索引擎，将降级到纯 LLM 推断")
        return None

    async def _generate_resume_summary(self, resume: StructuredResume) -> str:
        """S4.5: 调用 LLM 生成简历概述"""
        resume_data = self._make_resume_summary(resume)
        prompt = PromptManager.format_prompt(PromptTemplate.RESUME_SUMMARY.value, resume_data=resume_data)
        try:
            response = await self.llm.generate_text(
                prompt=prompt,
                temperature=0.3,
            )
            summary = response.strip()
            logger.info("简历摘要生成完成", summary_len=len(summary))
            return summary
        except Exception as e:
            logger.warning("简历摘要生成失败，跳过", error=str(e))
            return ""

    async def analyze(
        self,
        resume: StructuredResume,
        jd_text: Optional[str] = None,
        config: Optional[dict] = None,
    ) -> dict:
        """完整分析流程 S4.5 → S9"""
        cfg = config or {}
        breadth = cfg.get("breadth", 3)

        # S4.5: 生成简历摘要
        resume.resume_summary = await self._generate_resume_summary(resume)

        # S5: JD 技术图谱（可选）
        jd_analysis = None
        if jd_text and jd_text.strip():
            jd_analysis = await self._extract_jd_analysis(jd_text)
            logger.info("JD 技术图谱提取完成", skills=len(jd_analysis.required_skills))

        # S6: 工作-项目上下文合并
        work_units = self._merge_work_projects(resume)
        logger.info("工作-项目合并完成", unit_count=len(work_units))

        # S6.5: 公司/岗位背景补充
        work_units = await self._enrich_work_contexts(work_units)
        logger.info("公司/岗位背景补充完成")

        # S7: 复杂度评估 + 追问策略
        work_units = await self._assess_complexities(work_units, resume, jd_analysis)
        knowledge_points = self._build_knowledge_points(work_units, resume, jd_analysis, breadth)
        logger.info("知识点提取完成", kp_count=len(knowledge_points))

        probing_plan = await self._generate_probing_strategy(
            knowledge_points, work_units, resume, jd_analysis, breadth,
        )
        probing_plan.work_units = work_units
        logger.info("追问策略生成完成", total_rounds=probing_plan.total_rounds)

        # S8: 技术前置学习
        prefix_knowledge = await self._generate_prefix_knowledge(knowledge_points)
        logger.info("前缀知识生成完成", count=len(prefix_knowledge))

        # S9: 组装 MD 报告
        md_report = self._assemble_md_report(resume, jd_analysis, probing_plan, work_units, prefix_knowledge)
        logger.info("MD 报告组装完成", report_len=len(md_report))

        return {
            "jd_analysis": jd_analysis,
            "cross_mapping": {"knowledge_points": [kp.model_dump() for kp in knowledge_points]},
            "probing_plan": probing_plan,
            "prefix_knowledge": prefix_knowledge,
            "md_report": md_report,
        }

    # ==================== S5: JD 技术图谱 ====================

    async def _extract_jd_analysis(self, jd_text: str) -> JDAnalysis:
        prompt = PromptManager.format_prompt(PromptTemplate.RESUME_JD_ANALYSIS.value, jd_text=jd_text)
        response = await self.llm.generate_text(
            prompt=prompt,
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        data = json.loads(_extract_json(response))
        return JDAnalysis(**data)

    # ==================== S6: 工作-项目上下文合并 ====================

    def _merge_work_projects(self, resume: StructuredResume) -> list[WorkProjectUnit]:
        """将 project_experience 和 work_experience 合并为 WorkProjectUnit"""
        units: list[WorkProjectUnit] = []
        used_projects: set[int] = set()  # 已分配到某个工作单元的项目索引
        used_works: set[int] = set()     # 已处理的工作经历索引

        # 1. 对每个工作经历，找到关联的项目
        for wi, work in enumerate(resume.work_experience):
            matched_projects = []
            for pi, proj in enumerate(resume.project_experience):
                if pi in used_projects:
                    continue
                # 匹配条件：项目的 associated_company 包含公司名，或公司名包含 associated_company
                if proj.associated_company and (
                    proj.associated_company.lower() in work.company.lower()
                    or work.company.lower() in proj.associated_company.lower()
                ):
                    matched_projects.append(proj)
                    used_projects.add(pi)

            unit = WorkProjectUnit(
                id=f"work_{wi + 1}",
                company=work.company,
                company_brief=work.company_brief,
                position=work.position,
                department=work.department,
                employment_type=work.employment_type,
                work_period=f"{work.start_date} ~ {work.end_date}",
                work_responsibilities=work.responsibilities,
                work_tech_stack=work.tech_stack,
                projects=matched_projects,
            )
            # 构建初始上下文
            unit.full_context = self._build_unit_context(unit)
            units.append(unit)
            used_works.add(wi)

        # 2. 处理未关联工作经历的项目（个人项目、教育项目等）
        for pi, proj in enumerate(resume.project_experience):
            if pi in used_projects:
                continue
            unit = WorkProjectUnit(
                id=f"proj_standalone_{pi + 1}",
                projects=[proj],
            )
            unit.full_context = self._build_unit_context(unit)
            units.append(unit)

        # 3. 处理有公司但没有匹配到项目的工作经历（仅有工作职责）
        for wi, work in enumerate(resume.work_experience):
            if wi in used_works:
                continue
            unit = WorkProjectUnit(
                id=f"work_noproj_{wi + 1}",
                company=work.company,
                company_brief=work.company_brief,
                position=work.position,
                department=work.department,
                employment_type=work.employment_type,
                work_period=f"{work.start_date} ~ {work.end_date}",
                work_responsibilities=work.responsibilities,
                work_tech_stack=work.tech_stack,
                projects=[],
            )
            unit.full_context = self._build_unit_context(unit)
            units.append(unit)

        return units

    def _build_unit_context(self, unit: WorkProjectUnit) -> str:
        """构建工作单元的综合上下文"""
        parts = []

        if unit.company:
            parts.append(f"公司: {unit.company}")
            if unit.company_brief:
                parts.append(f"公司简介: {unit.company_brief}")
            if unit.position:
                parts.append(f"岗位: {unit.position}")
            if unit.department:
                parts.append(f"部门: {unit.department}")
            if unit.employment_type:
                parts.append(f"类型: {unit.employment_type}")
            if unit.work_period:
                parts.append(f"时间段: {unit.work_period}")
            if unit.work_responsibilities:
                parts.append("工作职责: " + "；".join(unit.work_responsibilities))
            if unit.work_tech_stack:
                parts.append("技术栈: " + "、".join(unit.work_tech_stack))

        for proj in unit.projects:
            parts.append(f"\n--- 项目: {proj.name} ---")
            if proj.background:
                parts.append(f"背景: {proj.background}")
            if proj.architecture:
                parts.append(f"架构: {proj.architecture}")
            if proj.role:
                parts.append(f"角色: {proj.role}")
            ts = proj.tech_stack
            tech_list = ts.languages + ts.frameworks + ts.middleware + ts.infrastructure + ts.tools
            if tech_list:
                parts.append(f"技术栈: {', '.join(tech_list)}")
            if proj.responsibilities:
                parts.append("职责: " + "；".join(proj.responsibilities))
            if proj.challenges:
                for c in proj.challenges:
                    line = f"挑战: {c.challenge} → 方案: {c.solution}"
                    if c.result:
                        line += f" → 结果: {c.result}"
                    parts.append(line)
            if proj.achievements:
                for a in proj.achievements:
                    line = f"成果: {a.description}"
                    if a.metric:
                        line += f"（{a.metric}）"
                    parts.append(line)
            if proj.highlights:
                parts.append("亮点: " + "；".join(proj.highlights))

        return "\n".join(parts)

    # ==================== S6.5: 公司/岗位背景补充 ====================

    async def _enrich_work_contexts(self, work_units: list[WorkProjectUnit]) -> list[WorkProjectUnit]:
        """对每个有公司信息的 WorkProjectUnit，通过搜索引擎+LLM补充背景"""
        for unit in work_units:
            if not unit.company or not unit.position:
                continue
            try:
                await self._enrich_single_context(unit)
            except Exception as e:
                logger.warning(
                    "公司背景补充失败，跳过",
                    company=unit.company,
                    error=str(e)[:200],
                )
        return work_units

    async def _enrich_single_context(self, unit: WorkProjectUnit) -> None:
        """补充单个工作单元的公司/岗位背景"""
        search_results_text = "（无搜索结果）"

        # 步骤1：搜索引擎查询
        search_service = self._get_search_service()
        if search_service:
            try:
                from novamind.shared.utils.redact import redact_sensitive_text
                # 搜索查询前脱敏，防止 JD/简历夹带联系方式外发搜索引擎
                company = redact_sensitive_text(unit.company or "")
                position = redact_sensitive_text(unit.position or "")
                queries = [
                    f"{company} {position} 技术栈 业务方向",
                    f"{company} {position} 面试 岗位职责",
                ]
                all_results = []
                for query in queries:
                    results = await search_service.search(query=query, max_results=5)
                    all_results.extend(results)

                if all_results:
                    # 去重并取 top 8
                    seen_urls = set()
                    unique = []
                    for r in all_results:
                        if r.url not in seen_urls:
                            seen_urls.add(r.url)
                            unique.append(r)
                    top_results = unique[:8]
                    search_results_text = "\n".join(
                        f"- [{r.title}] {r.content[:200]}"
                        for r in top_results
                    )
                    logger.info(
                        "搜索引擎查询成功",
                        company=unit.company,
                        result_count=len(top_results),
                    )
            except Exception as e:
                logger.warning(
                    "搜索引擎查询失败，将降级到 LLM 推断",
                    company=unit.company,
                    error=str(e)[:200],
                )

        # 步骤2：LLM 综合整理
        project_summary = "；".join(
            f"{p.name}（{', '.join(p.tech_stack.languages + p.tech_stack.frameworks)}）"
            for p in unit.projects
        )
        tech_stack = ", ".join(unit.work_tech_stack)
        if not tech_stack:
            all_tech = []
            for p in unit.projects:
                ts = p.tech_stack
                all_tech.extend(ts.languages + ts.frameworks + ts.middleware)
            tech_stack = ", ".join(set(all_tech))

        prompt = PromptManager.format_prompt(
            PromptTemplate.RESUME_WORK_CONTEXT_ENRICHMENT.value,
            company=unit.company,
            position=unit.position,
            department=unit.department or "未说明",
            responsibilities="；".join(unit.work_responsibilities) or "未说明",
            project_summary=project_summary or "未说明",
            tech_stack=tech_stack or "未说明",
            search_results=search_results_text,
        )

        response = await self.llm.generate_text(
            prompt=prompt,
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        data = json.loads(_extract_json(response))

        unit.company_industry = data.get("company_industry", "")
        unit.company_scale = data.get("company_scale", "")
        unit.position_context = data.get("position_context", "")
        unit.industry_context = data.get("industry_context", "")

        # 重新构建完整上下文（加入背景信息）
        unit.full_context = self._build_unit_context_with_enrichment(unit)

        logger.info(
            "公司背景补充完成",
            company=unit.company,
            has_industry=bool(unit.company_industry),
            has_position_ctx=bool(unit.position_context),
        )

    def _build_unit_context_with_enrichment(self, unit: WorkProjectUnit) -> str:
        """构建包含背景补充信息的完整上下文"""
        parts = [unit.full_context]  # 保留基础上下文

        if unit.company_industry:
            parts.append(f"\n--- 公司背景 ---")
            parts.append(f"行业: {unit.company_industry}")
        if unit.company_scale:
            parts.append(f"规模: {unit.company_scale}")
        if unit.position_context:
            parts.append(f"岗位定位: {unit.position_context}")
        if unit.industry_context:
            parts.append(f"行业关注点: {unit.industry_context}")

        return "\n".join(parts)

    # ==================== S7: 复杂度评估 ====================

    async def _assess_complexities(
        self,
        work_units: list[WorkProjectUnit],
        resume: StructuredResume,
        jd_analysis: Optional[JDAnalysis],
    ) -> list[WorkProjectUnit]:
        """LLM 评估每个工作单元的复杂度，自动分配追问轮数"""
        for unit in work_units:
            try:
                await self._assess_single_complexity(unit, resume, jd_analysis)
            except Exception as e:
                logger.warning(
                    "复杂度评估失败，使用默认轮数",
                    unit_id=unit.id,
                    error=str(e)[:200],
                )
                unit.allocated_rounds = 3
                unit.complexity_score = 0.5
        return work_units

    async def _assess_single_complexity(
        self,
        unit: WorkProjectUnit,
        resume: StructuredResume,
        jd_analysis: Optional[JDAnalysis],
    ) -> None:
        """评估单个工作单元的复杂度"""
        # 构建工作单元信息摘要
        unit_info_parts = []
        if unit.company:
            unit_info_parts.append(f"公司: {unit.company} | 岗位: {unit.position}")
        for proj in unit.projects:
            tech = ", ".join(
                proj.tech_stack.languages + proj.tech_stack.frameworks + proj.tech_stack.middleware
            )
            unit_info_parts.append(
                f"项目: {proj.name} | 角色: {proj.role} | 技术栈: {tech}"
            )
            if proj.background:
                unit_info_parts.append(f"  背景: {proj.background[:200]}")
            if proj.challenges:
                unit_info_parts.append(f"  挑战数: {len(proj.challenges)}")
            if proj.achievements:
                unit_info_parts.append(f"  成果数: {len(proj.achievements)}")
                for a in proj.achievements:
                    if a.metric:
                        unit_info_parts.append(f"    量化指标: {a.metric}")
        if not unit.projects and unit.work_responsibilities:
            unit_info_parts.append("工作职责: " + "；".join(unit.work_responsibilities[:5]))

        prompt = PromptManager.format_prompt(
            PromptTemplate.RESUME_COMPLEXITY_ASSESSMENT.value,
            work_unit_info="\n".join(unit_info_parts),
        )

        response = await self.llm.generate_text(
            prompt=prompt,
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        data = json.loads(_extract_json(response))

        unit.complexity_score = data.get("complexity_score", 0.5)
        unit.allocated_rounds = data.get("allocated_rounds", 3)
        unit.complexity_reasoning = data.get("reasoning", "")

        # 安全校验：限制在 2-8 轮
        unit.allocated_rounds = max(2, min(8, unit.allocated_rounds))

        logger.info(
            "复杂度评估完成",
            unit_id=unit.id,
            score=unit.complexity_score,
            rounds=unit.allocated_rounds,
        )

    # ==================== S7: 知识点构建（以工作单元为核心） ====================

    def _build_knowledge_points(
        self,
        work_units: list[WorkProjectUnit],
        resume: StructuredResume,
        jd_analysis: Optional[JDAnalysis],
        breadth: int = 3,
    ) -> list[KnowledgePoint]:
        """以工作单元为核心构建知识点，取代原有 Tier 1/2/3 分类"""
        points = []
        idx = 0

        for unit in work_units:
            # 每个项目生成一个项目知识点
            for proj in unit.projects:
                idx += 1
                proj_depth = self._calc_resume_depth(proj)
                proj_jd_rel = self._calc_project_jd_relevance(proj, jd_analysis)
                proj_weight = self._calc_weight(proj_jd_rel, proj_depth, jd_analysis is not None, is_project=True)

                points.append(KnowledgePoint(
                    id=f"proj_{idx}",
                    name=f"{proj.name}（{unit.company}）" if unit.company else proj.name,
                    category="project",
                    module="project_experience",
                    source=proj.name,
                    context=self._build_project_context(proj),
                    jd_relevance=proj_jd_rel,
                    resume_depth=proj_depth,
                    probing_weight=proj_weight,
                    work_unit_id=unit.id,
                    allocated_rounds=unit.allocated_rounds,
                    complexity_score=unit.complexity_score,
                    complexity_reasoning=unit.complexity_reasoning,
                ))

                # 项目中的技术追问
                all_tech = []
                ts = proj.tech_stack
                all_tech.extend(ts.languages)
                all_tech.extend(ts.frameworks)
                all_tech.extend(ts.middleware)

                seen = set()
                for tech in all_tech:
                    if tech.lower() in seen:
                        continue
                    seen.add(tech.lower())
                    idx += 1
                    jd_rel = self._calc_jd_relevance(tech, jd_analysis)
                    weight = self._calc_weight(jd_rel, proj_depth, jd_analysis is not None)

                    points.append(KnowledgePoint(
                        id=f"tech_{idx}",
                        name=f"{tech}（{proj.name}）",
                        category="tech_in_project",
                        module="project_experience",
                        source=proj.name,
                        context=self._build_project_context(proj),
                        jd_relevance=jd_rel,
                        resume_depth=proj_depth,
                        probing_weight=weight,
                        work_unit_id=unit.id,
                        allocated_rounds=max(2, unit.allocated_rounds - 1),
                    ))

            # 如果工作单元没有项目但有工作职责，生成一个工作职责知识点
            if not unit.projects and unit.work_responsibilities:
                idx += 1
                weight = self._calc_weight(0.5, 0.4, jd_analysis is not None)
                points.append(KnowledgePoint(
                    id=f"work_resp_{idx}",
                    name=f"{unit.position} @ {unit.company}" if unit.company else "工作经历",
                    category="work_responsibility",
                    module="work_experience",
                    source=unit.company or "工作经历",
                    context="；".join(unit.work_responsibilities),
                    jd_relevance=0.5,
                    resume_depth=0.4,
                    probing_weight=weight,
                    work_unit_id=unit.id,
                    allocated_rounds=unit.allocated_rounds,
                ))

        # 基础技能知识点（Skills 中未被项目技术覆盖的）
        skill_map = {}
        for group in (resume.skills.skill_groups if resume.skills else []):
            for item in group.items:
                skill_map[item.name] = (group, item)

        covered = set()
        for unit in work_units:
            for proj in unit.projects:
                ts = proj.tech_stack
                for t in ts.languages + ts.frameworks + ts.middleware:
                    covered.add(t.lower())

        for skill_name, (group, item) in skill_map.items():
            if skill_name.lower() in covered:
                continue
            idx += 1
            jd_rel = self._calc_jd_relevance(skill_name, jd_analysis)
            weight = self._calc_weight(jd_rel, 0.4, jd_analysis is not None)

            parts = [f"技能分类: {group.label}"]
            if item.proficiency:
                parts.append(f"熟练度: {item.proficiency}")
            if item.years:
                parts.append(f"使用年限: {item.years}年")

            points.append(KnowledgePoint(
                id=f"fundamental_{idx}",
                name=skill_name,
                category="fundamental",
                module="skills",
                source="技能列表",
                context="，".join(parts),
                jd_relevance=jd_rel,
                resume_depth=0.4,
                probing_weight=weight,
                allocated_rounds=2,
            ))

        # 论文和专利
        for paper in resume.publications.papers:
            idx += 1
            paper_parts = []
            if paper.abstract:
                paper_parts.append(f"摘要: {paper.abstract}")
            if paper.keywords:
                paper_parts.append(f"关键词: {', '.join(paper.keywords)}")
            if paper.my_contribution:
                paper_parts.append(f"个人贡献: {paper.my_contribution}")

            points.append(KnowledgePoint(
                id=f"paper_{idx}",
                name=paper.title,
                category="paper",
                module="papers",
                source=paper.title,
                context="\n".join(paper_parts),
                jd_relevance=0.3 if jd_analysis else 0.5,
                resume_depth=0.7 if paper.abstract else 0.3,
                probing_weight=0.4,
                allocated_rounds=2,
            ))

        for patent in resume.publications.patents:
            idx += 1
            patent_parts = []
            if patent.brief:
                patent_parts.append(f"简介: {patent.brief}")
            if patent.patent_type:
                patent_parts.append(f"类型: {patent.patent_type}")

            points.append(KnowledgePoint(
                id=f"patent_{idx}",
                name=patent.title,
                category="patent",
                module="patents",
                source=patent.title,
                context="\n".join(patent_parts),
                jd_relevance=0.3 if jd_analysis else 0.5,
                resume_depth=0.5,
                probing_weight=0.3,
                allocated_rounds=2,
            ))

        # 排序并归一化
        if points:
            max_w = max(p.probing_weight for p in points) or 1
            for p in points:
                p.probing_weight = p.probing_weight / max_w

        return points

    def _build_project_context(self, proj) -> str:
        """从项目对象构建完整上下文"""
        parts = []
        if proj.background:
            parts.append(f"项目背景: {proj.background}")
        if proj.architecture:
            parts.append(f"架构: {proj.architecture}")
        if proj.responsibilities:
            parts.append("职责: " + "；".join(proj.responsibilities))
        if proj.challenges:
            for c in proj.challenges:
                parts.append(
                    f"挑战: {c.challenge} → 方案: {c.solution}"
                    + (f" → 结果: {c.result}" if c.result else "")
                )
        if proj.achievements:
            for a in proj.achievements:
                parts.append(f"成果: {a.description}" + (f"（{a.metric}）" if a.metric else ""))
        if proj.highlights:
            parts.append("亮点: " + "；".join(proj.highlights))
        return "\n".join(parts)

    def _calc_jd_relevance(self, tech: str, jd: Optional[JDAnalysis]) -> float:
        if not jd:
            return 0.5
        tech_lower = tech.lower()
        for s in jd.required_skills:
            if tech_lower == s.name.lower():
                return 1.0
            if tech_lower in s.name.lower() or s.name.lower() in tech_lower:
                return 0.7
        for s in jd.preferred_skills:
            if tech_lower == s.name.lower():
                return 0.7
            if tech_lower in s.name.lower() or s.name.lower() in tech_lower:
                return 0.5
        return 0.1

    def _calc_project_jd_relevance(self, proj, jd: Optional[JDAnalysis]) -> float:
        if not jd:
            return 0.5
        all_tech = []
        ts = proj.tech_stack
        all_tech.extend(ts.languages + ts.frameworks + ts.middleware)
        if not all_tech:
            return 0.3
        relevances = [self._calc_jd_relevance(t, jd) for t in all_tech]
        return max(relevances)

    def _calc_resume_depth(self, proj) -> float:
        score = 0.0
        if proj.background:
            score += 0.2
        if proj.architecture:
            score += 0.2
        if proj.challenges:
            score += 0.2 * min(len(proj.challenges), 3)
        if proj.achievements:
            score += 0.1 * min(len(proj.achievements), 3)
        return min(score, 1.0)

    def _calc_weight(self, jd_rel: float, depth: float, has_jd: bool, is_project: bool = False) -> float:
        base = 0.0
        if has_jd:
            base = jd_rel * 0.5 + depth * 0.3 + 0.2
        else:
            base = depth * 0.6 + 0.3 + jd_rel * 0.1
        if is_project:
            base *= 1.5
        return min(base, 1.0)

    # ==================== S7: 追问策略 ====================

    async def _generate_probing_strategy(
        self,
        knowledge_points: list[KnowledgePoint],
        work_units: list[WorkProjectUnit],
        resume: StructuredResume,
        jd_analysis: Optional[JDAnalysis],
        breadth: int,
    ) -> ProbingPlan:
        sorted_points = sorted(knowledge_points, key=lambda p: p.probing_weight, reverse=True)

        resume_summary = resume.resume_summary or self._make_resume_summary(resume)
        jd_info = jd_analysis.model_dump_json(indent=2) if jd_analysis else "无目标岗位"

        # 构建工作单元 JSON
        work_units_json = json.dumps(
            [
                {
                    "id": u.id,
                    "company": u.company,
                    "position": u.position,
                    "company_industry": u.company_industry,
                    "position_context": u.position_context,
                    "industry_context": u.industry_context,
                    "projects": [
                        {
                            "name": p.name,
                            "tech_stack": ", ".join(
                                p.tech_stack.languages + p.tech_stack.frameworks + p.tech_stack.middleware
                            ),
                            "role": p.role,
                            "background": p.background[:200] if p.background else "",
                            "context": self._build_project_context(p)[:500],
                            "allocated_rounds": u.allocated_rounds,
                        }
                        for p in u.projects
                    ],
                    "work_responsibilities": u.work_responsibilities[:5],
                    "allocated_rounds": u.allocated_rounds,
                }
                for u in work_units
            ],
            ensure_ascii=False,
            indent=2,
        )

        prompt = PromptManager.format_prompt(
            PromptTemplate.RESUME_PROBING_STRATEGY.value,
            jd_info=jd_info,
            resume_summary=resume_summary,
            work_units_json=work_units_json,
            breadth=breadth,
        )

        try:
            response = await self.llm.generate_text(
                prompt=prompt,
                temperature=0.3,
                response_format={"type": "json_object"},
            )
            data = json.loads(_extract_json(response))
            updated_plans = {p["project_name"]: p.get("probing_chain", []) for p in data.get("probing_plans", [])}

            # 将问题链分配给对应的知识点
            for p in sorted_points:
                if p.category == "project" and p.source in updated_plans:
                    p.probing_chain = updated_plans[p.source][:p.allocated_rounds]
        except Exception as e:
            logger.error("追问策略生成失败，使用默认问题", error=str(e))

        # 生成项目优先级
        proj_points = [p for p in sorted_points if p.category == "project"]
        project_priorities = [
            ProjectPriority(name=p.name, weight=p.probing_weight, allocated_rounds=p.allocated_rounds)
            for p in proj_points
        ]

        # 计算总轮数和轮数分布
        actual_total = sum(p.allocated_rounds for p in sorted_points)
        rounds_dist = {}
        for p in sorted_points:
            rounds_dist[p.category] = rounds_dist.get(p.category, 0) + p.allocated_rounds

        return ProbingPlan(
            knowledge_points=sorted_points,
            work_units=work_units,
            project_priorities=project_priorities,
            total_rounds=actual_total,
            rounds_distribution=rounds_dist,
            has_jd=jd_analysis is not None,
        )

    def _make_resume_summary(self, resume: StructuredResume) -> str:
        lines = []
        lines.append(f"候选人: {resume.personal_info.name}")
        lines.append(f"简介: {resume.personal_info.summary}")
        for w in resume.work_experience:
            lines.append(f"- {w.company} | {w.position} | {w.start_date}~{w.end_date}")
        for p in resume.project_experience:
            tech = ", ".join(p.tech_stack.languages + p.tech_stack.frameworks + p.tech_stack.middleware)
            lines.append(f"- 项目: {p.name} | {p.role} | 技术栈: {tech}")
        for paper in resume.publications.papers:
            lines.append(f"- 论文: {paper.title} | {paper.venue}")
        return "\n".join(lines)

    # ==================== S8: 技术前置学习 ====================

    async def _generate_prefix_knowledge(self, top_points: list[KnowledgePoint]) -> list[PrefixKnowledge]:
        tech_list = []
        seen = set()
        for p in top_points:
            if p.category in ("tech_in_project", "fundamental") and p.name not in seen:
                tech_list.append(p.name)
                seen.add(p.name)

        if not tech_list:
            return []

        results: list[PrefixKnowledge] = []
        for tech_name in tech_list:
            prompt = PromptManager.format_prompt(
                PromptTemplate.RESUME_PREFIX_KNOWLEDGE.value,
                tech_list=json.dumps([tech_name], ensure_ascii=False),
            )
            try:
                response = await self.llm.generate_text(
                    prompt=prompt,
                    temperature=0.2,
                    response_format={"type": "json_object"},
                )
                data = json.loads(_extract_json(response))
                items = data.get("items", [])
                if items:
                    results.append(PrefixKnowledge(**items[0]))
                    logger.info("前缀知识生成成功", tech=tech_name)
            except Exception as e:
                logger.warning("前缀知识生成失败，跳过", tech=tech_name, error=str(e))

        return results

    # ==================== S9: 组装中间 MD 报告（三段式） ====================

    def _assemble_md_report(
        self,
        resume: StructuredResume,
        jd_analysis: Optional[JDAnalysis],
        probing_plan: ProbingPlan,
        work_units: list[WorkProjectUnit],
        prefix_knowledge: list[PrefixKnowledge],
    ) -> str:
        parts = []
        pi = resume.personal_info

        # 标题
        parts.append("# 面试深度追问报告\n")
        parts.append(f"**候选人**: {pi.name}")
        if jd_analysis:
            parts.append(f"**目标岗位**: {jd_analysis.position_title}" + (f" @ {jd_analysis.company}" if jd_analysis.company else ""))
        else:
            parts.append("**模式**: 纯简历挖掘（无目标岗位）")
        parts.append(f"**总追问轮数**: {probing_plan.total_rounds}")
        parts.append(f"**工作单元**: {len(work_units)} 个")
        parts.append("")

        # ==================== Part 1: 技术前置学习 ====================
        parts.append("---\n")
        parts.append("# Part 1：技术前置学习\n")

        if prefix_knowledge:
            for pk in prefix_knowledge:
                parts.append(f"## {pk.tech_name}\n")
                if pk.core_concepts:
                    parts.append("**核心概念**: " + "、".join(pk.core_concepts))
                if pk.quick_reference:
                    parts.append(f"\n> {pk.quick_reference}\n")
                if pk.learning_qa:
                    parts.append("**学习 Q&A**:")
                    for i, qa in enumerate(pk.learning_qa, 1):
                        if isinstance(qa, dict):
                            parts.append(f"\n**Q{i}**: {qa.get('question', '')}")
                            parts.append(f"**A{i}**: {qa.get('answer', '')}")
                        else:
                            parts.append(f"\n**Q{i}**: {qa.question}")
                            parts.append(f"**A{i}**: {qa.answer}")
                if pk.pitfalls:
                    parts.append("\n**常见踩坑**: " + "、".join(pk.pitfalls))
                parts.append("")
        else:
            parts.append("_（暂无技术学习材料）_\n")

        # ==================== Part 2: 项目深度追问 ====================
        parts.append("---\n")
        parts.append("# Part 2：项目深度追问\n")

        # 按工作单元组织
        for unit in work_units:
            # 工作单元头部
            if unit.company:
                parts.append(f"## 工作单元：{unit.company} - {unit.position}\n")
                if unit.company_industry:
                    parts.append(f"**公司背景**: {unit.company_industry}")
                if unit.company_scale:
                    parts.append(f"**公司规模**: {unit.company_scale}")
                if unit.position_context:
                    parts.append(f"**岗位定位**: {unit.position_context}")
                if unit.industry_context:
                    parts.append(f"**行业关注点**: {unit.industry_context}")
                parts.append(f"**追问轮数**: {unit.allocated_rounds}轮")
                parts.append("")
            else:
                parts.append("## 独立项目\n")

            # 找到属于该工作单元的项目知识点
            unit_kps = [kp for kp in probing_plan.knowledge_points if kp.work_unit_id == unit.id]

            if unit.projects:
                for proj in unit.projects:
                    parts.append(f"### 项目: {proj.name}\n")
                    if proj.background:
                        parts.append(f"**背景**: {proj.background}")
                    tech = ", ".join(
                        proj.tech_stack.languages + proj.tech_stack.frameworks + proj.tech_stack.middleware
                    )
                    if tech:
                        parts.append(f"**技术栈**: {tech}")
                    if proj.role:
                        parts.append(f"**角色**: {proj.role}")
                    parts.append("")

                    # 找到该项目的知识点
                    proj_kps = [kp for kp in unit_kps if kp.source == proj.name]

                    parts.append("**追问记录**:")
                    q_idx = 1
                    for kp in proj_kps:
                        for q in kp.probing_chain[:kp.allocated_rounds]:
                            parts.append(f"{q_idx}. **Q**: {q}")
                            parts.append(f"   **A**: _（待追问填入）_")
                            q_idx += 1
                    parts.append("")

                    # 也包含该项目的技术追问
                    tech_kps = [kp for kp in unit_kps if kp.category == "tech_in_project" and kp.source == proj.name]
                    if tech_kps:
                        parts.append("**技术追问**:")
                        for kp in tech_kps:
                            parts.append(f"\n#### {kp.name}（{kp.allocated_rounds}轮）\n")
                            for i, q in enumerate(kp.probing_chain[:kp.allocated_rounds], 1):
                                parts.append(f"{i}. **Q**: {q}")
                                parts.append(f"   **A**: _（待追问填入）_")
                        parts.append("")
            elif unit.work_responsibilities:
                # 工作职责追问
                work_kps = [kp for kp in unit_kps if kp.category == "work_responsibility"]
                parts.append("**工作职责追问**:")
                for kp in work_kps:
                    for i, q in enumerate(kp.probing_chain[:kp.allocated_rounds], 1):
                        parts.append(f"{i}. **Q**: {q}")
                        parts.append(f"   **A**: _（待追问填入）_")
                parts.append("")

        # 技能/论文/专利等独立知识点
        other_kps = [kp for kp in probing_plan.knowledge_points if not kp.work_unit_id]
        if other_kps:
            parts.append("## 其他知识点\n")
            for kp in other_kps:
                parts.append(f"### {kp.name}（{kp.allocated_rounds}轮）\n")
                parts.append("**追问记录**:")
                for i, q in enumerate(kp.probing_chain[:kp.allocated_rounds], 1):
                    parts.append(f"{i}. **Q**: {q}")
                    parts.append(f"   **A**: _（待追问填入）_")
                parts.append("")

        # ==================== Part 3: 简历优化建议（占位） ====================
        parts.append("---\n")
        parts.append("# Part 3：简历优化建议\n")
        parts.append("_（追问全部完成后自动生成）_\n")

        return "\n".join(parts)

    def _calc_match_score(self, resume: StructuredResume, jd: JDAnalysis) -> int:
        if not jd.required_skills:
            return 80
        all_resume_tech = set()
        for proj in resume.project_experience:
            ts = proj.tech_stack
            all_resume_tech.update(t.lower() for t in ts.languages + ts.frameworks + ts.middleware + ts.infrastructure + ts.tools)
        for w in resume.work_experience:
            all_resume_tech.update(t.lower() for t in w.tech_stack)

        matched = 0
        for s in jd.required_skills:
            if any(s.name.lower() in t or t in s.name.lower() for t in all_resume_tech):
                matched += 1
        return int(matched / len(jd.required_skills) * 100) if jd.required_skills else 80

    # ==================== S12: 最终报告组装（三段式） ====================

    def _assemble_final_md_report(
        self,
        resume: StructuredResume,
        jd_analysis: Optional[JDAnalysis],
        probing_plan: ProbingPlan,
        work_units: list[WorkProjectUnit],
        prefix_knowledge: list[PrefixKnowledge],
        qa_records: list[dict],
        preparation_advice: str = "",
        resume_advice: str = "",
    ) -> str:
        """组装最终报告，填入 Q&A + 面试准备建议 + 简历优化建议"""
        qa_map = {}
        for r in qa_records:
            if r.get("status") == "completed" and r.get("qa_pairs"):
                qa_map[r["kp_id"]] = r["qa_pairs"]

        parts = []
        pi = resume.personal_info

        # 标题
        parts.append("# 面试深度追问报告\n")
        parts.append(f"**候选人**: {pi.name}")
        if jd_analysis:
            parts.append(f"**目标岗位**: {jd_analysis.position_title}" + (f" @ {jd_analysis.company}" if jd_analysis.company else ""))
        else:
            parts.append("**模式**: 纯简历挖掘（无目标岗位）")

        total_qa = sum(len(qa_map.get(kp.id, [])) for kp in probing_plan.knowledge_points)
        parts.append(f"**追问知识点**: {len(qa_map)} 个，共 {total_qa} 轮 Q&A")
        parts.append(f"**工作单元**: {len(work_units)} 个")
        parts.append("")

        # ==================== Part 1: 技术前置学习 ====================
        parts.append("---\n")
        parts.append("# Part 1：技术前置学习\n")

        if prefix_knowledge:
            for pk in prefix_knowledge:
                parts.append(f"## {pk.tech_name}\n")
                if pk.core_concepts:
                    parts.append("**核心概念**: " + "、".join(pk.core_concepts))
                if pk.quick_reference:
                    parts.append(f"\n> {pk.quick_reference}\n")
                if pk.learning_qa:
                    parts.append("**学习 Q&A**:")
                    for i, qa in enumerate(pk.learning_qa, 1):
                        if isinstance(qa, dict):
                            parts.append(f"\n**Q{i}**: {qa.get('question', '')}")
                            parts.append(f"**A{i}**: {qa.get('answer', '')}")
                        else:
                            parts.append(f"\n**Q{i}**: {qa.question}")
                            parts.append(f"**A{i}**: {qa.answer}")
                if pk.pitfalls:
                    parts.append("\n**常见踩坑**: " + "、".join(pk.pitfalls))
                parts.append("")

        # ==================== Part 2: 项目深度追问 ====================
        parts.append("---\n")
        parts.append("# Part 2：项目深度追问\n")

        for unit in work_units:
            if unit.company:
                parts.append(f"## 工作单元：{unit.company} - {unit.position}\n")
                if unit.company_industry:
                    parts.append(f"**公司背景**: {unit.company_industry}")
                if unit.position_context:
                    parts.append(f"**岗位定位**: {unit.position_context}")
                if unit.industry_context:
                    parts.append(f"**行业关注点**: {unit.industry_context}")
                parts.append("")
            else:
                parts.append("## 独立项目\n")

            unit_kps = [kp for kp in probing_plan.knowledge_points if kp.work_unit_id == unit.id]

            if unit.projects:
                for proj in unit.projects:
                    parts.append(f"### 项目: {proj.name}\n")
                    if proj.background:
                        parts.append(f"**背景**: {proj.background}")
                    tech = ", ".join(
                        proj.tech_stack.languages + proj.tech_stack.frameworks + proj.tech_stack.middleware
                    )
                    if tech:
                        parts.append(f"**技术栈**: {tech}")
                    if proj.role:
                        parts.append(f"**角色**: {proj.role}")
                    parts.append("")

                    proj_kps = [kp for kp in unit_kps if kp.source == proj.name]

                    for kp in proj_kps:
                        qa = qa_map.get(kp.id, [])
                        parts.append(f"#### {kp.name}（{len(qa)}轮）\n")
                        if qa:
                            for pair in qa:
                                score = pair.get("quality_score", 0)
                                parts.append(f"**Q{pair.get('round', '?')}:** {pair.get('question', '')}")
                                parts.append(f"**A:** {pair.get('answer', '')}")
                                parts.append(f"*深度评分: {score}*\n")
                        else:
                            parts.append("*追问未能生成*\n")
                    parts.append("")

                    # 项目技术追问
                    tech_kps = [kp for kp in unit_kps if kp.category == "tech_in_project" and kp.source == proj.name]
                    if tech_kps:
                        parts.append("**技术追问**:")
                        for kp in tech_kps:
                            qa = qa_map.get(kp.id, [])
                            parts.append(f"\n##### {kp.name}（{len(qa)}轮）\n")
                            if qa:
                                for pair in qa:
                                    score = pair.get("quality_score", 0)
                                    parts.append(f"**Q{pair.get('round', '?')}:** {pair.get('question', '')}")
                                    parts.append(f"**A:** {pair.get('answer', '')}")
                                    parts.append(f"*深度评分: {score}*\n")
                            else:
                                parts.append("*追问未能生成*\n")
                        parts.append("")
            elif unit.work_responsibilities:
                work_kps = [kp for kp in unit_kps if kp.category == "work_responsibility"]
                for kp in work_kps:
                    qa = qa_map.get(kp.id, [])
                    parts.append(f"### {kp.name}（{len(qa)}轮）\n")
                    if qa:
                        for pair in qa:
                            score = pair.get("quality_score", 0)
                            parts.append(f"**Q{pair.get('round', '?')}:** {pair.get('question', '')}")
                            parts.append(f"**A:** {pair.get('answer', '')}")
                            parts.append(f"*深度评分: {score}*\n")
                    else:
                        parts.append("*追问未能生成*\n")
                parts.append("")

        # 其他独立知识点
        other_kps = [kp for kp in probing_plan.knowledge_points if not kp.work_unit_id]
        if other_kps:
            parts.append("## 其他知识点\n")
            for kp in other_kps:
                qa = qa_map.get(kp.id, [])
                parts.append(f"### {kp.name}（{len(qa)}轮）\n")
                if qa:
                    for pair in qa:
                        score = pair.get("quality_score", 0)
                        parts.append(f"**Q{pair.get('round', '?')}:** {pair.get('question', '')}")
                        parts.append(f"**A:** {pair.get('answer', '')}")
                        parts.append(f"*深度评分: {score}*\n")
                else:
                    parts.append("*追问未能生成*\n")
                parts.append("")

        # ==================== Part 3: 简历优化建议 + 面试准备建议 ====================
        if resume_advice:
            parts.append("---\n")
            parts.append("# Part 3：简历优化建议\n")
            parts.append(resume_advice)
            parts.append("")

        if preparation_advice:
            parts.append("---\n")
            parts.append("## 附：面试准备建议\n")
            parts.append(preparation_advice)
            parts.append("")

        return "\n".join(parts)
