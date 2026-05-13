"""
简历挖掘 Schema — 结构化数据模型 + 请求/响应

所有字段均有默认值，兼容各种格式的简历和 LLM 输出。
"""
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict


# ==================== 结构化简历数据模型 ====================

class PersonalInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = ""
    phone: str = ""
    email: str = ""
    location: str = ""
    age: Optional[int] = None
    gender: str = ""
    summary: str = ""
    job_intention: Optional[dict] = None
    social_links: list[dict] = []


class EducationExperience(BaseModel):
    model_config = ConfigDict(extra="ignore")

    school: str = ""
    major: str = ""
    degree: str = ""
    start_date: str = ""
    end_date: str = ""
    gpa: str = ""
    gpa_ranking: str = ""
    thesis_title: str = ""
    thesis_advisor: str = ""
    core_courses: list[str] = []
    highlights: list[str] = []
    research_direction: str = ""


class Achievement(BaseModel):
    model_config = ConfigDict(extra="ignore")

    description: str = ""
    metric: str = ""
    impact: str = ""


class WorkProjectRef(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = ""
    role: str = ""
    brief: str = ""


class Promotion(BaseModel):
    model_config = ConfigDict(extra="ignore")

    date: str = ""
    from_level: str = ""
    to_level: str = ""
    reason: str = ""


class WorkExperience(BaseModel):
    model_config = ConfigDict(extra="ignore")

    company: str = ""
    company_brief: str = ""
    position: str = ""
    department: str = ""
    level: str = ""
    employment_type: str = "fulltime"
    start_date: str = ""
    end_date: str = ""
    duration_months: int = 0
    is_current: bool = False
    team_context: str = ""
    responsibilities: list[str] = []
    key_projects: list[WorkProjectRef] = []
    achievements: list[Achievement] = []
    tech_stack: list[str] = []
    promotion_history: list[Promotion] = []
    leave_reason: str = ""


class TechStackDetail(BaseModel):
    model_config = ConfigDict(extra="ignore")

    languages: list[str] = []
    frameworks: list[str] = []
    middleware: list[str] = []
    infrastructure: list[str] = []
    tools: list[str] = []


class Challenge(BaseModel):
    model_config = ConfigDict(extra="ignore")

    challenge: str = ""
    solution: str = ""
    result: str = ""


class ProjectExperience(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = ""
    source: str = "work"
    associated_company: str = ""
    role: str = ""
    team_size: int = 0
    my_contribution_ratio: str = ""
    start_date: str = ""
    end_date: str = ""
    duration_months: int = 0
    background: str = ""
    tech_stack: TechStackDetail = Field(default_factory=TechStackDetail)
    architecture: str = ""
    responsibilities: list[str] = []
    challenges: list[Challenge] = []
    achievements: list[Achievement] = []
    highlights: list[str] = []
    probing_directions: list[str] = []


class SkillItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = ""
    proficiency: str = ""
    years: int = 0
    source_projects: list[str] = []


class SkillGroup(BaseModel):
    model_config = ConfigDict(extra="ignore")

    category: str = ""
    label: str = ""
    items: list[SkillItem] = []


class Certification(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = ""
    date: str = ""


class LanguageSkill(BaseModel):
    model_config = ConfigDict(extra="ignore")

    language: str = ""
    proficiency: str = ""
    certificate: str = ""


class SkillsData(BaseModel):
    model_config = ConfigDict(extra="ignore")

    skill_groups: list[SkillGroup] = []
    certifications: list[Certification] = []
    languages: list[LanguageSkill] = []


class Paper(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str = ""
    authors: list[str] = []
    author_rank: int = 0
    is_first_author: bool = False
    venue: str = ""
    venue_level: str = ""
    publication_date: str = ""
    paper_type: str = ""
    citations: int = 0
    abstract: str = ""
    keywords: list[str] = []
    my_contribution: str = ""
    related_project: str = ""


class Patent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str = ""
    patent_type: str = ""
    patent_number: str = ""
    status: str = ""
    filing_date: str = ""
    inventors: list[str] = []
    inventor_rank: int = 0
    brief: str = ""


class TechnicalWriting(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str = ""
    platform: str = ""
    url: str = ""
    publish_date: str = ""
    views: int = 0
    likes: int = 0


class PublicationsData(BaseModel):
    model_config = ConfigDict(extra="ignore")

    papers: list[Paper] = []
    patents: list[Patent] = []
    technical_writings: list[TechnicalWriting] = []


class ResumeMetadata(BaseModel):
    model_config = ConfigDict(extra="ignore")

    parse_time: str = ""
    source_file: str = ""
    total_experience_months: int = 0
    companies_count: int = 0
    projects_count: int = 0
    papers_count: int = 0
    patents_count: int = 0


class ValidationWarning(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: str = ""
    message: str = ""
    severity: str = "info"
    suggestion: str = ""


class StructuredResume(BaseModel):
    model_config = ConfigDict(extra="ignore")

    personal_info: PersonalInfo = Field(default_factory=PersonalInfo)
    education: list[EducationExperience] = []
    work_experience: list[WorkExperience] = []
    project_experience: list[ProjectExperience] = []
    skills: SkillsData = Field(default_factory=SkillsData)
    publications: PublicationsData = Field(default_factory=PublicationsData)
    metadata: Optional[ResumeMetadata] = None
    validation_warnings: list[ValidationWarning] = []


# ==================== JD 分析模型 ====================

class JDSkill(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = ""
    category: str = ""
    importance: str = "required"
    level: str = ""
    context: str = ""


class JDAnalysis(BaseModel):
    model_config = ConfigDict(extra="ignore")

    position_title: str = ""
    company: str = ""
    seniority_level: str = ""
    required_years: int = 0
    required_skills: list[JDSkill] = []
    preferred_skills: list[JDSkill] = []
    required_experience: list[str] = []
    domain_knowledge: list[str] = []
    soft_skills: list[str] = []
    responsibilities: list[str] = []


# ==================== 追问计划模型 ====================

class KnowledgePoint(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = ""
    name: str = ""
    category: str = ""
    module: str = ""
    source: str = ""
    jd_relevance: float = 0.5
    resume_depth: float = 0.0
    probing_weight: float = 0.0
    allocated_rounds: int = 1
    derivatives: list[str] = []
    probing_chain: list[str] = []


class ProjectPriority(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = ""
    weight: float = 0.0
    allocated_rounds: int = 0


class ProbingPlan(BaseModel):
    model_config = ConfigDict(extra="ignore")

    knowledge_points: list[KnowledgePoint] = []
    project_priorities: list[ProjectPriority] = []
    total_rounds: int = 30
    rounds_distribution: dict = {}
    has_jd: bool = False


# ==================== 前缀知识模型 ====================

class ComparisonItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = ""
    pros: str = ""
    cons: str = ""


class TopicWithAnswer(BaseModel):
    model_config = ConfigDict(extra="ignore")

    topic: str = ""
    answer: str = ""


class QuestionWithAnswer(BaseModel):
    model_config = ConfigDict(extra="ignore")

    question: str = ""
    answer: str = ""


class PrefixKnowledge(BaseModel):
    model_config = ConfigDict(extra="ignore")

    tech_name: str = ""
    category: str = ""
    core_concepts: list[str] = []
    common_interview_topics: list[TopicWithAnswer] = []
    key_questions: list[QuestionWithAnswer] = []
    quick_reference: str = ""
    pitfalls: list[str] = []
    comparison: list[ComparisonItem] = []


# ==================== 请求/响应 ====================

class ResumeUploadRequest(BaseModel):
    jd_text: str = ""
    config: dict = {}


class ResumeSessionResponse(BaseModel):
    id: str
    user_id: int
    resume_filename: str = ""
    structured_resume: Optional[StructuredResume] = None
    jd_text: str = ""
    md_report_url: Optional[str] = None
    status: int
    config: dict = {}
    error_message: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ResumeSessionListResponse(BaseModel):
    sessions: list[ResumeSessionResponse]
    total: int
