"""
Resume mining module prompt templates (V2)

三阶段框架：
  Part 1: 技术前置学习 (resume_prefix_knowledge)
  Part 2: 项目深度追问（核心）(resume_probing_strategy + resume_probe_first_round + resume_probe_follow_up)
  Part 3: 简历优化建议 (resume_optimization_advice + resume_probe_evaluation)

辅助步骤：
  S2-S4: 简历解析（7 个模板不变）
  S4.5-S5: 简历概述 + JD 分析（不变）
  S6-NEW: 上下文合并 (resume_work_context_enrichment)
  S7-NEW: 复杂度评估 (resume_complexity_assessment)
"""

TEMPLATES = {
    # ==================== S1: Section Splitting (不变) ====================
    "resume_section_split": (
        "You are a resume structure analyzer. Identify the section boundaries in the following "
        "resume text (with line numbers).\n\n"
        "Section types can only be one of the following:\n"
        "- personal_info\n"
        "- education\n"
        "- work_experience\n"
        "- project_experience\n"
        "- skills\n"
        "- publications\n"
        "- certifications\n"
        "- awards\n"
        "- other\n\n"
        "Output the start and end line numbers for each section in strict JSON format:\n"
        '{{\n  "sections": [\n'
        '    {{ "type": "personal_info", "start_line": 1, "end_line": 5 }},\n'
        '    {{ "type": "work_experience", "start_line": 6, "end_line": 20 }},\n'
        "    ...\n  ]\n}}\n\n"
        "Notes:\n"
        "1. Line numbers correspond to the content after [number] in the numbered text below\n"
        "2. If a section does not exist, do not output it\n"
        "3. Output JSON only, no other content\n"
        "4. Output content in Simplified Chinese\n"
        "5. If the resume lacks clear section headers, infer sections from content semantics\n\n"
        "Numbered resume content:\n{numbered_text}"
    ),

    # ==================== S2-S4: Structured Parsing (不变) ====================
    "resume_parse_personal_info": (
        "You are a personal information extraction expert. Extract structured data from the following content. "
        "Output content in Simplified Chinese.\n\n"
        "Output in strict JSON format:\n"
        '{{\n  "name": "",\n  "phone": "",\n  "email": "",\n  "location": "",\n'
        '  "age": null,\n  "gender": "",\n  "summary": "",\n'
        '  "job_intention": {{\n    "target_position": "",\n    "target_salary": "",\n'
        '    "current_status": ""\n  }},\n'
        '  "social_links": [\n    {{ "platform": "GitHub", "url": "..." }}\n  ]\n}}\n\n'
        "Use empty string or null for missing fields. Output JSON only.\n\nContent:\n{content}"
    ),

    "resume_parse_work_experience": (
        "You are a work experience extraction expert. Extract structured data from the following content. "
        "Output a JSON array with one object per work experience. "
        "Output content in Simplified Chinese.\n\n"
        "Each work experience object format:\n"
        '{{\n  "company": "",\n  "company_brief": "",\n  "position": "",\n  "department": "",\n'
        '  "level": "",\n  "employment_type": "fulltime/intern/parttime",\n'
        '  "start_date": "YYYY.MM",\n  "end_date": "YYYY.MM or present",\n'
        '  "duration_months": 0,\n  "is_current": false,\n  "team_context": "",\n'
        '  "responsibilities": [],\n'
        '  "key_projects": [\n    {{ "name": "", "role": "", "brief": "" }}\n  ],\n'
        '  "achievements": [\n    {{ "description": "", "metric": "", "impact": "high/medium/low" }}\n  ],\n'
        '  "tech_stack": [],\n'
        '  "promotion_history": [\n    {{ "date": "YYYY.MM", "from_level": "", "to_level": "", "reason": "" }}\n  ],\n'
        '  "leave_reason": ""\n}}\n\n'
        "Notes:\n"
        "1. Extract quantitative data where possible (percentages, multiples, specific values)\n"
        "2. Dates in YYYY.MM format, keep 'present' as-is\n"
        "3. Calculate duration_months\n"
        "4. Output JSON array only\n\nContent:\n{content}"
    ),

    "resume_parse_project_experience": (
        "You are a project experience extraction expert. Extract structured data from the following content. "
        "Output a JSON array with one object per project. "
        "Output content in Simplified Chinese.\n\n"
        "Each project object format:\n"
        '{{\n  "name": "",\n  "source": "work/personal/education/open_source",\n'
        '  "associated_company": "",\n  "role": "",\n  "team_size": 0,\n'
        '  "my_contribution_ratio": "",\n  "start_date": "YYYY.MM",\n  "end_date": "YYYY.MM",\n'
        '  "duration_months": 0,\n  "background": "",\n'
        '  "tech_stack": {{\n    "languages": [],\n    "frameworks": [],\n    "middleware": [],\n'
        '    "infrastructure": [],\n    "tools": []\n  }},\n'
        '  "architecture": "",\n  "responsibilities": [],\n'
        '  "challenges": [\n    {{\n      "challenge": "",\n      "solution": "",\n      "result": ""\n    }}\n  ],\n'
        '  "achievements": [\n    {{ "description": "", "metric": "", "impact": "high/medium/low" }}\n  ],\n'
        '  "highlights": [],\n  "probing_directions": []\n}}\n\n'
        "Notes:\n"
        "1. Classify tech stack into the correct arrays\n"
        "2. Extract quantitative data for challenges and achievements\n"
        "3. Generate 3-5 probing_directions (directions an interviewer might probe deeper)\n"
        "4. Output JSON array only\n\nContent:\n{content}"
    ),

    "resume_parse_education": (
        "You are an education history extraction expert. Extract structured data from the following content. "
        "Output a JSON array. Output content in Simplified Chinese.\n\nFormat:\n"
        '{{\n  "school": "",\n  "major": "",\n  "degree": "bachelor/master/phd/associate",\n'
        '  "start_date": "YYYY.MM",\n  "end_date": "YYYY.MM",\n'
        '  "gpa": "",\n  "gpa_ranking": "",\n  "thesis_title": "",\n  "thesis_advisor": "",\n'
        '  "core_courses": [],\n  "highlights": [],\n  "research_direction": ""\n}}\n\n'
        "Use empty string or empty array for missing fields. For dual degrees or joint programs, create separate entries.\n"
        "Output JSON array only.\n\nContent:\n{content}"
    ),

    "resume_parse_skills": (
        "You are a skills extraction expert. Extract structured data from the following content. "
        "Output content in Simplified Chinese.\n\nFormat:\n"
        '{{\n  "skill_groups": [\n    {{\n      "category": "",\n      "label": "",\n      "items": [\n'
        '        {{ "name": "", "proficiency": "expert/proficient/familiar", "years": 0, "source_projects": [] }}\n'
        '      ]\n    }}\n  ],\n'
        '  "certifications": [\n    {{ "name": "", "date": "YYYY.MM" }}\n  ],\n'
        '  "languages": [\n    {{ "language": "", "proficiency": "", "certificate": "" }}\n  ]\n}}\n\n'
        "skill_groups category options: programming_languages, frameworks, middleware, "
        "infrastructure, databases, devops, soft_skills, other\n"
        "Infer proficiency from descriptions like 'expert/proficient/familiar'. "
        "If proficiency cannot be determined, use 'familiar' as default. "
        "Infer source_projects from context where possible.\n"
        "Output JSON only.\n\nContent:\n{content}"
    ),

    "resume_parse_publications": (
        "You are a publications extraction expert. Extract structured data from the following content. "
        "Output content in Simplified Chinese.\n\nFormat:\n"
        '{{\n  "papers": [\n    {{\n      "title": "",\n      "authors": [],\n      "author_rank": 1,\n'
        '      "is_first_author": true,\n      "venue": "",\n      "venue_level": "CCF-A/B/C or empty",\n'
        '      "publication_date": "YYYY.MM",\n      "paper_type": "conference/journal/preprint",\n'
        '      "citations": 0,\n      "abstract": "",\n      "keywords": [],\n'
        '      "my_contribution": "",\n      "related_project": ""\n    }}\n  ],\n'
        '  "patents": [\n    {{\n      "title": "",\n      "patent_type": "invention/utility/design",\n'
        '      "patent_number": "",\n      "status": "pending/granted",\n'
        '      "filing_date": "YYYY.MM",\n      "inventors": [],\n      "inventor_rank": 1,\n'
        '      "brief": ""\n    }}\n  ],\n'
        '  "technical_writings": [\n    {{\n      "title": "",\n      "platform": "",\n      "url": "",\n'
        '      "publish_date": "YYYY.MM",\n      "views": 0,\n      "likes": 0\n    }}\n  ]\n}}\n\n'
        "Use empty string or empty array for missing fields. Output JSON only.\n\nContent:\n{content}"
    ),

    # ==================== S4.5-S5: Resume Analysis (不变) ====================
    "resume_summary": (
        "You are a senior interviewer and resume analyst. Generate a comprehensive resume overview "
        "based on the following structured resume data. Output in Simplified Chinese as Markdown.\n\n"
        "## Structured Resume Data\n{resume_data}\n\n"
        "## Rules\n"
        "- Base your overview ONLY on the provided structured data — do NOT fabricate information\n"
        "- All section headers and content must be in Simplified Chinese\n\n"
        "Generate a Markdown overview with the following sections:\n\n"
        "## Candidate Profile\n"
        "(Years of experience, technical direction, current career stage, job intentions)\n\n"
        "## Core Competency Profile\n"
        "(Strongest technical areas and depth assessment based on actual project usage)\n\n"
        "## Key Project Summary\n"
        "(Each project in 2-3 sentences: what was done, core tech used, problems solved, results achieved)\n\n"
        "## Standout Highlights\n"
        "(Quantified achievements, technical highlights, differentiating advantages vs. peers)\n\n"
        "## Areas for Deep Probing\n"
        "(Points in the resume with insufficient detail that are likely to be probed in interviews)\n"
    ),

    "resume_jd_analysis": (
        "You are a job requirements analyzer. Extract structured technical requirements "
        "from the following job description. Output content in Simplified Chinese.\n\nFormat:\n"
        '{{\n  "position_title": "",\n  "company": "",\n  "seniority_level": "junior/mid/senior/lead",\n'
        '  "required_years": 0,\n'
        '  "required_skills": [\n'
        '    {{ "name": "", "category": "language/framework/middleware/concept/domain", '
        '"importance": "required", "level": "", "context": "" }}\n  ],\n'
        '  "preferred_skills": [\n'
        '    {{ "name": "", "category": "", "importance": "preferred", "level": "", "context": "" }}\n  ],\n'
        '  "required_experience": [],\n  "domain_knowledge": [],\n'
        '  "soft_skills": [],\n  "responsibilities": []\n}}\n\n'
        "Notes:\n"
        "1. importance options: required/preferred/plus\n"
        "2. Standardize skill names (e.g., 'Go' not 'Golang')\n"
        "3. Output JSON only\n\nJD content:\n{jd_text}"
    ),

    # ==================== S6-NEW: 公司/岗位背景补充 ====================
    "resume_work_context_enrichment": (
        "你是一位资深的行业分析师和面试官。根据以下工作经历信息和相关搜索资料，"
        "补充公司和岗位的背景上下文。输出内容使用简体中文。\n\n"
        "## 工作经历\n"
        "- 公司：{company}\n"
        "- 岗位：{position}\n"
        "- 部门：{department}\n"
        "- 工作内容：{responsibilities}\n"
        "- 涉及项目：{project_summary}\n"
        "- 技术栈：{tech_stack}\n\n"
        "## 搜索参考资料\n"
        "{search_results}\n\n"
        "请输出 JSON：\n"
        '{{\n'
        '  "company_industry": "公司主营业务和行业定位（基于搜索资料，如无资料则基于常识推断）",\n'
        '  "company_scale": "公司规模描述（如能从资料推断，否则留空）",\n'
        '  "position_context": "该岗位在团队中的定位、核心职责范围、可能面临的技术选型和架构决策场景",\n'
        '  "industry_context": "该行业/领域对这类技术岗位的典型要求、常见技术挑战和面试高频关注点"\n'
        '}}\n\n'
        "注意：\n"
        "1. 优先使用搜索资料中的真实信息，搜索资料不足时基于行业常识推断\n"
        "2. position_context 要具体到该岗位可能面临的技术选型、架构决策场景\n"
        "3. industry_context 要说明该行业常见的技术挑战和面试关注点\n"
        "4. 输出 JSON only"
    ),

    # ==================== S7-NEW: 复杂度评估 ====================
    "resume_complexity_assessment": (
        "你是一位资深面试官。评估以下工作-项目单元的复杂度，并自动决定追问轮数。"
        "输出内容使用简体中文。\n\n"
        "## 工作-项目单元信息\n"
        "{work_unit_info}\n\n"
        "## 评估维度\n"
        "按以下 4 个维度评分（每维 1-3 分）：\n"
        "1. 技术栈复杂度：单一语言/框架=1，3-5种技术组合=2，微服务/分布式/大规模=3\n"
        "2. 架构角色：参与者=1，核心开发=2，架构师/负责人=3\n"
        "3. 描述丰富度：仅一句话=1，有背景+职责=2，有挑战+方案+成果+量化数据=3\n"
        "4. 项目权重：边缘项目=1，核心业务项目=2，简历主打项目=3\n\n"
        "## 分配规则\n"
        "- 总分 4-5：2 轮（做法 + 原因）\n"
        "- 总分 6-7：3 轮（做法 + 原因 + 结果）\n"
        "- 总分 8-9：5 轮（做法 + 原因 + 结果 + 困难 + 1轮自由追问）\n"
        "- 总分 10-12：7 轮（完整链路 + 多轮自由追问）\n\n"
        "请输出 JSON：\n"
        '{{\n'
        '  "scores": [\n'
        '    {{ "dimension": "技术栈复杂度", "score": 0, "reason": "" }},\n'
        '    {{ "dimension": "架构角色", "score": 0, "reason": "" }},\n'
        '    {{ "dimension": "描述丰富度", "score": 0, "reason": "" }},\n'
        '    {{ "dimension": "项目权重", "score": 0, "reason": "" }}\n'
        '  ],\n'
        '  "total_score": 0,\n'
        '  "complexity_score": 0.0,\n'
        '  "allocated_rounds": 0,\n'
        '  "reasoning": "综合评估理由"\n'
        '}}\n\n'
        "注意：\n"
        "1. 如果该单元包含多个项目，取最复杂的项目为基准\n"
        "2. complexity_score = total_score / 12.0（归一化到 0-1）\n"
        "3. 输出 JSON only"
    ),

    # ==================== S7-NEW: 追问策略（重写，按工作单元组织） ====================
    "resume_probing_strategy": (
        "你是一位面试追问策略设计师。根据以下工作-项目单元和知识信息，"
        "为每个项目生成追问问题链。输出内容使用简体中文。\n\n"
        "## 目标岗位 JD 技术图谱\n{jd_info}\n\n"
        "## 候选人简历概述\n{resume_summary}\n\n"
        "## 工作-项目单元\n{work_units_json}\n\n"
        "## 配置\n"
        "- 广度（1=仅核心，5=所有衍生主题）：{breadth}\n\n"
        "## 追问策略\n\n"
        "对每个工作单元中的每个项目，生成追问问题链。"
        "前几轮必须遵循固定的追问策略：\n\n"
        "### Round 1（做法）：\n"
        "\"在这个项目中，你具体是怎么实现 XX 的？\" — 问具体方案、技术选型、架构设计、实现步骤。\n\n"
        "### Round 2（原因）：\n"
        "\"为什么选择这个方案/技术？考虑过什么替代方案？\" — 问选型理由、方案对比、权衡考量。\n\n"
        "### Round 3（结果）：\n"
        "\"最终效果怎么样？怎么量化的？\" — 问量化指标、效果对比、度量方法。\n\n"
        "### Round 4（困难）：\n"
        "\"过程中遇到什么困难？怎么解决的？\" — 问具体问题场景、排查思路、解决方案、复盘。\n\n"
        "### Round 5+（深入）：\n"
        "基于前一轮回答中的技术细节/模糊点继续深入。\n\n"
        "**核心规则：**\n"
        "1. 问题必须紧密围绕简历中的实际描述，不能问泛泛的理论问题\n"
        "2. 如果项目关联了公司/岗位背景，问题应该结合该岗位的实际场景\n"
        "3. 每个项目的 allocated_rounds 已由复杂度评估自动决定，生成对应轮数的问题\n"
        "4. 问题要自然，像真实面试对话\n\n"
        "输出 JSON 格式：\n"
        '{{\n  "probing_plans": [\n    {{\n      "work_unit_id": "",\n      "project_name": "",\n'
        '      "probing_chain": [\n        "Round 1 question",\n        "Round 2 question",\n        ...\n      ]\n    }}\n  ]\n}}\n\n'
        "输出 JSON only"
    ),

    # ==================== S8-NEW: 技术前置学习（重写，学习导向） ====================
    "resume_prefix_knowledge": (
        "你是一位面试准备知识讲师。为以下技术主题生成**学习导向**的知识材料和 Q&A 对，"
        "帮助用户快速复习。输出内容使用简体中文。\n\n"
        "技术主题：{tech_list}\n\n"
        "对每个技术主题，生成：\n"
        '{{\n  "items": [\n    {{\n      "tech_name": "",\n      "category": "",\n'
        '      "core_concepts": ["核心概念1", "核心概念2", ...],\n'
        '      "learning_qa": [\n'
        '        {{ "question": "基础原理：XX是什么？怎么工作的？", "answer": "简洁但完整的回答（3-5句，包含关键原理）" }},\n'
        '        {{ "question": "基础原理：XX的核心机制是什么？", "answer": "..." }},\n'
        '        {{ "question": "使用场景：XX适合什么场景？怎么用最好？", "answer": "..." }},\n'
        '        {{ "question": "使用场景：XX的最佳实践是什么？", "answer": "..." }},\n'
        '        {{ "question": "进阶深入：XX的底层实现/性能优化关键点？", "answer": "..." }},\n'
        '        {{ "question": "进阶深入：XX在高并发/大规模场景下有什么注意事项？", "answer": "..." }},\n'
        '        {{ "question": "对比选型：XX和YY相比有什么优劣？什么场景选XX？", "answer": "..." }}\n'
        '      ],\n'
        '      "quick_reference": "一段话快速复习要点（100字以内）",\n'
        '      "pitfalls": ["踩坑点1", "踩坑点2"]\n'
        '    }}\n  ]\n}}\n\n'
        "注意：\n"
        "1. learning_qa 必须每个都有完整回答，不能只有问题\n"
        "2. 回答要精准、有深度，不是泛泛而谈\n"
        "3. Q&A 按难度递进：基础原理 → 使用场景 → 进阶深入 → 对比选型\n"
        "4. 每个技术生成 5-8 组 Q&A\n"
        "5. 输出 JSON only"
    ),

    # ==================== S10: 追问第一轮（重写，做法策略） ====================
    "resume_probe_first_round": (
        "你同时扮演面试官和候选人。"
        "针对候选人在「{kp_name}」上的经历，以「你是怎么做的」为策略提出第一个问题并给出回答。"
        "输出内容使用简体中文。\n\n"
        "## 候选人简历概述\n{resume_summary}\n\n"
        "## 当前追问单元\n"
        "- 知识点：{kp_name}\n"
        "- 类别：{kp_category}\n"
        "- 来源：{kp_source}\n\n"
        "## 简历中的实际描述\n{kp_context}\n\n"
        "{work_context_section}"
        "{probing_chain_section}"
        "{jd_context_section}\n\n"
        "## 第一轮策略：你是怎么做的？\n\n"
        "面试官必须围绕简历中的实际项目描述，询问候选人的具体做法：\n"
        "- 具体方案是什么？技术选型怎么做的？\n"
        "- 架构设计是怎样的？关键实现步骤是什么？\n"
        "- 你在这个项目中负责哪部分？怎么实现的？\n\n"
        "**绝对禁止：**\n"
        "- 问泛泛的理论问题（如\"什么是XX\"）\n"
        "- 问与简历描述无关的问题\n"
        "- 脱离项目场景问纯技术知识\n\n"
        "## 通用规则\n"
        "1. 面试官的问题必须以简历实际描述为出发点，紧密围绕项目场景\n"
        "2. 候选人回答必须基于简历中的实际经验（不编造、不夸大；未涉及的内容诚实说明）\n"
        "3. quality_score（0-1）：纯理论 0.3-0.5，有项目经验支撑 0.6-0.8，有量化数据和深度分析 0.8-1.0\n"
        "4. 输出 JSON only\n\n"
        "输出 JSON 格式：\n"
        '{{\n  "question": "",\n  "answer": "",\n  "quality_score": 0.7\n}}'
    ),

    # ==================== S10: 追问后续轮（重写，强制引用上轮） ====================
    "resume_probe_follow_up": (
        "你同时扮演面试官和候选人。根据上一轮的回答，提出更深入的追问并给出回答。"
        "输出内容使用简体中文。\n\n"
        "## 当前知识点\n"
        "- 名称：{kp_name}\n"
        "- 类别：{kp_category}\n\n"
        "## 上一轮 Q&A\n"
        "**Q**: {prev_question}\n"
        "**A**: {prev_answer}\n"
        "**评分**: {prev_score}\n\n"
        "## 当前轮次策略\n"
        "当前是第 {round_number} 轮。追问方向由轮次决定：\n\n"
        "{round_strategy}\n\n"
        "## 核心规则\n"
        "1. **必须引用上一轮回答中的具体内容**，不能脱离上下文凭空提问\n"
        "2. 面试官的追问必须针对上一轮回答中提到的方案、技术、数据、或模糊之处\n"
        "3. 候选人回答基于实际简历经验（不编造不夸大）\n"
        "4. 如果上一轮回答非常深入（score >= 0.8），可以转向相关延伸话题\n"
        "5. quality_score（0-1）：纯理论 0.3-0.5，有项目经验支撑 0.6-0.8，有量化数据和深度分析 0.8-1.0\n"
        "6. 输出 JSON only\n\n"
        "输出 JSON 格式：\n"
        '{{\n  "question": "",\n  "answer": "",\n  "quality_score": 0.7\n}}'
    ),

    # ==================== S11-NEW: 简历优化建议 ====================
    "resume_optimization_advice": (
        "你是一位资深面试官和简历顾问。基于对候选人简历的深度追问记录，"
        "给出具体的简历优化建议。输出内容使用简体中文，以 Markdown 格式输出。\n\n"
        "## 候选人\n{name}\n\n"
        "## 简历摘要\n{resume_summary}\n\n"
        "## 追问记录摘要（含薄弱点标记）\n{qa_summary}\n\n"
        "请生成以下建议：\n\n"
        "### 1. 简历薄弱点\n"
        "（追问中暴露的描述不足、量化缺失、表达模糊的具体位置，"
        "逐条给出建议补充方向和示例）\n\n"
        "### 2. 高概率追问点\n"
        "（基于简历内容，面试官最可能抓住不放深入追问的 5-8 个点，"
        "每个点说明为什么容易被追问以及准备建议）\n\n"
        "### 3. 表达优化建议\n"
        "（针对每条有问题的简历描述，给出改写示例：\n"
        "  - **原文**：简历中的原始描述\n"
        "  - **问题**：为什么这样写容易被追问或不被认可\n"
        "  - **建议改写**：用 STAR 法重写的示例）\n\n"
        "注意：\n"
        "1. 薄弱点要具体到简历的哪一条、哪个描述\n"
        "2. 表达优化建议要给出可以直接替换的改写版本\n"
        "3. 所有建议基于追问中发现的真实问题，不要泛泛而谈"
    ),

    # ==================== S11: 面试准备建议（保留） ====================
    "resume_probe_evaluation": (
        "You are an interview preparation advisor. Based on the following automated probing Q&A records, "
        "generate an interview preparation advice report for the candidate. "
        "Output in Simplified Chinese as Markdown.\n\n"
        "## Candidate\n{name}\n\n"
        "## Probing Q&A Summary\n{qa_summary}\n\n"
        "Generate a Markdown report with the following sections:\n\n"
        "## Interview Preparation Advice\n\n"
        "### Project Experience Preparation\n"
        "(For each project's probing performance, provide specific preparation advice: "
        "which questions were answered well and can be highlighted, which need additional preparation)\n\n"
        "### Technical Depth Gaps\n"
        "(Technical weaknesses exposed during probing, with specific knowledge points "
        "to review and learning suggestions)\n\n"
        "### Fundamentals Reinforcement\n"
        "(Areas of weakness in fundamentals testing, with directions for reinforcement)\n\n"
        "### High-Frequency Question Predictions\n"
        "(Based on resume and probing results, predict the Top 5 most likely interview questions)\n\n"
        "### Communication Advice\n"
        "(How to better describe project experience using the STAR method, how to quantify achievements)"
    ),
}
