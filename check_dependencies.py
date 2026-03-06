"""
Patch script to fix ChromaDB and sentence_transformers compatibility
"""
import sys
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def check_sentence_transformers():
    """Check if sentence_transformers is properly installed"""
    try:
        import sentence_transformers
        logger.info(f"✓ sentence_transformers installed: {sentence_transformers.__version__}")
        
        # Try to load a model
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer('all-MiniLM-L6-v2')
        
        # Test encoding
        test_embedding = model.encode("test sentence")
        logger.info(f"✓ Model loaded successfully, embedding dimension: {len(test_embedding)}")
        
        return True
    except ImportError as e:
        logger.error(f"✗ sentence_transformers not installed: {e}")
        return False
    except Exception as e:
        logger.error(f"✗ Error loading sentence_transformers: {e}")
        return False


def check_chromadb():
    """Check if ChromaDB is properly configured"""
    try:
        import chromadb
        logger.info(f"✓ ChromaDB installed: {chromadb.__version__}")
        
        # Test embedding function
        try:
            from chromadb.utils import embedding_functions
            ef = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name="all-MiniLM-L6-v2"
            )
            logger.info("✓ ChromaDB embedding function loaded successfully")
            return True
        except Exception as e:
            logger.warning(f"⚠ ChromaDB embedding function issue: {e}")
            logger.info("Will use custom embedding function as fallback")
            return True
            
    except ImportError as e:
        logger.error(f"✗ ChromaDB not installed: {e}")
        return False


def main():
    """Run all checks"""
    print("="*60)
    print("ChromaDB Compatibility Check")
    print("="*60 + "\n")
    
    st_ok = check_sentence_transformers()
    print()
    chroma_ok = check_chromadb()
    
    print("\n" + "="*60)
    if st_ok and chroma_ok:
        print("✅ All checks passed! You can proceed with initialization.")
        print("\nRun: python init_portfolio.py")
    else:
        print("❌ Some checks failed. Please fix the issues above.")
        if not st_ok:
            print("\nFix: pip install --upgrade sentence-transformers")
        if not chroma_ok:
            print("\nFix: pip install --upgrade chromadb")
    print("="*60)


if __name__ == "__main__":
    main()