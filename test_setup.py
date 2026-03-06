"""
Test script to verify Cold Email Generator setup
"""
import sys
from pathlib import Path

def check_file_structure():
    """Verify all required files exist"""
    print("🔍 Checking project structure...")
    
    required_files = [
        "app/main.py",
        "app/config.py",
        "app/api/routes.py",
        "app/api/schemas.py",
        "app/core/llm_client.py",
        "app/core/vector_store.py",
        "app/core/prompts.py",
        "app/services/job_extractor.py",
        "app/services/portfolio_matcher.py",
        "app/services/email_generator.py",
        "app/utils/text_cleaner.py",
        "data/portfolio.csv",
        "requirements.txt",
        "init_portfolio.py",
        "README.md"
    ]
    
    missing = []
    for file in required_files:
        if not Path(file).exists():
            missing.append(file)
            print(f"  ✗ Missing: {file}")
        else:
            print(f"  ✓ Found: {file}")
    
    if missing:
        print(f"\n❌ {len(missing)} files are missing!")
        return False
    else:
        print(f"\n✅ All {len(required_files)} required files present!")
        return True


def check_imports():
    """Test if core modules can be imported"""
    print("\n🔍 Checking imports...")
    
    modules = [
        ("app.config", "get_settings"),
        ("app.api.schemas", "EmailGenerationRequest"),
        ("app.core.prompts", "JOB_EXTRACTION_PROMPT"),
        ("app.utils.text_cleaner", "clean_html_text"),
    ]
    
    errors = []
    for module_name, item_name in modules:
        try:
            module = __import__(module_name, fromlist=[item_name])
            getattr(module, item_name)
            print(f"  ✓ {module_name}.{item_name}")
        except Exception as e:
            errors.append((module_name, str(e)))
            print(f"  ✗ {module_name}: {str(e)[:50]}")
    
    if errors:
        print(f"\n❌ {len(errors)} import errors found!")
        return False
    else:
        print(f"\n✅ All imports successful!")
        return True


def check_environment():
    """Check environment setup"""
    print("\n🔍 Checking environment...")
    
    env_file = Path("app/.env")
    if env_file.exists():
        print("  ✓ .env file found")
        
        # Check if GROQ_API_KEY is set
        with open(env_file) as f:
            content = f.read()
            if "GROQ_API_KEY=" in content and "your_groq_api_key" not in content:
                print("  ✓ GROQ_API_KEY appears to be set")
            else:
                print("  ⚠️  GROQ_API_KEY not configured (edit app/.env)")
    else:
        print("  ⚠️  .env file not found (copy from app/.env.example)")


def main():
    """Run all checks"""
    print("="*60)
    print("Cold Email Generator - Setup Verification")
    print("="*60)
    
    structure_ok = check_file_structure()
    imports_ok = check_imports()
    check_environment()
    
    print("\n" + "="*60)
    if structure_ok and imports_ok:
        print("✅ Setup verification passed!")
        print("\nNext steps:")
        print("1. Configure app/.env with your GROQ_API_KEY")
        print("2. Run: python init_portfolio.py")
        print("3. Run: python -m app.main")
        print("4. Visit: http://localhost:8000/docs")
    else:
        print("❌ Setup verification failed!")
        print("\nPlease fix the errors above and try again.")
    print("="*60)


if __name__ == "__main__":
    main()