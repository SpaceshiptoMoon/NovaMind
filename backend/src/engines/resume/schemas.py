"""
简历挖掘 Schema — 结构化数据模型 + 请求/响应

所有字段均有默认值，兼容各种格式的简历和 LLM 输出。
"""

from pydantic import BaseModel, ConfigDict, Field

# ==================== 结构化简历数据模型 ====================

class PersonalInfo(BaseModel):
    """候选人基本信息（姓名/联系方式/所在地/个人简介/求职意向/社交链接）。"""
    model_config = ConfigDict(extra="ignore")

    name: str = ""
    phone: str = ""
    email: str = ""
    location: str = ""
    age: int | None = None
    gender: str = ""
    summary: str = ""
    job_intention: dict | None = None
    social_links: list[dict] = []


class EducationExperience(BaseModel):
    """单段教育经历（学校/专业/学位/GPA/论文/核心课程）。"""
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
    """单条量化成果（描述/指标/影响）。"""
    model_config = ConfigDict(extra="ignore")

    description: str = ""
    metric: str = ""
    impact: str = ""


class WorkProjectRef(BaseModel):
    """工作经历内嵌项目的轻量引用（名称/角色/简述）。"""
    model_config = ConfigDict(extra="ignore")

    name: str = ""
    role: str = ""
    brief: str = ""


class Promotion(BaseModel):
    """单次晋升记录（时间/前后职级/理由）。"""
    model_config = ConfigDict(extra="ignore")

    date: str = ""
    from_level: str = ""
    to_level: str = ""
    reason: str = ""


class WorkExperience(BaseModel):
    """单段工作经历（公司/职位/时间/职责要点/关键项目/晋升史/离职原因）。"""
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
    """分类技术栈明细（语言/框架/中间件/基础设施/工具）。"""
    model_config = ConfigDict(extra="ignore")

    languages: list[str] = []
    frameworks: list[str] = []
    middleware: list[str] = []
    infrastructure: list[str] = []
    tools: list[str] = []


class Challenge(BaseModel):
    """单条挑战应对（挑战/解决方案/结果）。"""
    model_config = ConfigDict(extra="ignore")

    challenge: str = ""
    solution: str = ""
    result: str = ""


class ProjectExperience(BaseModel):
    """单段项目经历（背景/角色/技术栈/职责/挑战/成果/亮点/可追问方向）。"""
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
    """单条技能项（名称/熟练度/年限/来源项目）。"""
    model_config = ConfigDict(extra="ignore")

    name: str = ""
    proficiency: str = ""
    years: int = 0
    source_projects: list[str] = []


class SkillGroup(BaseModel):
    """按类别聚合的技能组（类别/标签/技能项列表）。"""
    model_config = ConfigDict(extra="ignore")

    category: str = ""
    label: str = ""
    items: list[SkillItem] = []


class Certification(BaseModel):
    """单条职业认证（名称/获得时间）。"""
    model_config = ConfigDict(extra="ignore")

    name: str = ""
    date: str = ""


class LanguageSkill(BaseModel):
    """单条语言能力（语言/熟练度/证书）。"""
    model_config = ConfigDict(extra="ignore")

    language: str = ""
    proficiency: str = ""
    certificate: str = ""


class SkillsData(BaseModel):
    """技能总览（技能组/认证/语言能力三类聚合）。"""
    model_config = ConfigDict(extra="ignore")

    skill_groups: list[SkillGroup] = []
    certifications: list[Certification] = []
    languages: list[LanguageSkill] = []


class Paper(BaseModel):
    """单篇论文（标题/作者排序/发表载体/引用数/个人贡献/关联项目）。"""
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
    """单项专利（类型/号/状态/申请时间/发明人排序/简述）。"""
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
    """单篇技术文章（平台/链接/发布时间/浏览与点赞数）。"""
    model_config = ConfigDict(extra="ignore")

    title: str = ""
    platform: str = ""
    url: str = ""
    publish_date: str = ""
    views: int = 0
    likes: int = 0


class PublicationsData(BaseModel):
    """学术成果总览（论文/专利/技术文章三类聚合）。"""
    model_config = ConfigDict(extra="ignore")

    papers: list[Paper] = []
    patents: list[Patent] = []
    technical_writings: list[TechnicalWriting] = []


class ResumeMetadata(BaseModel):
    """解析元数据（源文件/总工作月数/公司与项目等计数）。"""
    model_config = ConfigDict(extra="ignore")

    parse_time: str = ""
    source_file: str = ""
    total_experience_months: int = 0
    companies_count: int = 0
    projects_count: int = 0
    papers_count: int = 0
    patents_count: int = 0


class ValidationWarning(BaseModel):
    """交叉校验警告（类型/消息/严重度/追问建议）。"""
    model_config = ConfigDict(extra="ignore")

    type: str = ""
    message: str = ""
    severity: str = "info"
    suggestion: str = ""


class StructuredResume(BaseModel):
    """结构化简历聚合根：个人信息 + 教育/工作/项目经历 + 技能与学术成果 + 校验警告。"""
    model_config = ConfigDict(extra="ignore")

    personal_info: PersonalInfo = Field(default_factory=PersonalInfo)
    education: list[EducationExperience] = []
    work_experience: list[WorkExperience] = []
    project_experience: list[ProjectExperience] = []
    skills: SkillsData = Field(default_factory=SkillsData)
    publications: PublicationsData = Field(default_factory=PublicationsData)
    metadata: ResumeMetadata | None = None
    validation_warnings: list[ValidationWarning] = []
    resume_summary: str = ""


# ==================== JD 分析模型 ====================

class JDSkill(BaseModel):
    """JD 中的单条技能要求（名称/类别/必需或优选/程度要求）。"""
    model_config = ConfigDict(extra="ignore")

    name: str = ""
    category: str = ""
    importance: str = "required"
    level: str = ""
    context: str = ""


class JDAnalysis(BaseModel):
    """JD 结构化分析（岗位/公司/年资要求/必备与优选技能/软素质/职责）。"""
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


# ==================== 工作-项目合并单元 ====================

class WorkProjectUnit(BaseModel):
    """工作-项目合并单元：以公司+岗位为维度的整体追问上下文"""
    model_config = ConfigDict(extra="ignore")

    # 公司维度
    id: str = ""
    company: str = ""
    company_brief: str = ""
    position: str = ""
    department: str = ""
    employment_type: str = ""              # fulltime / intern / parttime
    work_period: str = ""                  # 2023.06 ~ 2024.03
    work_responsibilities: list[str] = []
    work_tech_stack: list[str] = []

    # 公司/岗位背景补充（搜索引擎 + LLM 生成）
    company_industry: str = ""             # 公司所在行业
    company_scale: str = ""                # 公司规模（如适用）
    position_context: str = ""             # 岗位定位描述
    industry_context: str = ""             # 行业背景（技术特点和关注点）

    # 关联项目
    projects: list[ProjectExperience] = []

    # 复杂度评估
    complexity_score: float = 0.0          # 综合复杂度分数 0-1
    complexity_reasoning: str = ""         # 复杂度评估理由
    allocated_rounds: int = 3              # 自动分配的追问轮数

    # 综合追问上下文（合并后自动构建）
    full_context: str = ""


# ==================== 追问计划模型 ====================

class KnowledgePoint(BaseModel):
    """可追问知识点（类别/来源/JD 相关性与简历深度加权/分配轮数/追问链）。"""
    model_config = ConfigDict(extra="ignore")

    id: str = ""
    name: str = ""
    category: str = ""                     # project / tech_in_project / fundamental / paper / patent
    module: str = ""
    source: str = ""
    context: str = ""
    jd_relevance: float = 0.5
    resume_depth: float = 0.0
    probing_weight: float = 0.0
    allocated_rounds: int = 1
    derivatives: list[str] = []
    probing_chain: list[str] = []
    # 新增：关联工作单元
    work_unit_id: str = ""                 # 所属 WorkProjectUnit 的 ID
    complexity_score: float = 0.0          # 项目复杂度分数
    complexity_reasoning: str = ""         # 复杂度评估理由


class ProjectPriority(BaseModel):
    """项目优先级条目（名称/权重/分配轮数）。"""
    model_config = ConfigDict(extra="ignore")

    name: str = ""
    weight: float = 0.0
    allocated_rounds: int = 0


class ProbingPlan(BaseModel):
    """追问总体计划（知识点/工作单元/项目优先级/总轮数与分布）。"""
    model_config = ConfigDict(extra="ignore")

    knowledge_points: list[KnowledgePoint] = []
    work_units: list[WorkProjectUnit] = []     # 新增：工作-项目合并单元
    project_priorities: list[ProjectPriority] = []
    total_rounds: int = 30
    rounds_distribution: dict = {}
    has_jd: bool = False


# ==================== 前缀知识模型 ====================

class ComparisonItem(BaseModel):
    """技术对比条目（名称/优点/缺点）。"""
    model_config = ConfigDict(extra="ignore")

    name: str = ""
    pros: str = ""
    cons: str = ""


class TopicWithAnswer(BaseModel):
    """带参考答案的面试话题（话题/答案）。"""
    model_config = ConfigDict(extra="ignore")

    topic: str = ""
    answer: str = ""


class QuestionWithAnswer(BaseModel):
    """带参考答案的问答对（问题/答案）。"""
    model_config = ConfigDict(extra="ignore")

    question: str = ""
    answer: str = ""


class PrefixKnowledge(BaseModel):
    """单技术点的前缀知识包（核心概念/常见话题/关键问题/学习问答/踩坑/对比）。"""
    model_config = ConfigDict(extra="ignore")

    tech_name: str = ""
    category: str = ""
    core_concepts: list[str] = []
    common_interview_topics: list[TopicWithAnswer] = []
    key_questions: list[QuestionWithAnswer] = []
    learning_qa: list[QuestionWithAnswer] = []     # 新增：学习导向的 Q&A 对（从基础到进阶）
    quick_reference: str = ""
    pitfalls: list[str] = []
    comparison: list[ComparisonItem] = []
