"""
Alternative ChromaDB Vector Store with improved compatibility
"""
import logging
from typing import List, Dict, Any
import chromadb
from chromadb.config import Settings as ChromaSettings

logger = logging.getLogger(__name__)


def get_embedding_function(model_name: str):
    """
    Get embedding function with fallback options
    
    Tries in order:
    1. ChromaDB's SentenceTransformerEmbeddingFunction
    2. Direct SentenceTransformer usage
    3. Default embedding function
    """
    # Try ChromaDB's built-in function first
    try:
        from chromadb.utils import embedding_functions
        ef = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=model_name
        )
        logger.info("Using ChromaDB's SentenceTransformer embedding function")
        return ef
    except Exception as e:
        logger.warning(f"ChromaDB embedding function failed: {e}")
    
    # Try direct SentenceTransformer
    try:
        from sentence_transformers import SentenceTransformer
        
        class DirectEmbeddingFunction:
            def __init__(self, model_name):
                self.model = SentenceTransformer(model_name)
                logger.info(f"Loaded SentenceTransformer model: {model_name}")
            
            def __call__(self, input):
                """Encode input text to embeddings"""
                if isinstance(input, str):
                    input = [input]
                embeddings = self.model.encode(input, convert_to_numpy=True)
                return embeddings.tolist()
        
        ef = DirectEmbeddingFunction(model_name)
        logger.info("Using direct SentenceTransformer embedding function")
        return ef
        
    except Exception as e:
        logger.error(f"Direct SentenceTransformer failed: {e}")
        raise RuntimeError(
            "Failed to initialize embedding function. "
            "Please install sentence-transformers: pip install sentence-transformers"
        )


class VectorStore:
    """ChromaDB vector store for portfolio skills"""
    
    def __init__(self, persist_dir: str = "./chroma_db", 
                 collection_name: str = "portfolio_skills",
                 embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"):
        """
        Initialize ChromaDB client and collection
        
        Args:
            persist_dir: Directory for ChromaDB persistence
            collection_name: Name of the collection
            embedding_model: Model name for embeddings
        """
        self.persist_dir = persist_dir
        self.collection_name = collection_name
        
        # Initialize ChromaDB with persistence
        try:
            self.client = chromadb.PersistentClient(
                path=persist_dir,
                settings=ChromaSettings(
                    anonymized_telemetry=False,
                    allow_reset=True
                )
            )
            logger.info(f"ChromaDB client initialized at {persist_dir}")
        except Exception as e:
            logger.error(f"Failed to initialize ChromaDB client: {e}")
            raise
        
        # Get embedding function
        self.embedding_function = get_embedding_function(embedding_model)
        
        # Get or create collection
        try:
            self.collection = self.client.get_collection(
                name=collection_name,
                embedding_function=self.embedding_function
            )
            logger.info(f"Loaded existing collection: {collection_name}")
        except Exception:
            self.collection = self.client.create_collection(
                name=collection_name,
                embedding_function=self.embedding_function,
                metadata={"description": "Portfolio skills and projects"}
            )
            logger.info(f"Created new collection: {collection_name}")
    
    def add_portfolio(
        self,
        skill: str,
        portfolio_link: str,
        projects: List[str],
        description: str = ""
    ) -> str:
        """
        Add a portfolio entry to the vector store
        
        Args:
            skill: Skill name (e.g., "Python", "React")
            portfolio_link: URL to portfolio/project page
            projects: List of project names/descriptions
            description: Additional description
            
        Returns:
            Document ID
        """
        try:
            # Create document text for embedding
            document_text = f"Skill: {skill}\nProjects: {', '.join(projects)}\nDescription: {description}"
            
            # Generate unique ID
            doc_id = f"skill_{skill.lower().replace(' ', '_')}_{hash(portfolio_link) % 10000}"
            
            # Add to collection
            self.collection.add(
                documents=[document_text],
                metadatas=[{
                    "skill": skill,
                    "portfolio_link": portfolio_link,
                    "projects": "|".join(projects),
                    "description": description
                }],
                ids=[doc_id]
            )
            
            logger.info(f"Added portfolio entry: {skill}")
            return doc_id
            
        except Exception as e:
            logger.error(f"Error adding portfolio: {str(e)}")
            raise
    
    def search_skills(
        self,
        skills: List[str],
        top_k: int = 3
    ) -> List[Dict[str, Any]]:
        """
        Search for portfolio entries matching given skills
        
        Args:
            skills: List of skills to search for
            top_k: Number of results per skill
            
        Returns:
            List of matched portfolio entries with relevance scores
        """
        try:
            all_results = []
            
            for skill in skills:
                # Query collection with just the skill name (not formatted)
                query_text = skill  # Simple query, let embeddings do the work
                
                logger.debug(f"Querying for skill: '{query_text}'")
                
                # Query collection
                results = self.collection.query(
                    query_texts=[query_text],
                    n_results=min(top_k, max(1, self.count_documents()))
                )
                
                logger.debug(f"Raw results for '{skill}': {results.get('distances', [[]])[0][:3] if results.get('distances') else 'No distances'}")
                
                # Process results
                if results['ids'] and len(results['ids'][0]) > 0:
                    for i in range(len(results['ids'][0])):
                        metadata = results['metadatas'][0][i]
                        
                        # Get distance - ChromaDB returns different ranges based on metric
                        distance = results['distances'][0][i] if 'distances' in results and results['distances'] else 1.0
                        
                        # ChromaDB with cosine similarity returns squared L2 distance
                        # Range is typically [0, 4] where 0 = identical
                        # Convert to similarity score [0, 1]
                        if distance <= 2.0:
                            # Good range for cosine distance
                            similarity_score = max(0.0, 1.0 - (distance / 2.0))
                        else:
                            # Fallback for other metrics
                            similarity_score = max(0.0, 1.0 / (1.0 + distance))
                        
                        all_results.append({
                            "skill": metadata['skill'],
                            "portfolio_link": metadata['portfolio_link'],
                            "projects": metadata['projects'].split('|'),
                            "relevance_score": round(similarity_score, 3),
                            "query_skill": skill,
                            "_debug_distance": distance  # Debug info
                        })
            
            # Sort by relevance and remove duplicates
            seen_links = set()
            unique_results = []
            for result in sorted(all_results, key=lambda x: x['relevance_score'], reverse=True):
                if result['portfolio_link'] not in seen_links:
                    seen_links.add(result['portfolio_link'])
                    unique_results.append(result)
            
            logger.info(f"Found {len(unique_results)} unique portfolio matches")
            
            # Log scores for debugging
            if unique_results:
                top_scores = [(r['skill'], f"sim={r['relevance_score']:.3f}, dist={r.get('_debug_distance', 'N/A')}") for r in unique_results[:5]]
                logger.info(f"Top matches: {top_scores}")
            
            # Remove debug info before returning
            for result in unique_results:
                result.pop('_debug_distance', None)
            
            return unique_results
            
        except Exception as e:
            logger.error(f"Error searching skills: {str(e)}")
            raise
    
    def count_documents(self) -> int:
        """Get total number of documents in collection"""
        try:
            return self.collection.count()
        except:
            return 0
    
    def reset_collection(self):
        """Reset the collection (delete all data)"""
        try:
            self.client.delete_collection(self.collection_name)
            self.collection = self.client.create_collection(
                name=self.collection_name,
                embedding_function=self.embedding_function
            )
            logger.info("Collection reset successfully")
        except Exception as e:
            logger.error(f"Error resetting collection: {str(e)}")
            raise
    
    def check_health(self) -> bool:
        """Check if vector store is healthy"""
        try:
            self.collection.count()
            return True
        except:
            return False


# Singleton instance
_vector_store = None


def get_vector_store(
    persist_dir: str = "./chroma_db",
    collection_name: str = "portfolio_skills",
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
) -> VectorStore:
    """Get or create vector store singleton"""
    global _vector_store
    if _vector_store is None:
        _vector_store = VectorStore(
            persist_dir=persist_dir,
            collection_name=collection_name,
            embedding_model=embedding_model
        )
    return _vector_store