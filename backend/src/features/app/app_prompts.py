"""
Resume mining module prompt templates

Covers: resume parsing (S1-S4), resume analysis (S4.5-S9), probing simulation (S10-S11)
"""

TEMPLATES = {
    # ==================== S1: Section Splitting ====================
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

    # ==================== S2-S4: Structured Parsing ====================
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

    # ==================== S4.5-S9: Resume Analysis ====================
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

    "resume_probing_strategy": (
        "You are an interview probing strategy designer. Generate a probing plan based on the "
        "following information. Output content in Simplified Chinese.\n\n"
        "## Target Position JD Technical Profile\n{jd_info}\n\n"
        "## Candidate Resume Summary\n{resume_summary}\n\n"
        "## Calculated Knowledge Point Weights & Context\n{knowledge_points_json}\n\n"
        "## Configuration\n"
        "- Breadth (derived topics per knowledge point, 1=core only, 5=all derived): {breadth}\n"
        "- Depth (probing rounds per knowledge point, 1=surface, 5=deep): {depth}\n\n"
        "## Probing Patterns (by knowledge point category)\n\n"
        "### Category: project (project deep-dive) — HIGHEST PRIORITY\n"
        "Probe the project holistically, covering these dimensions:\n"
        "1. **Architecture & Selection**: What is the overall architecture? Why this tech stack? Alternatives considered?\n"
        "2. **Problems & Challenges**: Biggest technical challenge? Specific scenario?\n"
        "3. **Solutions & Methods**: What tech/method solved it? Why this approach?\n"
        "4. **Metrics & Verification**: How were resume metrics (XX% improvement, XXms reduction) measured? "
        "Testing tools, environment, process? Baseline comparison? Data collection method?\n"
        "5. **Reflection & Improvement**: If redesigned, what would change? Regrets or improvements?\n\n"
        "### Category: tech_in_project (technology used in project) — MEDIUM PRIORITY\n"
        "Probe specific technologies used in the project, tied to actual project scenarios:\n"
        "1. What did you do with this tech in the XX project? What problem did it solve?\n"
        "2. Why this tech over alternatives? (Trade-off analysis)\n"
        "3. Any pitfalls or difficulties encountered? How resolved?\n"
        "4. If traffic 10x'd, would this solution still hold? How to optimize?\n\n"
        "### Category: fundamental (fundamentals) — BASE LEVEL\n"
        "Verify understanding of core technology internals:\n"
        "1. Core principles / underlying mechanisms?\n"
        "2. Common use cases and best practices?\n"
        "3. Pros and cons vs. similar technologies?\n"
        "4. Production environment caveats and common pitfalls?\n\n"
        "Output JSON format:\n"
        '{{\n  "updated_points": [\n    {{\n      "id": "",\n      "probing_chain": [\n        "Round 1 question",\n        "Round 2 question",\n        ...\n      ]\n    }}\n  ]\n}}\n\n'
        "Notes:\n"
        "1. Generate depth questions per knowledge point (depth = allocated_rounds)\n"
        "2. Strictly follow the category patterns above\n"
        "3. When JD is available, tie questions to specific JD scenarios and requirements\n"
        "4. Questions should be natural, like real interview dialogue\n"
        "5. **MOST IMPORTANT: Each knowledge point has a context field with its actual resume description. "
        "Questions MUST be grounded in the actual scenario described in context — never ask generically "
        "without tying to the specific project. Example: if context says the project uses Redis for session caching, "
        "ask 'Why Redis for session caching?' and 'How is session expiration handled?', "
        "not 'What data structures does Redis have?'**\n"
        "6. Output JSON only"
    ),

    "resume_prefix_knowledge": (
        "You are an interview preparation knowledge card generator. Generate knowledge cards "
        "for the following technical topics. Each test point and question must include a concise answer. "
        "Output content in Simplified Chinese.\n\n"
        "Technical topics:\n{tech_list}\n\n"
        "For each technical topic, generate:\n"
        '{{\n  "items": [\n    {{\n      "tech_name": "",\n      "category": "",\n'
        '      "core_concepts": [],\n'
        '      "common_interview_topics": [\n        {{ "topic": "", "answer": "Concise answer (2-3 sentences with key points)" }}\n      ],\n'
        '      "key_questions": [\n'
        '        {{ "question": "", "answer": "Reference answer (3-5 sentences with core principles and key points)" }}\n      ],\n'
        '      "quick_reference": "One-paragraph quick review (max 100 characters)",\n'
        '      "pitfalls": [],\n'
        '      "comparison": [\n        {{ "name": "", "pros": "", "cons": "" }}\n      ]\n    }}\n  ]\n}}\n\n'
        "Notes:\n"
        "1. common_interview_topics MUST each have an answer, not just a topic name\n"
        "2. key_questions MUST each have an answer that would score high in an interview\n"
        "3. Answers must be precise, accurate, and deep — not vague\n"
        "4. Output JSON only"
    ),

    # ==================== S10-S11: Probing Simulation ====================
    "resume_probe_first_round": (
        "You play both interviewer and candidate simultaneously. "
        "Based on the candidate's '{kp_name}' experience, ask the first question and provide the answer. "
        "Output content in Simplified Chinese.\n\n"
        "## Candidate Resume Summary\n{resume_summary}\n\n"
        "## Current Knowledge Point\n"
        "- Name: {kp_name}\n"
        "- Category: {kp_category}\n"
        "- Source: {kp_source}\n\n"
        "## Actual Description in Resume\n{kp_context}\n"
        "{probing_chain_section}\n"
        "{jd_context_section}\n\n"
        "## Question Strategy (by category)\n\n"
        "### If category is project (project deep-dive)\n"
        "Focus on the project holistically:\n"
        "- Architecture & Selection: Why this architecture/tech stack? Alternatives considered?\n"
        "- Problems & Challenges: Biggest technical challenge?\n"
        "- Solutions & Methods: What tech solved what problem? Why this choice?\n"
        "- Metrics & Verification: How were resume metrics measured? Testing tools and process? "
        "Baseline? Data collection method?\n"
        "- Reflection & Improvement: If redesigned, what would change?\n\n"
        "### If category is tech_in_project (technology in project)\n"
        "Probe specific technology tied to project scenario:\n"
        "- What did you do with this tech in this project? What problem?\n"
        "- Why this tech over alternatives? (Trade-offs)\n"
        "- Pitfalls encountered? How resolved?\n"
        "- If traffic doubled, would this solution hold?\n\n"
        "### If category is fundamental (fundamentals)\n"
        "Verify deep understanding:\n"
        "- Core principles? Underlying mechanisms?\n"
        "- Common use cases and best practices?\n"
        "- Pros/cons vs. similar technologies?\n"
        "- Production environment caveats?\n\n"
        "## General Rules\n"
        "1. The interviewer MUST base questions on 'Actual Description in Resume', "
        "closely tied to the specific project scenario — never ask generically without context\n"
        "2. The candidate answers based on actual experience described in the resume "
        "(no fabrication or exaggeration; honestly state areas not covered)\n"
        "3. quality_score represents answer depth (0-1): pure theory 0.3-0.5, "
        "backed by project experience 0.6-0.8, quantified data with deep analysis 0.8-1.0\n"
        "4. Output JSON only\n\n"
        "Output JSON format:\n"
        '{{\n  "question": "",\n  "answer": "",\n  "quality_score": 0.7\n}}'
    ),

    "resume_probe_follow_up": (
        "You play both interviewer and candidate simultaneously. Based on the previous answer, "
        "ask a deeper follow-up question and provide the answer. "
        "Output content in Simplified Chinese.\n\n"
        "## Current Knowledge Point\n"
        "- Name: {kp_name}\n"
        "- Category: {kp_category}\n\n"
        "## Previous Q&A\n"
        "**Q**: {prev_question}\n"
        "**A**: {prev_answer}\n"
        "**Score**: {prev_score}\n\n"
        "## Follow-up Rules\n"
        "1. The interviewer MUST probe based on specific content in the previous answer, not generically\n"
        "2. Follow-up direction (choose the one that enables deepest probing):\n"
        "   - Technical details mentioned: probe underlying principles or implementation\n"
        "   - Solution choices mentioned: probe why this choice, alternatives considered\n"
        "   - Metrics/data mentioned: probe measurement methodology, baselines, testing approach\n"
        "   - Challenges mentioned: probe specific resolution, pitfalls encountered\n"
        "   - Weak points: areas where the candidate was vague or superficial\n"
        "3. The candidate answers based on actual resume experience (no fabrication or exaggeration)\n"
        "4. If the previous answer was very deep (score >= 0.8), the follow-up can shift to related extension topics\n"
        "5. quality_score represents this round's answer depth (0-1): pure theory 0.3-0.5, "
        "backed by project experience 0.6-0.8, quantified data with deep analysis 0.8-1.0\n"
        "6. Output JSON only\n\n"
        "Output JSON format:\n"
        '{{\n  "question": "",\n  "answer": "",\n  "quality_score": 0.7\n}}'
    ),

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
