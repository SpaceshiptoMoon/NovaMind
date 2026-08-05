"""Resume 引擎——简历结构化解析 / 分析报告 / 自动追问的纯逻辑编排层。

三引擎（``ResumeParser`` / ``ResumeAnalyzer`` / ``AutoProbingEngine``）从
``features/app/services/`` 迁入，prompt/log/WebSearch/降级 LLM 经构造器注入端口
（``PromptProvider`` / ``Logger`` / ``WebSearchPort`` / ``FallbackLLMProvider``），
引擎零 ``features`` / ``setting`` import。引擎产物 Schema（``StructuredResume``
等）跟引擎走，归 ``engines/resume/schemas.py``——引擎产出契约随引擎，feature 侧
API DTO 反向引用（feature -> engine 合法）。

宿主编排（DB/MinIO/ModelConfigService/arq）留 ``features/app/services/resume_pipeline_service.py``，
装配点构造端口适配器并注入引擎。
"""
from novamind.engines.resume.resume_parser import ResumeParser
from novamind.engines.resume.resume_analyzer import ResumeAnalyzer
from novamind.engines.resume.resume_probing import AutoProbingEngine
from novamind.engines.resume.schemas import (
    JDAnalysis,
    KnowledgePoint,
    PrefixKnowledge,
    ProbingPlan,
    ProjectPriority,
    StructuredResume,
    WorkProjectUnit,
)

__all__ = [
    "ResumeParser",
    "ResumeAnalyzer",
    "AutoProbingEngine",
    "StructuredResume",
    "JDAnalysis",
    "ProbingPlan",
    "KnowledgePoint",
    "ProjectPriority",
    "PrefixKnowledge",
    "WorkProjectUnit",
]