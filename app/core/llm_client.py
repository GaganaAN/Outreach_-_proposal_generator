"""
LLM Client for interacting with LLaMA 3.1 via Groq API
"""
import json
import logging
from typing import Dict, Any, Optional
from groq import Groq
from app.config import get_settings

logger = logging.getLogger(__name__)


class LLMClient:
    """Client for LLaMA 3.1 via Groq API"""
    
    def __init__(self):
        """Initialize LLM client with Groq"""
        self.settings = get_settings()
        
        if not self.settings.GROQ_API_KEY:
            raise ValueError("GROQ_API_KEY not found in environment variables")
        
        self.client = Groq(api_key=self.settings.GROQ_API_KEY)
        self.model = self.settings.LLM_MODEL
        self.temperature = self.settings.LLM_TEMPERATURE
        self.max_tokens = self.settings.MAX_TOKENS
        
        logger.info(f"LLM Client initialized with model: {self.model}")
    
    def generate(
        self,
        prompt: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        json_mode: bool = False
    ) -> str:
        """
        Generate completion from LLM
        
        Args:
            prompt: Input prompt
            temperature: Sampling temperature (overrides default)
            max_tokens: Maximum tokens to generate (overrides default)
            json_mode: If True, forces JSON output
            
        Returns:
            Generated text
        """
        try:
            messages = [
                {
                    "role": "system",
                    "content": "You are a helpful AI assistant." + 
                               (" Always respond with valid JSON." if json_mode else "")
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ]
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature or self.temperature,
                max_tokens=max_tokens or self.max_tokens,
                response_format={"type": "json_object"} if json_mode else {"type": "text"}
            )
            
            result = response.choices[0].message.content
            logger.info(f"LLM generation successful. Output length: {len(result)} chars")
            
            return result.strip()
            
        except Exception as e:
            logger.error(f"LLM generation error: {str(e)}")
            raise Exception(f"Failed to generate response from LLM: {str(e)}")
    
    def generate_json(self, prompt: str) -> Dict[str, Any]:
        """
        Generate JSON output from LLM
        
        Args:
            prompt: Input prompt
            
        Returns:
            Parsed JSON dict
        """
        try:
            response_text = self.generate(prompt, json_mode=True)
            
            # Try to parse JSON
            try:
                return json.loads(response_text)
            except json.JSONDecodeError:
                # Try to extract JSON from markdown code blocks
                if "```json" in response_text:
                    json_str = response_text.split("```json")[1].split("```")[0].strip()
                    return json.loads(json_str)
                elif "```" in response_text:
                    json_str = response_text.split("```")[1].split("```")[0].strip()
                    return json.loads(json_str)
                else:
                    raise
                    
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON from LLM: {str(e)}")
            logger.error(f"Raw response: {response_text[:500]}")
            raise Exception(f"LLM did not return valid JSON: {str(e)}")
        except Exception as e:
            logger.error(f"Error generating JSON from LLM: {str(e)}")
            raise
    
    def check_health(self) -> bool:
        """
        Check if LLM service is healthy
        
        Returns:
            True if healthy, False otherwise
        """
        try:
            test_response = self.generate("Say 'OK'", max_tokens=10)
            return len(test_response) > 0
        except:
            return False


# Singleton instance
_llm_client = None


def get_llm_client() -> LLMClient:
    """Get or create LLM client singleton"""
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client