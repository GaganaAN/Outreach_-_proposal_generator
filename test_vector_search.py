"""
Diagnostic script to test ChromaDB vector search
"""
import sys
sys.path.insert(0, '.')

from app.core.vector_store import get_vector_store
from app.config import get_settings

def test_vector_search():
    """Test vector search with debug output"""
    
    print("="*60)
    print("Vector Search Diagnostic Test")
    print("="*60)
    
    # Initialize
    vector_store = get_vector_store()
    
    # Check document count
    count = vector_store.count_documents()
    print(f"\n✓ Portfolio has {count} documents")
    
    if count == 0:
        print("\n❌ No documents in database! Run: python init_portfolio.py")
        return
    
    # Test searches
    test_skills = [
        "Python",           # Exact match (should be high)
        "Programming",      # Similar concept (should be medium)
        "Financial Planning",  # Different domain (should be low)
        "React"             # Exact match (should be high)
    ]
    
    print(f"\n{'='*60}")
    print("Testing searches...")
    print(f"{'='*60}\n")
    
    for skill in test_skills:
        print(f"\n🔍 Searching for: '{skill}'")
        print("-" * 40)
        
        results = vector_store.search_skills([skill], top_k=3)
        
        if results:
            for i, result in enumerate(results[:3], 1):
                print(f"  {i}. {result['skill']}")
                print(f"     Score: {result['relevance_score']:.3f}")
                print(f"     Link: {result['portfolio_link']}")
                if '_debug_distance' in result:
                    print(f"     Raw Distance: {result['_debug_distance']:.3f}")
        else:
            print("  ❌ No results found")
    
    print(f"\n{'='*60}")
    print("Diagnosis")
    print(f"{'='*60}")
    
    # Analyze results
    all_results = vector_store.search_skills(test_skills, top_k=5)
    
    if not all_results:
        print("\n❌ NO RESULTS AT ALL")
        print("   Possible causes:")
        print("   1. Embedding function not working")
        print("   2. Collection empty or corrupted")
        print("   3. Query format issue")
    else:
        scores = [r['relevance_score'] for r in all_results]
        avg_score = sum(scores) / len(scores)
        max_score = max(scores)
        min_score = min(scores)
        
        print(f"\n✓ Found {len(all_results)} total results")
        print(f"  Average score: {avg_score:.3f}")
        print(f"  Max score: {max_score:.3f}")
        print(f"  Min score: {min_score:.3f}")
        
        if max_score < 0.3:
            print("\n⚠️  ALL SCORES ARE LOW (<0.3)")
            print("   This means:")
            print("   1. Skills in portfolio don't match test queries")
            print("   2. Need to add relevant skills to portfolio")
            print("   3. OR test with skills that exist in portfolio")
        elif max_score >= 0.3:
            print("\n✓ Some good matches found (≥0.3)")
            high_quality = [r for r in all_results if r['relevance_score'] >= 0.3]
            print(f"  {len(high_quality)} matches above threshold")
    
    print(f"\n{'='*60}\n")


if __name__ == "__main__":
    try:
        test_vector_search()
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()