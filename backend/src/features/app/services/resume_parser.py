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
from src.shared.prompts import PromptTemplate, PromptManager
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
            self._parse_section("personal_info", personal_info_content, PromptTemplate.RESUME_PARSE_PERSONAL_INFO.value),
            self._parse_section("work_experience", sections.get("work_experience", ""), PromptTemplate.RESUME_PARSE_WORK_EXPERIENCE.value),
            self._parse_section("project_experience", sections.get("project_experience", ""), PromptTemplate.RESUME_PARSE_PROJECT_EXPERIENCE.value),
            self._parse_section("education", sections.get("education", ""), PromptTemplate.RESUME_PARSE_EDUCATION.value),
            self._parse_section("skills", sections.get("skills", ""), PromptTemplate.RESUME_PARSE_SKILLS.value),
            self._parse_section("publications", sections.get("publications", ""), PromptTemplate.RESUME_PARSE_PUBLICATIONS.value),
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

        prompt = PromptManager.format_prompt(PromptTemplate.RESUME_SECTION_SPLIT.value, numbered_text=numbered_text)
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

    async def _parse_section(self, section_type: str, content: str, template_name: str) -> dict | list:
        if not content.strip():
            return {} if section_type in ("personal_info", "skills", "publications") else []

        prompt = PromptManager.format_prompt(template_name, content=content)
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

    @staticmethod
    def _normalize_list_section(data) -> list[dict]:
        """归一化 LLM 返回的列表型章节数据

        处理两种常见异常格式:
        1. LLM 用 key 包裹: {"work_experience": [...]} → 提取内层列表
        2. 列表项为字符串: ["阿里 - 开发", ...] → 过滤掉
        """
        if data is None:
            return []
        # 情况 1: dict 包裹，提取唯一 value（如果是列表）
        if isinstance(data, dict):
            if len(data) == 1:
                val = next(iter(data.values()))
                if isinstance(val, list):
                    data = val
                else:
                    return []
            else:
                # 多 key 的 dict，尝试找第一个 list value
                for val in data.values():
                    if isinstance(val, list):
                        data = val
                        break
                else:
                    return []
        # 确保 data 是 list
        if not isinstance(data, list):
            return []
        # 情况 2: 过滤非 dict 项
        return [item for item in data if isinstance(item, dict)]

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
        work_experience = self._normalize_list_section(work_experience)
        work_experience = [self._clean_none(w) for w in work_experience]
        project_experience = self._normalize_list_section(project_experience)
        project_experience = [self._clean_none(p) for p in project_experience]
        education = self._normalize_list_section(education)
        education = [self._clean_none(e) for e in education]
        skills_data = self._clean_none(skills_data) if skills_data else {}
        publications = self._clean_none(publications) if publications else {}

        resume = StructuredResume(
            personal_info=PersonalInfo(**personal_info) if personal_info else PersonalInfo(),
            work_experience=[WE(**w) for w in work_experience],
            project_experience=[PE(**p) for p in project_experience],
            education=[EducationExperience(**e) for e in education],
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
