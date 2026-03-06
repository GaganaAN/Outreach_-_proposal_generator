# 🚀 Cold Email Generator - FastAPI Backend

An intelligent cold email generation system that uses LLM (LLaMA 3.1) and RAG (Retrieval-Augmented Generation) to automatically create personalized cold emails for software service companies.

## 📋 Overview

This system automates the process of generating targeted cold emails by:

1. **Scraping job postings** from career pages
2. **Extracting structured job data** using LLM (role, skills, requirements)
3. **Matching skills** with your company's portfolio using vector search
4. **Generating personalized emails** that highlight relevant expertise

## 🏗️ Architecture

```
┌─────────────┐
│  Job URL    │
└──────┬──────┘
       │
       ▼
┌─────────────────┐
│  Web Scraping   │  (BeautifulSoup)
└──────┬──────────┘
       │
       ▼
┌─────────────────┐
│ Job Extraction  │  (LLaMA 3.1 via Groq)
└──────┬──────────┘
       │
       ▼
┌─────────────────┐
│ Vector Search   │  (ChromaDB)
│ Portfolio Match │
└──────┬──────────┘
       │
       ▼
┌─────────────────┐
│Email Generation │  (LLaMA 3.1)
└──────┬──────────┘
       │
       ▼
┌─────────────────┐
│ Cold Email 📧   │
└─────────────────┘
```

## 🛠️ Tech Stack

- **FastAPI** - Modern Python web framework
- **LLaMA 3.1** - Open-source LLM via Groq API
- **ChromaDB** - Vector database for semantic search
- **LangChain** - LLM orchestration
- **BeautifulSoup** - Web scraping
- **Pydantic** - Data validation

## 📁 Project Structure

```
cold-email-generator/
├── app/
│   ├── main.py                 # FastAPI application
│   ├── config.py               # Configuration
│   ├── api/
│   │   ├── routes.py           # API endpoints
│   │   └── schemas.py          # Pydantic models
│   ├── core/
│   │   ├── llm_client.py       # LLaMA integration
│   │   ├── prompts.py          # LLM prompts
│   │   └── vector_store.py     # ChromaDB client
│   ├── services/
│   │   ├── job_extractor.py    # Job scraping & extraction
│   │   ├── portfolio_matcher.py # Skill matching
│   │   └── email_generator.py  # Email generation
│   └── utils/
│       └── text_cleaner.py     # Text preprocessing
├── data/
│   └── portfolio.csv           # Portfolio data
├── chroma_db/                  # Vector DB storage
├── requirements.txt
├── init_portfolio.py           # Database initialization
└── README.md
```

## 🚀 Setup Instructions

### 1. Prerequisites

- Python 3.9 or higher
- Groq API key (get from https://console.groq.com)

### 2. Installation

```bash
# Clone or download the project
cd cold-email-generator

# Create virtual environment
python -m venv venv

# Activate virtual environment
# On Linux/Mac:
source venv/bin/activate
# On Windows:
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Configuration

Create a `.env` file in the `app/` directory:

```bash
cp app/.env.example app/.env
```

Edit `app/.env` and add your Groq API key:

```env
GROQ_API_KEY=your_groq_api_key_here
LLM_MODEL=llama-3.1-70b-versatile
COMPANY_NAME=Your Company Name
COMPANY_WEBSITE=https://yourcompany.com
```

### 4. Initialize Portfolio Database

Load sample portfolio data into ChromaDB:

```bash
python init_portfolio.py
```

This will create the vector database and load the sample portfolio from `data/portfolio.csv`.

### 5. Run the Application

```bash
# From the project root directory
python -m app.main

# Or using uvicorn directly
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at:
- **API Docs**: http://localhost:8000/docs
- **API**: http://localhost:8000/api
- **Health Check**: http://localhost:8000/api/health

## 📡 API Endpoints

### 1. Generate Cold Email (Complete Pipeline)

**POST** `/api/generate-email`

Generate a complete cold email from a job posting URL.

```bash
curl -X POST "http://localhost:8000/api/generate-email" \
  -H "Content-Type: application/json" \
  -d '{
    "job_url": "https://jobs.nike.com/job/example"
  }'
```

**Response:**
```json
{
  "email_subject": "Expert ML Engineers Available - Python & AWS Specialists",
  "email_body": "Dear Hiring Manager,\n\nI noticed your posting for...",
  "job_details": {
    "job_role": "ML Engineer",
    "skills": ["Python", "TensorFlow", "AWS"],
    "description": "...",
    "experience_level": "mid",
    "location": "Remote"
  },
  "matched_portfolios": [
    {
      "skill": "Python",
      "portfolio_link": "https://lick.com/portfolio/python",
      "projects": ["ML Pipeline", "Data Processing"],
      "relevance_score": 0.92
    }
  ],
  "processing_time": 8.5
}
```

### 2. Extract Job Details Only

**POST** `/api/extract-job`

Extract structured job information without generating an email.

```bash
curl -X POST "http://localhost:8000/api/extract-job" \
  -H "Content-Type: application/json" \
  -d '{
    "job_url": "https://jobs.nike.com/job/example"
  }'
```

### 3. Upload Portfolio Entry

**POST** `/api/portfolio/upload`

Add a new portfolio entry to the vector database.

```bash
curl -X POST "http://localhost:8000/api/portfolio/upload" \
  -H "Content-Type: application/json" \
  -d '{
    "skill": "Rust",
    "portfolio_link": "https://yourcompany.com/rust",
    "projects": ["High-performance API", "Systems Programming"],
    "description": "Expert Rust development for performance-critical applications"
  }'
```

### 4. Search Portfolio

**POST** `/api/portfolio/search`

Search for portfolio entries matching specific skills.

```bash
curl -X POST "http://localhost:8000/api/portfolio/search" \
  -H "Content-Type: application/json" \
  -d '{
    "skills": ["Python", "Machine Learning"],
    "top_k": 5
  }'
```

### 5. Portfolio Statistics

**GET** `/api/portfolio/stats`

Get statistics about the portfolio database.

```bash
curl "http://localhost:8000/api/portfolio/stats"
```

### 6. Health Check

**GET** `/api/health`

Check service health status.

```bash
curl "http://localhost:8000/api/health"
```

## 📝 Usage Examples

### Python Example

```python
import requests

# Generate cold email
response = requests.post(
    "http://localhost:8000/api/generate-email",
    json={
        "job_url": "https://jobs.example.com/ml-engineer"
    }
)

result = response.json()
print(f"Subject: {result['email_subject']}")
print(f"Body:\n{result['email_body']}")
```

### cURL Example

```bash
# Complete workflow
curl -X POST "http://localhost:8000/api/generate-email" \
  -H "Content-Type: application/json" \
  -d '{"job_url": "https://jobs.example.com/ml-engineer"}' \
  | jq .
```

## 🔧 Customization

### Add Your Own Portfolio Data

Edit `data/portfolio.csv`:

```csv
skill,portfolio_link,projects,description
YourSkill,https://yoursite.com/portfolio,"Project A, Project B","Description here"
```

Then reinitialize:

```bash
python init_portfolio.py
```

### Customize Email Prompts

Edit `app/core/prompts.py` to customize:
- Job extraction format
- Email generation style
- Subject line templates

### Change LLM Model

Edit `app/.env`:

```env
# Use different Groq model
LLM_MODEL=llama-3.1-8b-instant  # Faster, less accurate
LLM_MODEL=llama-3.1-70b-versatile  # Balanced (default)
```

## 🧪 Testing

### Test the API

```bash
# Health check
curl http://localhost:8000/api/health

# Test with a real job URL
curl -X POST "http://localhost:8000/api/generate-email" \
  -H "Content-Type: application/json" \
  -d '{"job_url": "https://jobs.nike.com/job/example"}'
```

### Interactive API Documentation

Visit http://localhost:8000/docs to use the interactive Swagger UI for testing all endpoints.

## 🐛 Troubleshooting

### Issue: "GROQ_API_KEY not found"

**Solution:** Make sure you have created `app/.env` and added your API key.

### Issue: Vector store errors

**Solution:** Delete and recreate the database:

```bash
rm -rf chroma_db/
python init_portfolio.py
```

### Issue: Web scraping fails

**Solution:** Some sites block scrapers. Try:
- Using a different job posting URL
- Adding delays between requests
- Implementing browser automation (Playwright)

## 📊 Performance

- **Job extraction**: ~3-5 seconds
- **Email generation**: ~5-8 seconds
- **Total pipeline**: ~8-15 seconds

Performance depends on:
- LLM API response time
- Web page complexity
- Number of skills to match

## 🚀 Production Deployment

For production deployment:

1. **Set DEBUG=False** in `.env`
2. **Use proper CORS settings** in `main.py`
3. **Add authentication** for sensitive endpoints
4. **Use environment variables** for secrets
5. **Set up monitoring** and logging
6. **Consider rate limiting** for API endpoints

### Docker Deployment (Optional)

Create `Dockerfile`:

```dockerfile
FROM python:3.10-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Build and run:

```bash
docker build -t cold-email-generator .
docker run -p 8000:8000 --env-file app/.env cold-email-generator
```

## 📄 License

MIT License

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📧 Support

For issues or questions, please open an issue on GitHub or contact the development team.

---

**Built with ❤️ using FastAPI, LLaMA 3.1, and ChromaDB**