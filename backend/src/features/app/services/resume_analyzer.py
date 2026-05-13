"""
S5-S9: 分析报告生成 Pipeline

Pipeline:
  S5: JD 技术图谱提取（有JD时）
  S6: 简历↔JD 交叉映射（计算追问权重）
  S7: 追问策略生成（生成问题链）
  S8: 前缀知识生成
  S9: 组装 MD 报告
"""
import json
from typing import Optional

from src.core.middleware.structured_logging import get_logger
from src.shared.ai_models.llm import BaseLLM
from src.features.app.services.resume_parser import _extract_json
from src.features.app.schemas.resume_schema import (
    StructuredResume, JDAnalysis, JDSkill,
    ProbingPlan, KnowledgePoint, ProjectPriority, PrefixKnowledge,
)

logger = get_logger(__name__)

# ==================== Prompt 模板 ====================

JD_ANALYSIS_PROMPT = """你是一个岗位需求分析器。请从以下岗位描述中提取结构化的技术需求。

格式：
{{
  "position_title": "职位名称",
  "company": "公司名",
  "seniority_level": "junior/mid/senior/lead",
  "required_years": 0,
  "required_skills": [
    {{ "name": "技能名", "category": "language/framework/middleware/concept/domain", "importance": "required", "level": "精通/熟练/了解", "context": "JD中的原文描述" }}
  ],
  "preferred_skills": [
    {{ "name": "", "category": "", "importance": "preferred", "level": "", "context": "" }}
  ],
  "required_experience": ["经验要求1"],
  "domain_knowledge": ["领域知识1"],
  "soft_skills": ["软技能1"],
  "responsibilities": ["职责1"]
}}

注意：
1. importance 只有 required/preferred/plus 三种
2. 技能名称要标准化（如 "Go" 不要写成 "Golang"）
3. 只输出 JSON

JD 内容：
{jd_text}
"""

PROBING_STRATEGY_PROMPT = """你是一个面试追问策略设计器。根据以下信息生成追问计划。

## 目标岗位 JD 技术图谱
{jd_info}

## 候选人简历概要
{resume_summary}

## 已计算的知识点权重
{knowledge_points_json}

## 配置
- 广度（每个知识点的衍生主题数，1=仅核心，5=全部衍生）: {breadth}
- 深度（每个知识点的追问轮数，1=浅层，5=深层）: {depth}

## 追问模式（按知识点类别区分）

### 类别 project（项目深挖）—— 最高优先级
针对项目整体进行追问，必须覆盖以下维度：
1. **架构与选型**：项目整体架构是什么样的？为什么选择这个架构/技术栈？考虑过哪些替代方案？
2. **问题与挑战**：遇到的最大技术挑战是什么？具体场景是怎样的？
3. **方案与方法**：用什么技术/方法解决的？为什么选这个方案？
4. **指标与验证**：简历中提到的指标（性能提升XX%、延迟降低XXms）是怎么测出来的？测试环境和工具是什么？测试流程是怎样的？有对比基线吗？数据是怎么采集的？
5. **反思与改进**：如果重新设计会怎么做？有哪些遗憾或可以改进的地方？

### 类别 tech_in_project（项目中的技术追问）—— 中优先级
针对项目中使用的具体技术，必须关联项目实际场景：
1. 你在XX项目中用YY技术做了什么？解决什么场景的问题？
2. 为什么在这个场景选择YY而不是ZZ？（对比权衡）
3. 使用过程中遇到过什么坑或难点？怎么解决的？
4. 如果请求量翻10倍，这个技术方案还能撑住吗？怎么优化？

### 类别 fundamental（基础扎实度）—— 基础必问
验证候选人对核心技术的底层理解：
1. 核心原理/底层机制是什么？
2. 常见的使用场景和最佳实践？
3. 和同类技术对比的优劣势？
4. 生产环境中的注意事项和常见踩坑？

输出 JSON 格式：
{{
  "updated_points": [
    {{
      "id": "知识点ID",
      "probing_chain": [
        "第1轮问题",
        "第2轮问题",
        ...
      ]
    }}
  ]
}}

注意：
1. 每个知识点生成 depth 个追问问题（depth即allocated_rounds）
2. 严格按照上面的类别模式设计问题
3. （有JD时）问题要结合JD中的具体场景和要求
4. 问题要自然，像真实面试对话
5. 只输出 JSON
"""

PREFIX_KNOWLEDGE_PROMPT = """你是一个面试前缀知识生成器。为以下技术点生成面试准备知识卡片，每个考点和问题必须附带简明答案。

技术点列表：
{tech_list}

对于每个技术点，生成：

{{
  "items": [
    {{
      "tech_name": "技术名",
      "category": "分类",
      "core_concepts": ["核心概念1", "核心概念2", "核心概念3"],
      "common_interview_topics": [
        {{"topic": "考点名称", "answer": "简明答案（2-3句话，包含关键要点）"}}
      ],
      "key_questions": [
        {{"question": "经典面试问题", "answer": "参考答案（3-5句话，包含核心原理和要点）"}}
      ],
      "quick_reference": "一段话快速回顾（100字以内）",
      "pitfalls": ["常见踩坑1", "常见踩坑2"],
      "comparison": [
        {{ "name": "替代方案名", "pros": "相比该技术的优势", "cons": "相比该技术的劣势" }}
      ]
    }}
  ]
}}

注意：
1. common_interview_topics 每条必须有 answer，不能只有考点名
2. key_questions 每条必须有 answer，给出面试能拿高分的参考回答
3. 答案要精炼、准确、有深度，不要空泛
4. 只输出 JSON
"""


class ResumeAnalyzer:
    """简历分析 + 报告生成器"""

    def __init__(self, llm_client: BaseLLM):
        self.llm = llm_client

    async def analyze(
        self,
        resume: StructuredResume,
        jd_text: Optional[str] = None,
        config: Optional[dict] = None,
    ) -> dict:
        """完整分析流程 S5 → S9"""
        cfg = config or {}
        breadth = cfg.get("breadth", 3)
        depth = cfg.get("depth", 3)

        # S5: JD 技术图谱（可选）
        jd_analysis = None
        if jd_text and jd_text.strip():
            jd_analysis = await self._extract_jd_analysis(jd_text)
            logger.info("JD 技术图谱提取完成", skills=len(jd_analysis.required_skills))

        # S6: 交叉映射 + 权重计算
        knowledge_points = self._cross_mapping(resume, jd_analysis, breadth)
        logger.info("交叉映射完成", kp_count=len(knowledge_points))

        # S7: 追问策略
        probing_plan = await self._generate_probing_strategy(
            knowledge_points, resume, jd_analysis, breadth, depth,
        )
        logger.info("追问策略生成完成", total_rounds=probing_plan.total_rounds)

        # S8: 前缀知识
        prefix_knowledge = await self._generate_prefix_knowledge(knowledge_points)
        logger.info("前缀知识生成完成", count=len(prefix_knowledge))

        # S9: 组装 MD 报告
        md_report = self._assemble_md_report(resume, jd_analysis, probing_plan, prefix_knowledge)
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
        prompt = JD_ANALYSIS_PROMPT.format(jd_text=jd_text)
        response = await self.llm.generate_text(
            prompt=prompt,
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        data = json.loads(_extract_json(response))
        return JDAnalysis(**data)

    # ==================== S6: 交叉映射 ====================

    def _cross_mapping(
        self, resume: StructuredResume, jd_analysis: Optional[JDAnalysis], breadth: int = 3,
    ) -> list[KnowledgePoint]:
        points = []
        idx = 0

        # ===== Tier 1: 项目深挖（最高权重） =====
        for proj in resume.project_experience:
            idx += 1
            proj_depth = self._calc_resume_depth(proj)
            proj_jd_rel = self._calc_project_jd_relevance(proj, jd_analysis)
            proj_weight = self._calc_weight(proj_jd_rel, proj_depth, jd_analysis is not None, is_project=True)

            points.append(KnowledgePoint(
                id=f"proj_{idx}",
                name=proj.name,
                category="project",
                module="project_experience",
                source=proj.name,
                jd_relevance=proj_jd_rel,
                resume_depth=proj_depth,
                probing_weight=proj_weight,
            ))

        # ===== Tier 2: 项目中的技术追问（中等权重） =====
        for proj in resume.project_experience:
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
                depth = self._calc_resume_depth(proj)
                weight = self._calc_weight(jd_rel, depth, jd_analysis is not None)

                derivatives = self._get_derivatives(tech, breadth)

                points.append(KnowledgePoint(
                    id=f"tech_{idx}",
                    name=f"{tech}（{proj.name}）",
                    category="tech_in_project",
                    module="project_experience",
                    source=proj.name,
                    jd_relevance=jd_rel,
                    resume_depth=depth,
                    probing_weight=weight,
                    derivatives=derivatives,
                ))

        # ===== Tier 3: 基础扎实度（基础权重） =====
        all_skill_names = set()
        for group in (resume.skills.skill_groups if resume.skills else []):
            for item in group.items:
                all_skill_names.add(item.name)

        # 排除 Tier 2 已覆盖的技术
        covered = set()
        for proj in resume.project_experience:
            ts = proj.tech_stack
            for t in ts.languages + ts.frameworks + ts.middleware:
                covered.add(t.lower())

        for skill in all_skill_names:
            if skill.lower() in covered:
                continue
            idx += 1
            jd_rel = self._calc_jd_relevance(skill, jd_analysis)
            weight = self._calc_weight(jd_rel, 0.4, jd_analysis is not None)

            points.append(KnowledgePoint(
                id=f"fundamental_{idx}",
                name=skill,
                category="fundamental",
                module="skills",
                source="技能列表",
                jd_relevance=jd_rel,
                resume_depth=0.4,
                probing_weight=weight,
            ))

        # 从论文中提取知识点
        for paper in resume.publications.papers:
            idx += 1
            points.append(KnowledgePoint(
                id=f"paper_{idx}",
                name=paper.title,
                category="paper",
                module="papers",
                source=paper.title,
                jd_relevance=0.3 if jd_analysis else 0.5,
                resume_depth=0.7 if paper.abstract else 0.3,
                probing_weight=0.4,
            ))

        # 从专利中提取知识点
        for patent in resume.publications.patents:
            idx += 1
            points.append(KnowledgePoint(
                id=f"patent_{idx}",
                name=patent.title,
                category="patent",
                module="patents",
                source=patent.title,
                jd_relevance=0.3 if jd_analysis else 0.5,
                resume_depth=0.5,
                probing_weight=0.3,
            ))

        # 排序并归一化
        if points:
            max_w = max(p.probing_weight for p in points) or 1
            for p in points:
                p.probing_weight = p.probing_weight / max_w

        return points

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

    def _get_derivatives(self, tech: str, breadth: int = 3) -> list[str]:
        deriv_map = {
            "redis": ["Redis数据结构", "持久化(RDB/AOF)", "高可用(Sentinel/Cluster)", "缓存策略(穿透/击穿/雪崩)", "分布式锁"],
            "kafka": ["分区策略", "消费者组", "消息可靠性", "Exactly-Once语义", "性能调优"],
            "mysql": ["索引优化", "事务隔离级别", "锁机制", "主从复制", "分库分表"],
            "elasticsearch": ["倒排索引", "分词器", "相关性算分", "聚合查询", "集群架构"],
            "kubernetes": ["Pod/Deployment", "Service/Ingress", "存储卷", "HPA自动扩缩", "网络策略"],
            "docker": ["镜像构建", "容器网络", "数据卷", "Docker Compose", "多阶段构建"],
            "go": ["协程(Goroutine)", "Channel", "内存模型", "错误处理", "性能调优"],
            "python": ["GIL", "异步编程", "装饰器", "内存管理", "类型系统"],
            "mongodb": ["文档模型", "聚合管道", "索引策略", "分片集群", "副本集"],
            "rabbitmq": ["交换机类型", "消息确认", "死信队列", "延迟队列", "集群模式"],
        }
        all_derivs = deriv_map.get(tech.lower(), [])
        # breadth 1=无衍生, 2=1个, 3=2个, 4=3个, 5=全部
        if breadth <= 1:
            return []
        return all_derivs[:breadth - 1]

    # ==================== S7: 追问策略 ====================

    async def _generate_probing_strategy(
        self,
        knowledge_points: list[KnowledgePoint],
        resume: StructuredResume,
        jd_analysis: Optional[JDAnalysis],
        breadth: int,
        depth: int,
    ) -> ProbingPlan:
        # 按权重排序
        sorted_points = sorted(knowledge_points, key=lambda p: p.probing_weight, reverse=True)

        # 每个知识点直接用 depth 作为追问轮数
        for p in sorted_points:
            p.allocated_rounds = depth

        # LLM 生成问题链
        resume_summary = self._make_resume_summary(resume)
        jd_info = jd_analysis.model_dump_json(indent=2) if jd_analysis else "无目标岗位"
        kp_json = json.dumps([{"id": p.id, "name": p.name, "weight": p.probing_weight, "rounds": p.allocated_rounds} for p in sorted_points], ensure_ascii=False, indent=2)

        prompt = PROBING_STRATEGY_PROMPT.format(
            jd_info=jd_info,
            resume_summary=resume_summary,
            knowledge_points_json=kp_json,
            breadth=breadth,
            depth=depth,
        )

        try:
            response = await self.llm.generate_text(
                prompt=prompt,
                temperature=0.3,
                response_format={"type": "json_object"},
            )
            data = json.loads(_extract_json(response))
            updated_map = {u["id"]: u.get("probing_chain", []) for u in data.get("updated_points", [])}
            for p in sorted_points:
                if p.id in updated_map:
                    p.probing_chain = updated_map[p.id][:p.allocated_rounds]
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

    # ==================== S8: 前缀知识 ====================

    async def _generate_prefix_knowledge(self, top_points: list[KnowledgePoint]) -> list[PrefixKnowledge]:
        tech_list = []
        seen = set()
        for p in top_points:
            if p.category in ("tech_in_project", "fundamental") and p.name not in seen:
                tech_list.append(p.name)
                seen.add(p.name)

        if not tech_list:
            return []

        # 逐个技术点生成前缀知识，避免单次 prompt 过大导致超时
        results: list[PrefixKnowledge] = []
        for tech_name in tech_list:
            prompt = PREFIX_KNOWLEDGE_PROMPT.format(tech_list=json.dumps([tech_name], ensure_ascii=False))
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

    # ==================== S9: 组装 MD 报告 ====================

    def _assemble_md_report(
        self,
        resume: StructuredResume,
        jd_analysis: Optional[JDAnalysis],
        probing_plan: ProbingPlan,
        prefix_knowledge: list[PrefixKnowledge],
    ) -> str:
        parts = []
        pi = resume.personal_info

        # 标题
        parts.append("# 面试准备报告\n")
        parts.append(f"**候选人**: {pi.name}")
        if jd_analysis:
            parts.append(f"**目标岗位**: {jd_analysis.position_title}" + (f" @ {jd_analysis.company}" if jd_analysis.company else ""))
        else:
            parts.append("**模式**: 纯简历挖掘（无目标岗位）")
        parts.append(f"**总追问轮数**: {probing_plan.total_rounds}")
        parts.append("")

        # 一、概览
        parts.append("---\n")
        if jd_analysis:
            parts.append("## 一、岗位匹配概览\n")
            parts.append("| 维度 | 匹配度 | 说明 |")
            parts.append("|------|--------|------|")
            # 简单生成匹配度
            tech_match = self._calc_match_score(resume, jd_analysis)
            parts.append(f"| 技术栈 | {tech_match}% | JD 要求技术与简历技术栈对比 |")
            exp_years = resume.metadata.total_experience_months / 12 if resume.metadata else 0
            req_years = jd_analysis.required_years or 0
            exp_match = min(100, int(exp_years / req_years * 100)) if req_years > 0 else 90
            parts.append(f"| 经验年限 | {exp_match}% | 要求{req_years}年，候选人有{exp_years:.1f}年 |")
            parts.append("")
        else:
            parts.append("## 一、简历概览\n")
            exp = resume.metadata
            if exp:
                parts.append(f"- 总工作年限: {exp.total_experience_months / 12:.1f}年")
                parts.append(f"- 核心项目数: {exp.projects_count}个")
                parts.append(f"- 论文/专利: {exp.papers_count}篇/{exp.patents_count}项")
            parts.append("")

        # 二、前缀知识
        if prefix_knowledge:
            parts.append("---\n")
            parts.append("## 二、面试前缀知识\n")
            for pk in prefix_knowledge:
                parts.append(f"### {pk.tech_name}\n")
                if pk.core_concepts:
                    parts.append("**核心概念**: " + "、".join(pk.core_concepts))
                if pk.quick_reference:
                    parts.append(f"\n> {pk.quick_reference}\n")
                if pk.common_interview_topics:
                    parts.append("**常见考点**:")
                    for t in pk.common_interview_topics:
                        if isinstance(t, dict):
                            parts.append(f"- **{t.get('topic', '')}**: {t.get('answer', '')}")
                        else:
                            parts.append(f"- {t}")
                if pk.key_questions:
                    parts.append("**经典问题**:")
                    for q in pk.key_questions:
                        if isinstance(q, dict):
                            parts.append(f"- **Q: {q.get('question', '')}**")
                            parts.append(f"  {q.get('answer', '')}")
                        else:
                            parts.append(f"- {q}")
                if pk.pitfalls:
                    parts.append("**常见踩坑**: " + "、".join(pk.pitfalls))
                if pk.comparison:
                    parts.append("**对比**:")
                    for c in pk.comparison:
                        parts.append(f"- **{c.name}**: 优势={c.pros}, 劣势={c.cons}")
                parts.append("")

        # 三、追问详情（按模块）
        parts.append("---\n")
        parts.append("## 三、追问详情\n")

        # 按模块分组
        module_groups: dict[str, list[KnowledgePoint]] = {}
        for kp in probing_plan.knowledge_points:
            module_groups.setdefault(kp.module, []).append(kp)

        module_labels = {
            "project_experience": "项目经历",
            "work_experience": "工作经历",
            "papers": "论文发表",
            "patents": "专利",
            "skills": "技能验证",
        }

        # 按模块权重排序
        module_order = sorted(module_groups.keys(), key=lambda m: sum(kp.probing_weight for kp in module_groups[m]), reverse=True)

        for module in module_order:
            kps = module_groups[module]
            label = module_labels.get(module, module)
            parts.append(f"### 模块: {label}\n")

            if module == "project_experience":
                # 按项目分组
                proj_groups: dict[str, list[KnowledgePoint]] = {}
                for kp in kps:
                    proj_groups.setdefault(kp.source, []).append(kp)

                for proj_name, proj_kps in proj_groups.items():
                    proj_rounds = sum(kp.allocated_rounds for kp in proj_kps)
                    parts.append(f"#### 项目: {proj_name}（{proj_rounds}轮）\n")

                    # 找到对应的项目对象
                    proj_obj = next((p for p in resume.project_experience if p.name == proj_name), None)
                    if proj_obj:
                        if proj_obj.background:
                            parts.append(f"**背景**: {proj_obj.background}")
                        tech = ", ".join(proj_obj.tech_stack.languages + proj_obj.tech_stack.frameworks + proj_obj.tech_stack.middleware)
                        if tech:
                            parts.append(f"**技术栈**: {tech}")
                        if proj_obj.role:
                            parts.append(f"**角色**: {proj_obj.role}")
                        parts.append("")

                    parts.append("**追问记录**:")
                    q_idx = 1
                    for kp in proj_kps:
                        for q in kp.probing_chain[:kp.allocated_rounds]:
                            parts.append(f"{q_idx}. **Q**: {q}")
                            parts.append(f"   **A**: _（待追问填入）_")
                            q_idx += 1
                    parts.append("")

            elif module == "papers":
                for kp in kps:
                    paper_obj = next((p for p in resume.publications.papers if p.title == kp.name), None)
                    if paper_obj:
                        parts.append(f"#### 论文：《{paper_obj.title}》\n")
                        parts.append(f"**发表**: {paper_obj.venue}" + (f" ({paper_obj.venue_level})" if paper_obj.venue_level else ""))
                        parts.append(f"**作者排序**: 第{paper_obj.author_rank}作者" + ("（第一作者）" if paper_obj.is_first_author else ""))
                        if paper_obj.keywords:
                            parts.append(f"**关键词**: {', '.join(paper_obj.keywords)}")
                        parts.append(f"**追问轮数**: {kp.allocated_rounds}轮\n")
                    else:
                        parts.append(f"#### {kp.name}（{kp.allocated_rounds}轮）\n")

                    parts.append("**追问记录**:")
                    for i, q in enumerate(kp.probing_chain[:kp.allocated_rounds], 1):
                        parts.append(f"{i}. **Q**: {q}")
                        parts.append(f"   **A**: _（待追问填入）_")
                    parts.append("")

            elif module == "patents":
                for kp in kps:
                    parts.append(f"#### 专利: {kp.name}（{kp.allocated_rounds}轮）\n")
                    parts.append("**追问记录**:")
                    for i, q in enumerate(kp.probing_chain[:kp.allocated_rounds], 1):
                        parts.append(f"{i}. **Q**: {q}")
                        parts.append(f"   **A**: _（待追问填入）_")
                    parts.append("")

            else:
                for kp in kps:
                    parts.append(f"#### {kp.name}（{kp.allocated_rounds}轮）\n")
                    parts.append("**追问记录**:")
                    for i, q in enumerate(kp.probing_chain[:kp.allocated_rounds], 1):
                        parts.append(f"{i}. **Q**: {q}")
                        parts.append(f"   **A**: _（待追问填入）_")
                    parts.append("")

        # 四、追问总结（占位）
        parts.append("---\n")
        parts.append("## 四、追问总结\n")
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

    # ==================== S12: 最终报告（追问后） ====================

    def _assemble_final_md_report(
        self,
        resume: StructuredResume,
        jd_analysis: Optional[JDAnalysis],
        probing_plan: ProbingPlan,
        prefix_knowledge: list[PrefixKnowledge],
        qa_records: list[dict],
        preparation_advice: str = "",
    ) -> str:
        """组装最终报告，填入 Q&A + 面试准备建议"""
        # 构建按 kp_id 索引的 qa 记录
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
        parts.append("")

        # 一、概览
        parts.append("---\n")
        if jd_analysis:
            parts.append("## 一、岗位匹配概览\n")
            parts.append("| 维度 | 匹配度 | 说明 |")
            parts.append("|------|--------|------|")
            tech_match = self._calc_match_score(resume, jd_analysis)
            parts.append(f"| 技术栈 | {tech_match}% | JD 要求技术与简历技术栈对比 |")
            exp_years = resume.metadata.total_experience_months / 12 if resume.metadata else 0
            req_years = jd_analysis.required_years or 0
            exp_match = min(100, int(exp_years / req_years * 100)) if req_years > 0 else 90
            parts.append(f"| 经验年限 | {exp_match}% | 要求{req_years}年，候选人有{exp_years:.1f}年 |")
        else:
            parts.append("## 一、简历概览\n")
            exp = resume.metadata
            if exp:
                parts.append(f"- 总工作年限: {exp.total_experience_months / 12:.1f}年")
                parts.append(f"- 核心项目数: {exp.projects_count}个")
                parts.append(f"- 论文/专利: {exp.papers_count}篇/{exp.patents_count}项")
        parts.append("")

        # 二、前缀知识
        if prefix_knowledge:
            parts.append("---\n")
            parts.append("## 二、面试前缀知识\n")
            for pk in prefix_knowledge:
                parts.append(f"### {pk.tech_name}\n")
                if pk.core_concepts:
                    parts.append("**核心概念**: " + "、".join(pk.core_concepts))
                if pk.quick_reference:
                    parts.append(f"\n> {pk.quick_reference}\n")
                if pk.common_interview_topics:
                    parts.append("**常见考点**:")
                    for t in pk.common_interview_topics:
                        if isinstance(t, dict):
                            parts.append(f"- **{t.get('topic', '')}**: {t.get('answer', '')}")
                        else:
                            parts.append(f"- {t}")
                if pk.key_questions:
                    parts.append("**经典问题**:")
                    for q in pk.key_questions:
                        if isinstance(q, dict):
                            parts.append(f"- **Q: {q.get('question', '')}**")
                            parts.append(f"  {q.get('answer', '')}")
                        else:
                            parts.append(f"- {q}")
                if pk.pitfalls:
                    parts.append("**常见踩坑**: " + "、".join(pk.pitfalls))
                parts.append("")

        # 三、追问详情
        parts.append("---\n")
        parts.append("## 三、追问详情\n")

        module_groups: dict[str, list[KnowledgePoint]] = {}
        for kp in probing_plan.knowledge_points:
            module_groups.setdefault(kp.module, []).append(kp)

        module_labels = {
            "project_experience": "项目经历",
            "work_experience": "工作经历",
            "papers": "论文发表",
            "patents": "专利",
            "skills": "技能验证",
        }

        module_order = sorted(module_groups.keys(), key=lambda m: sum(kp.probing_weight for kp in module_groups[m]), reverse=True)

        for module in module_order:
            kps = module_groups[module]
            label = module_labels.get(module, module)
            parts.append(f"### 模块: {label}\n")

            if module == "project_experience":
                proj_groups: dict[str, list[KnowledgePoint]] = {}
                for kp in kps:
                    proj_groups.setdefault(kp.source, []).append(kp)

                for proj_name, proj_kps in proj_groups.items():
                    parts.append(f"#### 项目: {proj_name}\n")
                    proj_obj = next((p for p in resume.project_experience if p.name == proj_name), None)
                    if proj_obj:
                        if proj_obj.background:
                            parts.append(f"**背景**: {proj_obj.background}")
                        tech = ", ".join(proj_obj.tech_stack.languages + proj_obj.tech_stack.frameworks + proj_obj.tech_stack.middleware)
                        if tech:
                            parts.append(f"**技术栈**: {tech}")
                        if proj_obj.role:
                            parts.append(f"**角色**: {proj_obj.role}")
                        parts.append("")

                    for kp in proj_kps:
                        qa = qa_map.get(kp.id, [])
                        parts.append(f"##### {kp.name}（{len(qa)}轮）\n")
                        if qa:
                            for pair in qa:
                                score = pair.get("quality_score", 0)
                                parts.append(f"**Q{pair.get('round', '?')}:** {pair.get('question', '')}")
                                parts.append(f"**A:** {pair.get('answer', '')}")
                                parts.append(f"*深度评分: {score}*\n")
                        else:
                            parts.append("*追问未能生成*\n")
                    parts.append("")
            else:
                for kp in kps:
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

        # 四、面试准备建议（闭环测评）
        if preparation_advice:
            parts.append("---\n")
            parts.append("## 四、面试准备建议\n")
            parts.append(preparation_advice)
            parts.append("")
        elif qa_map:
            parts.append("---\n")
            parts.append("## 四、面试准备建议\n")
            parts.append("*面试准备建议生成失败，请稍后重试或联系管理员。*\n")

        return "\n".join(parts)
