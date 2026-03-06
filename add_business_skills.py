"""
Add business and finance skills to portfolio database
"""
import requests
import json

# API endpoint
BASE_URL = "http://localhost:8000"

# Business/Finance skills to add
business_skills = [
    {
        "skill": "Financial Planning",
        "portfolio_link": "https://ivoyant.com/portfolio/financial-planning",
        "projects": ["Budget Analysis System", "Financial Dashboard", "Cost Optimization Tool"],
        "description": "Expert financial planning and analysis solutions for data-driven decision making"
    },
    {
        "skill": "Data Analysis",
        "portfolio_link": "https://ivoyant.com/portfolio/data-analysis",
        "projects": ["Business Intelligence Dashboard", "Predictive Analytics", "Data Visualization"],
        "description": "Advanced data analysis and business intelligence solutions"
    },
    {
        "skill": "Procurement",
        "portfolio_link": "https://ivoyant.com/portfolio/procurement",
        "projects": ["Procurement Management System", "Vendor Portal", "Supply Chain Analytics"],
        "description": "Automated procurement and vendor management solutions"
    },
    {
        "skill": "Customer Service",
        "portfolio_link": "https://ivoyant.com/portfolio/customer-service",
        "projects": ["CRM System", "Customer Support Portal", "Ticketing System"],
        "description": "Comprehensive customer service and support solutions"
    },
    {
        "skill": "Sales",
        "portfolio_link": "https://ivoyant.com/portfolio/sales",
        "projects": ["Sales Automation Tool", "Lead Management System", "Performance Dashboard"],
        "description": "Sales enablement and automation solutions"
    },
    {
        "skill": "Project Management",
        "portfolio_link": "https://ivoyant.com/portfolio/project-management",
        "projects": ["Project Tracking System", "Resource Planning Tool", "Collaboration Platform"],
        "description": "Project management and team collaboration solutions"
    }
]

def add_skills():
    """Add skills to portfolio via API"""
    
    print("Adding business skills to portfolio...\n")
    
    for skill_data in business_skills:
        try:
            response = requests.post(
                f"{BASE_URL}/api/portfolio/upload",
                json=skill_data,
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code == 201:
                result = response.json()
                print(f"✓ Added: {skill_data['skill']}")
            else:
                print(f"✗ Failed to add {skill_data['skill']}: {response.text}")
                
        except Exception as e:
            print(f"✗ Error adding {skill_data['skill']}: {str(e)}")
    
    print("\n" + "="*50)
    
    # Check stats
    try:
        stats_response = requests.get(f"{BASE_URL}/api/portfolio/stats")
        stats = stats_response.json()
        print(f"\n✓ Portfolio now has {stats['total_documents']} documents")
    except:
        pass
    
    print("\nDone! Restart your server and try again.")

if __name__ == "__main__":
    add_skills()