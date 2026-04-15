"""
LLM Prompts for job extraction and email generation
"""

JOB_EXTRACTION_PROMPT = """You are an AI assistant specialized in analyzing job postings.

Your task is to extract structured information from the following job posting text.

Job Posting Text:
{job_text}

Extract the following information and return ONLY a valid JSON object with this exact structure.
IMPORTANT: All fields are required. If information is not found, use reasonable defaults.

{{
  "job_role": "the job title or role",
  "skills": ["skill1", "skill2", "skill3"],
  "description": "a concise summary of the job responsibilities",
  "experience_level": "entry/mid/senior level or null",
  "location": "job location if mentioned or null"
}}

CRITICAL RULES:
1. skills MUST be an array/list with at least one skill - NEVER use null or empty
2. If no clear skills found, extract general skills like ["Communication", "Teamwork", "Problem Solving"]
3. Extract ALL technical skills mentioned (programming languages, frameworks, tools, methodologies)
4. Keep skills as short, specific terms (e.g., "Python", "React", "AWS")
5. Make the description concise (2-3 sentences max)
6. Return ONLY valid JSON, no additional text, no markdown, no explanation
7. If a field is not found, use null for experience_level and location, but NEVER for skills

Example valid response:
{{
  "job_role": "Software Engineer",
  "skills": ["Python", "JavaScript", "SQL", "REST APIs"],
  "description": "Develop and maintain software applications. Collaborate with cross-functional teams.",
  "experience_level": "mid",
  "location": "Remote"
}}

JSON Output:"""


EMAIL_GENERATION_PROMPT = """You are an expert cold email writer for a software services company.

Company Information:
- Name: {company_name}
- Website: {company_website}

Job Details:
- Role: {job_role}
- Required Skills: {skills}
- Description: {job_description}

Matched Portfolio Evidence:
{portfolio_matches}

CRITICAL FORMATTING RULES - MUST FOLLOW EXACTLY:

1. DO NOT include "Subject:" in the body
2. Write 4-5 SHORT paragraphs separated by TWO line breaks (\n\n)
3. Each paragraph = 1-3 sentences ONLY (not more)
4. Total length: 150-200 words

EXACT EMAIL STRUCTURE (copy this format):

Dear Hiring Manager,

[1-2 sentences about the role and initial interest]

[2-3 sentences about your expertise with portfolio links]

[2-3 sentences about benefits of partnering]

[1-2 sentences call-to-action]

Best regards,

Business Development Team
{company_name}
{company_website}

CONTENT GUIDELINES:
- Mention specific role from job posting
- Include 1-2 portfolio links naturally: "expertise in AWS (https://link)"
- Focus on flexibility, cost-effectiveness, no hiring overhead
- Professional, confident tone
- Keep it CONCISE and scannable

EXAMPLE FORMAT (follow this structure):

Dear Hiring Manager,

I came across your Security Engineer role and was impressed by the requirements.

Our team specializes in security software with proven expertise in AWS (link) and Docker (link). We've delivered similar projects successfully.

By partnering with Ivoyant, you get flexibility without full-time hiring costs. We scale with your needs.

I'd love to discuss how we can support your team. Let me know if you're interested.

Best regards,

Business Development Team
Ivoyant Systems Pvt Ltd
https://www.ivoyant.com

NOW write the email following this EXACT format with paragraph breaks:"""


EMAIL_SUBJECT_PROMPT = """Generate a professional B2B email subject line for a cold email about the following:

Job Role: {job_role}
Key Skills: {key_skills}

The subject should be:
- Professional and clear (B2B style)
- Focus on value proposition (e.g., "Experienced Team Available", "Partnership Opportunity")
- Specific to the role/skills mentioned
- Under 100 characters

Examples:
- "Senior {job_role} Developers Available for Immediate Start"
- "Scaling your {job_role} team with {key_skills} Experts"
- "Partnership Proposal: Dedicated {job_role} Resources"

Generate ONLY the subject line, nothing else:"""


PORTFOLIO_SUMMARY_PROMPT = """Summarize the following portfolio matches into a concise format suitable for an email:

{matches}

Format each match as:
- Skill: [Brief description with portfolio link]

Keep it concise and professional."""


# ── Phase 1: Signal Classification ────────────────────────────────────────────

SIGNAL_CLASSIFICATION_PROMPT = """You are an AI assistant that classifies business signals to determine what sales action to take.

Analyze the following text and classify it. Return ONLY a valid JSON object.

Text to analyze:
{signal_text}

Classify into exactly one of these types:
- "job_hiring"        : Company is hiring for a role we can fill as a service provider (staff augmentation / consulting)
- "rfp_opportunity"   : A formal Request for Proposal, tender, or procurement notice requiring a technical proposal
- "service_request"   : Direct inquiry or request for IT services, software development, or consulting
- "other"             : Not relevant to our business

Return this exact JSON structure:
{{
  "signal_type": "job_hiring|rfp_opportunity|service_request|other",
  "company_name": "extracted company or organization name, or null if not identifiable — NEVER use 'unknown', 'N/A', or placeholder strings",
  "detected_skills": ["skill1", "skill2"],
  "confidence_score": 0.85,
  "reasoning": "one sentence explaining the classification"
}}

Rules:
1. confidence_score must be between 0.0 and 1.0
2. detected_skills should list technology/domain skills mentioned (max 10)
3. If no company name is found, use null
4. Return ONLY the JSON object, no markdown, no explanation

JSON Output:"""


# ── Phase 4: AI Personalization ────────────────────────────────────────────────

COMPANY_CONTEXT_EXTRACTION_PROMPT = """Extract key business context from the following company website text.
Return ONLY a valid JSON object.

Website text:
{website_text}

Return:
{{
  "company_description": "1-2 sentence description of what the company does",
  "tech_stack": ["technology1", "technology2"],
  "industry": "industry name",
  "recent_focus": "any mentioned initiatives, expansions, or challenges (1 sentence or null)"
}}

Return ONLY the JSON, no markdown:"""


# ── Phase 5: Proposal Generation ───────────────────────────────────────────────

RFP_EXTRACTION_PROMPT = """You are an expert at analyzing RFP (Request for Proposal) documents.

Extract structured requirements from the following RFP text.
Return ONLY a valid JSON object.

RFP Text:
{rfp_text}

Return:
{{
  "project_title": "project title",
  "client_name": "client/organization name or null",
  "requirements": ["requirement 1", "requirement 2"],
  "tech_stack": ["technology1", "technology2"],
  "timeline": "mentioned timeline or null",
  "budget_range": "mentioned budget range or null",
  "submission_deadline": "deadline date or null",
  "evaluation_criteria": ["criterion 1", "criterion 2"]
}}

Return ONLY the JSON, no markdown:"""


PROPOSAL_GENERATION_PROMPT = """You are an expert technical proposal writer for a software services company.

Company Information:
- Name: {company_name}
- Website: {company_website}

RFP Requirements:
{requirements}

Relevant Portfolio / Experience:
{portfolio_matches}

Past Performance (Completed Projects):
{past_projects}

Evaluation Criteria (from solicitation):
{evaluation_matrix}

Agency Signals — What May Help Win:
{what_may_help_win}

Write a structured technical proposal. Return ONLY a valid JSON object with these sections:

{{
  "executive_summary": "2-3 sentence summary of our understanding and value proposition",
  "understanding_of_requirements": "2-3 paragraphs showing we understand the client's needs",
  "proposed_solution": "detailed solution approach with methodology (3-4 paragraphs)",
  "relevant_experience": "2-3 paragraphs citing specific past project names, outcomes, and technologies from the Past Performance section above",
  "team_structure": "description of proposed team roles and expertise",
  "timeline": "high-level project timeline with phases",
  "why_choose_us": "3-4 bullet points on our key differentiators, referencing specific past project outcomes and directly addressing the evaluation criteria",
  "next_steps": "1 paragraph on proposed next steps"
}}

Guidelines:
- Be specific and reference the requirements
- In relevant_experience and why_choose_us, cite actual project titles and measurable outcomes from Past Performance
- Structure the proposed_solution to address each evaluation factor in order of its weight
- Weave agency signals (what_may_help_win) into the proposed_solution and why_choose_us sections
- Keep each section focused and professional
- Do not include pricing numbers (handled separately)

Return ONLY the JSON object:"""


# ── Capture Management ─────────────────────────────────────────────────────────

CAPTURE_QUALIFICATION_PROMPT = """You are a capture analyst extracting structured qualification data from a government solicitation for Ivoyant Systems.

Ivoyant Systems Profile (for scope matching):
- Core capabilities: Data Engineering, Cloud Migration (AWS/Azure/GCP), Business Intelligence & Analytics,
  Machine Learning / AI, API Integration, DevOps & Platform Engineering, Cybersecurity, System Modernization
- NAICS focus: IT services, software development, data platforms, managed services
- Company size: Mid-size IT services firm

Search keyword that triggered this discovery: {keyword}
Solicitation source URL: {solicitation_url}

Full solicitation / RFP text:
{rfp_text}

Extract ALL sections below with precision. Use verbatim quotes from the document wherever "exact_wording" is requested.
Return ONLY a valid JSON object — no markdown, no explanation.

{{
  "title": "full solicitation title",
  "agency": "issuing agency or organization name",
  "solicitation_number": "solicitation or RFP number, or null",
  "response_deadline": "submission deadline date/time, or null",
  "agency_registration_details": {
    "is_required": true,
    "systems_or_portals": ["any agency or procurement portals the bidder must register in"],
    "identifiers": ["vendor IDs, supplier numbers, cage/sam identifiers, or account numbers"],
    "instructions": "registration steps or instructions if stated",
    "exact_wording": "Verbatim quote from the RFP about agency-specific registration details"
  },

  "keyword_matched_paragraph": "The exact paragraph(s) from the document where the search keyword '{keyword}' appears. Copy verbatim.",

  "past_performance_requirements": {{
    "is_required": true,
    "government_experience_required": false,
    "description": "What type of past performance is requested",
    "exact_wording": "Verbatim quote from RFP about past performance",
    "conditions": ["any conditions: years, contract value, similarity, domain, number of references"]
  }},

  "insurance_requirements": {{
    "is_mentioned": true,
    "types": ["General Liability", "Professional Liability / E&O", "Workers Comp", "etc."],
    "coverage_limits": "Any dollar limits or conditions stated",
    "exact_wording": "Verbatim quote from RFP about insurance"
  }},

  "certifications_required": [
    {{
      "name": "FedRAMP / SOC 2 / HIPAA / StateRAMP / ISO 27001 / etc.",
      "mandatory_or_preferred": "mandatory",
      "timing": "at time of submission / prior to award / during performance",
      "exact_wording": "Verbatim quote from RFP mentioning this certification"
    }}
  ],

  "licenses_registrations": {{
    "licenses": ["any licenses required to bid or perform"],
    "registrations": ["SAM.gov, state registrations, any other required registrations"],
    "preconditions": ["any formal preconditions bidder must satisfy before submission"],
    "exact_wording": "Verbatim quote from RFP about licenses/registrations"
  }},

  "mandatory_disqualifying_requirements": [
    "List every condition that would disqualify Ivoyant if not met.",
    "Include: mandatory government past performance, mandatory certifications, mandatory registrations, location restrictions, mandatory experience thresholds, any must-have conditions"
  ],

  "scope_match": {{
    "level": "High",
    "percentage": 80,
    "summary": "2-3 sentence explanation of how well this solicitation aligns with Ivoyant's core capabilities. Reference specific capability areas that match."
  }},

  "technical_requirements": {{
    "work_description": "What technical work is expected from the bidder",
    "technologies": ["list every technology, platform, system, tool, language mentioned"],
    "integrations": ["any integrations, APIs, or system connections required"],
    "exact_expectations": "Verbatim technical requirements text from the solicitation"
  }},

  "what_may_help_win": [
    "Each item is a signal about what the agency values, prefers, or is looking for",
    "Include: preferred experience, preferred technical approach, preferred delivery methodology",
    "Include: any language signalling agency priorities, hot-button topics, or evaluation emphasis"
  ],

  "evaluation_matrix": {{
    "factors": ["Technical Approach", "Past Performance", "Price/Cost", "etc."],
    "scoring_criteria": "How proposals will be evaluated — best value, LPTA, points-based, etc.",
    "technical_weight": "percentage or points allocated to technical",
    "past_performance_weight": "percentage or points allocated to past performance",
    "price_weight": "percentage or points allocated to price",
    "priority_order": "Listed order of evaluation factors if stated"
  }}
}}

Rules:
- Use null (not empty string) for any field not found in the document
- scope_match.level must be exactly one of: High, Medium, Low
- scope_match.percentage must be an integer 0-100
- certifications_required must be a list (empty list [] if none found)
- mandatory_disqualifying_requirements must be a list (empty list [] if none found)
- what_may_help_win must be a list (empty list [] if none found)
- agency_registration_details must be an object; use null values for missing subfields
- Use only facts present in the scraped page or attached documents. Do not infer or invent values.
- Return ONLY the JSON object, no markdown fences"""
