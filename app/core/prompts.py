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