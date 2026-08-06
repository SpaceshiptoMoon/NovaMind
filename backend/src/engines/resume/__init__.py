"""
Resume 引擎——简历结构化解析/分析报告/自动追问的纯逻辑编排层。
三引擎（ResumeParser/ResumeAnalyzer/AutoProbingEngine）经构造器注入端口，
零 features/setting import。引擎产物 Schema 随引擎走。
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