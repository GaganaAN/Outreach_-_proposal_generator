"""
Seed dummy past performance data for Ivoyant Systems.
Runs on app startup only if the past_projects table is empty.
"""
import json
import logging

logger = logging.getLogger(__name__)

PAST_PROJECTS = [
    {
        "title": "Enterprise Data Lake on AWS for Retail Analytics",
        "client_name": "Confidential Retail Group",
        "industry": "Retail",
        "project_type": "Data Engineering",
        "problem_statement": (
            "Client had siloed data across 12 source systems with no unified analytics layer, "
            "resulting in delayed reporting and missed business insights."
        ),
        "our_solution": (
            "Designed and built a scalable AWS data lake using S3, Glue ETL, and Redshift. "
            "Implemented Airflow-based orchestration and dbt transformations for reliable pipelines."
        ),
        "technologies": json.dumps(["AWS", "S3", "Redshift", "Glue", "Apache Airflow", "dbt", "Python", "SQL"]),
        "outcome": "Reduced report generation time from 4 hours to under 10 minutes; unified 12 data sources.",
        "team_size": 6,
        "duration_months": 8,
        "start_year": 2023,
    },
    {
        "title": "Cloud Migration from On-Premise to Azure",
        "client_name": "Confidential Manufacturing Firm",
        "industry": "Manufacturing",
        "project_type": "Cloud Migration",
        "problem_statement": (
            "Legacy on-premise infrastructure was expensive to maintain with frequent outages, "
            "limiting scalability during peak production cycles."
        ),
        "our_solution": (
            "Executed lift-and-shift followed by optimization to Azure using AKS, Azure SQL, "
            "and Blob Storage. Set up Azure DevOps CI/CD pipelines for automated deployments."
        ),
        "technologies": json.dumps(["Azure", "AKS", "Azure DevOps", "Docker", "Kubernetes", "Terraform", "Python"]),
        "outcome": "Achieved 40% reduction in infrastructure costs and 99.9% uptime SLA.",
        "team_size": 5,
        "duration_months": 6,
        "start_year": 2023,
    },
    {
        "title": "ML-Based Demand Forecasting Pipeline",
        "client_name": "Confidential FMCG Company",
        "industry": "FMCG",
        "project_type": "Machine Learning",
        "problem_statement": (
            "Manual demand forecasting was producing 30% error rates, causing stockouts "
            "and excess inventory valued at $2M annually."
        ),
        "our_solution": (
            "Built an end-to-end ML pipeline using scikit-learn and XGBoost models, "
            "served via FastAPI microservices on GCP with automated retraining via Vertex AI."
        ),
        "technologies": json.dumps(["Python", "scikit-learn", "XGBoost", "FastAPI", "GCP", "Vertex AI", "BigQuery", "Docker"]),
        "outcome": "Reduced forecast error to under 8%; saved $1.8M annually in inventory costs.",
        "team_size": 4,
        "duration_months": 5,
        "start_year": 2024,
    },
    {
        "title": "Real-Time BI Dashboard for Financial Services",
        "client_name": "Confidential Fintech Company",
        "industry": "Financial Services",
        "project_type": "Business Intelligence",
        "problem_statement": (
            "Finance team lacked real-time visibility into KPIs across 5 business units, "
            "relying on weekly Excel reports from different departments."
        ),
        "our_solution": (
            "Implemented a real-time Snowflake + Power BI solution with CDC pipelines using "
            "Fivetran, delivering live dashboards refreshed every 15 minutes."
        ),
        "technologies": json.dumps(["Snowflake", "Power BI", "Fivetran", "dbt", "Azure", "SQL", "Python"]),
        "outcome": "Delivered 15-min real-time dashboards used by 200+ stakeholders across 5 business units.",
        "team_size": 3,
        "duration_months": 4,
        "start_year": 2024,
    },
    {
        "title": "Microservices API Integration Platform",
        "client_name": "Confidential Healthcare Provider",
        "industry": "Healthcare",
        "project_type": "API Integration",
        "problem_statement": (
            "Multiple disconnected EHR, billing, and scheduling systems with no unified API layer, "
            "causing data inconsistencies and manual reconciliation overhead."
        ),
        "our_solution": (
            "Designed a microservices integration layer using FastAPI and Kafka for event-driven "
            "data sync, with Kong API gateway for centralized authentication and rate limiting."
        ),
        "technologies": json.dumps(["FastAPI", "Apache Kafka", "Kong", "PostgreSQL", "Docker", "Kubernetes", "Python", "REST APIs"]),
        "outcome": "Eliminated manual reconciliation (saving 40 staff-hours/week) and reduced data latency from 24h to 2 min.",
        "team_size": 5,
        "duration_months": 7,
        "start_year": 2023,
    },
    {
        "title": "DevOps Automation and CI/CD Modernization",
        "client_name": "Confidential SaaS Startup",
        "industry": "Technology",
        "project_type": "DevOps Automation",
        "problem_statement": (
            "Manual deployments took 3–4 hours and had a 25% rollback rate, "
            "significantly impacting release velocity and developer productivity."
        ),
        "our_solution": (
            "Implemented GitHub Actions CI/CD pipelines, Terraform IaC for AWS infrastructure, "
            "and ArgoCD for GitOps-based Kubernetes deployments with automated testing gates."
        ),
        "technologies": json.dumps(["GitHub Actions", "Terraform", "AWS", "Kubernetes", "ArgoCD", "Docker", "Helm", "Python"]),
        "outcome": "Reduced deployment time from 4 hours to 12 minutes; rollback rate dropped to under 3%.",
        "team_size": 3,
        "duration_months": 3,
        "start_year": 2024,
    },
    {
        "title": "Scalable Data Warehouse for E-Commerce Analytics",
        "client_name": "Confidential E-Commerce Platform",
        "industry": "E-Commerce",
        "project_type": "Data Engineering",
        "problem_statement": (
            "Growing transaction volume (5M+ daily events) was overwhelming existing MySQL-based "
            "reporting, causing query timeouts and stale dashboards."
        ),
        "our_solution": (
            "Migrated to a Snowflake data warehouse with Spark-based batch ingestion on AWS EMR, "
            "real-time streaming via Kafka, and automated dbt model testing."
        ),
        "technologies": json.dumps(["Snowflake", "Apache Spark", "AWS EMR", "Apache Kafka", "dbt", "Python", "SQL", "Airflow"]),
        "outcome": "Handled 5M+ daily events with sub-second query performance; zero downtime migration.",
        "team_size": 7,
        "duration_months": 9,
        "start_year": 2022,
    },
    {
        "title": "Security Audit and Zero-Trust Network Implementation",
        "client_name": "Confidential Government Agency",
        "industry": "Government",
        "project_type": "Cybersecurity",
        "problem_statement": (
            "Agency faced growing threat surface from remote work expansion with no zero-trust "
            "architecture, resulting in 3 security incidents in 12 months."
        ),
        "our_solution": (
            "Conducted comprehensive security audit, implemented zero-trust network access via "
            "Zscaler, integrated SIEM with Splunk, and deployed automated threat detection."
        ),
        "technologies": json.dumps(["Zscaler", "Splunk", "Azure AD", "Python", "SIEM", "IAM", "Network Security", "Compliance"]),
        "outcome": "Zero security incidents in 18 months post-implementation; achieved FedRAMP compliance.",
        "team_size": 4,
        "duration_months": 6,
        "start_year": 2023,
    },
]


def seed_past_projects(db):
    """Insert dummy past projects if the table is empty."""
    from app.models import PastProject

    count = db.query(PastProject).count()
    if count > 0:
        logger.info(f"Past projects already seeded ({count} records) — skipping")
        return

    for data in PAST_PROJECTS:
        project = PastProject(**data)
        db.add(project)

    db.commit()
    logger.info(f"✓ Seeded {len(PAST_PROJECTS)} past performance records")
