"""
S1-S4: 简历结构化解析 Pipeline

Pipeline:
  S1: 文本提取 (PDF/DOCX → raw_text)
  S2: 章节切割 (LLM → sections)
  S3: 并行深度解析 (6 路 LLM → 结构化数据)
  S4: 交叉校验 (程序化 → 校验后数据)
"""
import asyncio
import json
import os
import tempfile
from typing import Optional

from src.core.middleware.structured_logging import get_logger
from src.shared.ai_models.llm import BaseLLM
from src.shared.utils.document_readers.pdf_reader import PDFReader
from src.shared.utils.document_readers.docx_reader import DocxReader
from src.features.app.schemas.resume_schema import StructuredResume

logger = get_logger(__name__)


def _extract_json(text: str) -> str:
    """从 LLM 输出中提取 JSON，兼容 markdown 代码块包裹"""
    text = text.strip()
    if not text:
        raise ValueError("LLM 返回空内容")
    # 已经是合法 JSON
    if text.startswith("{") or text.startswith("["):
        return text
    # 尝试提取 ```json ... ``` 或 ``` ... ``` 包裹的内容
    import re
    m = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    # 兜底：找第一个 { 或 [ 到最后一个 } 或 ]
    start = -1
    for ch in ("{", "["):
        idx = text.find(ch)
        if idx >= 0 and (start < 0 or idx < start):
            start = idx
    if start >= 0:
        return text[start:]
    raise ValueError(f"无法从 LLM 输出中提取 JSON: {text[:200]}")

# ==================== Prompt 模板 ====================

SECTION_SPLIT_PROMPT = """你是一个简历结构分析器。请识别以下简历文本（带行号）的章节边界。

章节类型只能是以下之一：
- personal_info（个人信息）
- education（教育经历）
- work_experience（工作经历）
- project_experience（项目经历）
- skills（技能）
- publications（论文/专利）
- certifications（证书/资质）
- awards（获奖经历）
- other（其他）

请严格按以下 JSON 格式输出每个章节的起止行号：
{{
  "sections": [
    {{ "type": "personal_info", "start_line": 1, "end_line": 5 }},
    {{ "type": "work_experience", "start_line": 6, "end_line": 20 }},
    ...
  ]
}}

注意：
1. 行号对应下面带行号的文本中 [数字] 后的内容
2. 如果某章节不存在则不输出
3. 只输出 JSON，不要输出其他内容

带行号的简历内容：
{numbered_text}
"""

PARSE_PERSONAL_INFO_PROMPT = """从以下个人信息内容中提取结构化数据。

请严格按以下 JSON 格式输出：
{{
  "name": "姓名",
  "phone": "电话",
  "email": "邮箱",
  "location": "所在地",
  "age": null,
  "gender": "性别",
  "summary": "个人简介/求职意向",
  "job_intention": {{
    "target_position": "目标职位",
    "target_salary": "期望薪资",
    "current_status": "当前状态"
  }},
  "social_links": [
    {{ "platform": "GitHub", "url": "..." }}
  ]
}}

字段缺失时用空字符串或 null。只输出 JSON。

内容：
{content}
"""

PARSE_WORK_EXPERIENCE_PROMPT = """从以下工作经历内容中提取结构化数据。输出 JSON 数组，每段工作经历一个对象。

每个工作经历对象格式：
{{
  "company": "公司名称",
  "company_brief": "公司简介（一句话）",
  "position": "职位",
  "department": "部门",
  "level": "职级",
  "employment_type": "fulltime/intern/parttime",
  "start_date": "YYYY.MM",
  "end_date": "YYYY.MM 或 至今",
  "duration_months": 0,
  "is_current": false,
  "team_context": "团队规模和职责范围描述",
  "responsibilities": ["职责1", "职责2"],
  "key_projects": [
    {{ "name": "项目名", "role": "角色", "brief": "简介" }}
  ],
  "achievements": [
    {{ "description": "成果描述", "metric": "量化指标", "impact": "high/medium/low" }}
  ],
  "tech_stack": ["技术1", "技术2"],
  "promotion_history": [
    {{ "date": "YYYY.MM", "from_level": "", "to_level": "", "reason": "" }}
  ],
  "leave_reason": ""
}}

注意：
1. 尽量从描述中提取量化数据（百分比、倍数、具体数值）
2. 日期统一为 YYYY.MM 格式，"至今"保持原文
3. duration_months 需要计算
4. 只输出 JSON 数组

内容：
{content}
"""

PARSE_PROJECT_EXPERIENCE_PROMPT = """从以下项目经历内容中提取结构化数据。输出 JSON 数组，每个项目一个对象。

每个项目对象格式：
{{
  "name": "项目名称",
  "source": "work/personal/education/open_source",
  "associated_company": "关联公司（如果是工作项目）",
  "role": "担任角色",
  "team_size": 0,
  "my_contribution_ratio": "贡献占比",
  "start_date": "YYYY.MM",
  "end_date": "YYYY.MM",
  "duration_months": 0,
  "background": "项目背景和目标",
  "tech_stack": {{
    "languages": [],
    "frameworks": [],
    "middleware": [],
    "infrastructure": [],
    "tools": []
  }},
  "architecture": "架构描述",
  "responsibilities": ["负责内容1"],
  "challenges": [
    {{
      "challenge": "遇到的挑战",
      "solution": "解决方案",
      "result": "结果"
    }}
  ],
  "achievements": [
    {{ "description": "成果描述", "metric": "量化指标", "impact": "high/medium/low" }}
  ],
  "highlights": ["可追问的亮点"],
  "probing_directions": ["建议追问方向1", "建议追问方向2"]
}}

注意：
1. 技术栈要分层归类到对应数组中
2. 挑战和成果尽量提取量化数据
3. probing_directions 是面试官可以追问的方向（生成 3-5 个）
4. 只输出 JSON 数组

内容：
{content}
"""

PARSE_EDUCATION_PROMPT = """从以下教育经历内容中提取结构化数据。输出 JSON 数组。

格式：
{{
  "school": "学校",
  "major": "专业",
  "degree": "bachelor/master/phd/associate",
  "start_date": "YYYY.MM",
  "end_date": "YYYY.MM",
  "gpa": "GPA",
  "gpa_ranking": "排名",
  "thesis_title": "论文题目",
  "thesis_advisor": "导师",
  "core_courses": ["课程1"],
  "highlights": ["奖学金/竞赛等"],
  "research_direction": "研究方向"
}}

字段缺失留空字符串或空数组。只输出 JSON 数组。

内容：
{content}
"""

PARSE_SKILLS_PROMPT = """从以下技能相关内容中提取结构化数据。

格式：
{{
  "skill_groups": [
    {{
      "category": "programming_languages",
      "label": "编程语言",
      "items": [
        {{ "name": "Python", "proficiency": "expert/proficient/familiar", "years": 5, "source_projects": ["项目A"] }}
      ]
    }}
  ],
  "certifications": [
    {{ "name": "证书名", "date": "YYYY.MM" }}
  ],
  "languages": [
    {{ "language": "英语", "proficiency": "流利", "certificate": "CET-6 580" }}
  ]
}}

skill_groups 的 category 可选值：programming_languages, frameworks, middleware, infrastructure, databases, devops, soft_skills, other
proficiency 根据"精通/熟练/了解"等词判断，没有描述则留空。
source_projects 如果能从上下文推断则填写。
只输出 JSON。

内容：
{content}
"""

PARSE_PUBLICATIONS_PROMPT = """从以下论文/专利/技术写作相关内容中提取结构化数据。

格式：
{{
  "papers": [
    {{
      "title": "论文标题",
      "authors": ["作者1", "作者2"],
      "author_rank": 1,
      "is_first_author": true,
      "venue": "发表场所",
      "venue_level": "CCF-A/B/C 或空",
      "publication_date": "YYYY.MM",
      "paper_type": "conference/journal/preprint",
      "citations": 0,
      "abstract": "摘要",
      "keywords": ["关键词"],
      "my_contribution": "个人贡献描述",
      "related_project": "关联项目名"
    }}
  ],
  "patents": [
    {{
      "title": "专利标题",
      "patent_type": "invention/utility/design",
      "patent_number": "",
      "status": "pending/granted",
      "filing_date": "YYYY.MM",
      "inventors": ["发明人1"],
      "inventor_rank": 1,
      "brief": "简介"
    }}
  ],
  "technical_writings": [
    {{
      "title": "文章标题",
      "platform": "平台",
      "url": "",
      "publish_date": "YYYY.MM",
      "views": 0,
      "likes": 0
    }}
  ]
}}

没有的字段留空或空数组。只输出 JSON。

内容：
{content}
"""


class ResumeParser:
    """简历结构化解析器"""

    def __init__(self, llm_client: BaseLLM):
        self.llm = llm_client

    async def parse(self, file_bytes: bytes, filename: str) -> StructuredResume:
        """完整解析流程 S1 → S4"""
        # S1: 文本提取
        raw_text = await self._extract_text(file_bytes, filename)
        logger.info("简历文本提取完成", filename=filename, text_len=len(raw_text))

        # S2: 章节切割
        sections = await self._split_sections(raw_text)
        logger.info("章节切割完成", sections=list(sections.keys()))

        # personal_info 补充全文开头，防止章节切割行号偏差导致 summary 被截断
        raw_lines = raw_text.split("\n")
        personal_info_content = sections.get("personal_info", "")
        raw_head = "\n".join(raw_lines[:20])
        if raw_head not in personal_info_content:
            personal_info_content = raw_head + "\n\n--- 以上为简历全文开头 ---\n\n" + personal_info_content

        # S3: 并行深度解析
        results = await asyncio.gather(
            self._parse_section("personal_info", personal_info_content, PARSE_PERSONAL_INFO_PROMPT),
            self._parse_section("work_experience", sections.get("work_experience", ""), PARSE_WORK_EXPERIENCE_PROMPT),
            self._parse_section("project_experience", sections.get("project_experience", ""), PARSE_PROJECT_EXPERIENCE_PROMPT),
            self._parse_section("education", sections.get("education", ""), PARSE_EDUCATION_PROMPT),
            self._parse_section("skills", sections.get("skills", ""), PARSE_SKILLS_PROMPT),
            self._parse_section("publications", sections.get("publications", ""), PARSE_PUBLICATIONS_PROMPT),
            return_exceptions=True,
        )

        section_names = ["personal_info", "work_experience", "project_experience", "education", "skills", "publications"]
        section_defaults = [
            {},
            [],
            [],
            [],
            {"skill_groups": [], "certifications": [], "languages": []},
            {"papers": [], "patents": [], "technical_writings": []},
        ]
        parsed = []
        for i, (name, default) in enumerate(zip(section_names, section_defaults)):
            if isinstance(results[i], Exception):
                logger.warning("章节并行解析失败，使用默认值", section=name, error=str(results[i]))
                parsed.append(default)
            else:
                parsed.append(results[i])

        personal_info = parsed[0]
        work_experience = parsed[1]
        project_experience = parsed[2]
        education = parsed[3]
        skills_data = parsed[4]
        publications = parsed[5]

        # S4: 组装 + 交叉校验
        resume = self._assemble_resume(
            raw_text=raw_text,
            filename=filename,
            personal_info=personal_info,
            work_experience=work_experience,
            project_experience=project_experience,
            education=education,
            skills_data=skills_data,
            publications=publications,
        )

        resume = self._cross_validate(resume)
        logger.info("简历解析完成", projects=len(resume.project_experience), works=len(resume.work_experience))

        return resume

    # ==================== S1: 文本提取 ====================

    async def _extract_text(self, file_bytes: bytes, filename: str) -> str:
        ext = os.path.splitext(filename)[1].lower()

        # 扩展名白名单校验，防止临时文件安全风险
        ALLOWED_EXTS = {".pdf", ".docx", ".doc", ".txt", ".md"}
        if ext not in ALLOWED_EXTS:
            raise ValueError(f"不支持的文件格式: {ext}")

        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name

        try:
            if ext == ".pdf":
                reader = PDFReader()
                docs = await reader.load_data(tmp_path)
            elif ext in (".docx", ".doc"):
                reader = DocxReader()
                docs = await reader.load_data(tmp_path)
            elif ext in (".txt", ".md"):
                with open(tmp_path, "r", encoding="utf-8", errors="ignore") as f:
                    return f.read()
            else:
                raise ValueError(f"不支持的文件格式: {ext}")

            return "\n".join(doc.get("text", "") for doc in docs)
        finally:
            os.unlink(tmp_path)

    # ==================== S2: 章节切割 ====================

    async def _split_sections(self, raw_text: str) -> dict[str, str]:
        # 生成带行号的文本
        lines = raw_text.split("\n")
        numbered_text = "\n".join(f"[{i+1}] {lines[i]}" for i in range(len(lines)))

        prompt = SECTION_SPLIT_PROMPT.format(numbered_text=numbered_text)
        response = await self.llm.generate_text(
            prompt=prompt,
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        data = json.loads(_extract_json(response))
        sections = {}
        for sec in data.get("sections", []):
            sec_type = sec.get("type", "other")
            start = sec.get("start_line", 1) - 1  # 转为 0-based index
            end = sec.get("end_line", len(lines))
            start = max(0, min(start, len(lines)))
            end = max(start, min(end, len(lines)))
            sections[sec_type] = "\n".join(lines[start:end])
        return sections

    # ==================== S3: 并行深度解析 ====================

    async def _parse_section(self, section_type: str, content: str, prompt_template: str) -> dict | list:
        if not content.strip():
            return {} if section_type in ("personal_info", "skills", "publications") else []

        prompt = prompt_template.format(content=content)
        try:
            response = await self.llm.generate_text(
                prompt=prompt,
                temperature=0.1,
                response_format={"type": "json_object"},
            )
            return json.loads(_extract_json(response))
        except json.JSONDecodeError as e:
            logger.warning("章节解析 JSON 失败，尝试不带 response_format 重试", section=section_type, error=str(e))
            try:
                response = await self.llm.generate_text(
                    prompt=prompt + "\n\n请只输出合法 JSON，不要包含任何其他内容。",
                    temperature=0.1,
                )
                return json.loads(_extract_json(response))
            except Exception as e2:
                logger.error("章节解析重试仍失败", section=section_type, error=str(e2))
                return {} if section_type in ("personal_info", "skills", "publications") else []
        except Exception as e:
            logger.error("章节解析失败", section=section_type, error=str(e))
            return {} if section_type in ("personal_info", "skills", "publications") else []

    # ==================== S4: 交叉校验 ====================

    @staticmethod
    def _clean_none(obj):
        """递归清理 LLM 输出中的 None 值，替换为类型安全的默认值"""
        if isinstance(obj, dict):
            return {k: ResumeParser._clean_none(v) for k, v in obj.items() if v is not None}
        if isinstance(obj, list):
            return [ResumeParser._clean_none(item) for item in obj if item is not None]
        return obj

    def _assemble_resume(
        self,
        raw_text: str,
        filename: str,
        personal_info: dict,
        work_experience: list,
        project_experience: list,
        education: list,
        skills_data: dict,
        publications: dict,
    ) -> StructuredResume:
        from src.features.app.schemas.resume_schema import (
            PersonalInfo, WorkExperience as WE, ProjectExperience as PE,
            EducationExperience, SkillsData as SD, PublicationsData as PD,
            ResumeMetadata,
        )

        # 清理 LLM 输出中的 None 值
        personal_info = self._clean_none(personal_info) if personal_info else {}
        work_experience = [self._clean_none(w) for w in (work_experience or [])]
        project_experience = [self._clean_none(p) for p in (project_experience or [])]
        education = [self._clean_none(e) for e in (education or [])]
        skills_data = self._clean_none(skills_data) if skills_data else {}
        publications = self._clean_none(publications) if publications else {}

        resume = StructuredResume(
            personal_info=PersonalInfo(**personal_info) if personal_info else PersonalInfo(),
            work_experience=[WE(**w) for w in (work_experience or [])],
            project_experience=[PE(**p) for p in (project_experience or [])],
            education=[EducationExperience(**e) for e in (education or [])],
            skills=SD(**skills_data) if skills_data else SD(),
            publications=PD(**publications) if publications else PD(),
            metadata=ResumeMetadata(
                source_file=filename,
                projects_count=len(project_experience or []),
                papers_count=len((publications or {}).get("papers", [])),
                patents_count=len((publications or {}).get("patents", [])),
            ),
        )

        # 计算总工作月数和公司数
        if resume.work_experience:
            total_months = sum(w.duration_months for w in resume.work_experience)
            resume.metadata.companies_count = len(resume.work_experience)
            resume.metadata.total_experience_months = total_months

        return resume

    def _cross_validate(self, resume: StructuredResume) -> StructuredResume:
        from src.features.app.schemas.resume_schema import ValidationWarning

        warnings = []

        # 1. 项目-工作时间校验
        work_companies = {}
        for w in resume.work_experience:
            work_companies[w.company] = w

        for p in resume.project_experience:
            if p.associated_company and p.associated_company in work_companies:
                work = work_companies[p.associated_company]
                # 简单检查：如果项目有结束日期且在工作开始之前，可能有冲突
                # 这里只做提示性校验
                pass

        # 2. 成果量化检查
        for w in resume.work_experience:
            for a in w.achievements:
                if not a.metric:
                    warnings.append(ValidationWarning(
                        type="missing_metric",
                        message=f"工作经历「{w.company}」的成果「{a.description[:30]}」缺少量化数据",
                        severity="warning",
                        suggestion="追问：这个成果具体提升了多少？有数据支撑吗？",
                    ))

        for p in resume.project_experience:
            for a in p.achievements:
                if not a.metric:
                    warnings.append(ValidationWarning(
                        type="missing_metric",
                        message=f"项目「{p.name}」的成果「{a.description[:30]}」缺少量化数据",
                        severity="warning",
                        suggestion="追问：具体提升了多少？有量化指标吗？",
                    ))

        resume.validation_warnings = warnings
        return resume
