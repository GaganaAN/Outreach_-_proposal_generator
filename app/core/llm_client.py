"""
Multi-LLM Client — supports Groq (LLaMA), OpenAI (GPT), and Google Gemini.

All existing callers use get_llm_client().generate(prompt) which automatically
uses DEFAULT_LLM_PROVIDER from settings (default: openai).

User-facing features (email, proposal) can pass provider='groq'|'openai'|'gemini'
to override the default per-request.
"""
import json
import logging
from typing import Any, Dict, Optional

from app.config import get_settings

logger = logging.getLogger(__name__)


class MultiLLMClient:
    """Unified LLM client supporting Groq, OpenAI, and Google Gemini."""

    def __init__(self):
        self.settings = get_settings()
        self._groq_client = None
        self._openai_client = None
        self._gemini_configured = False
        logger.info(f"MultiLLMClient initialized. Default provider: {self.settings.DEFAULT_LLM_PROVIDER}")

    # ── Provider lazy-init ─────────────────────────────────────────────────────

    def _get_groq(self):
        if self._groq_client is None:
            if not self.settings.GROQ_API_KEY:
                raise ValueError("GROQ_API_KEY not set in .env")
            from groq import Groq
            self._groq_client = Groq(api_key=self.settings.GROQ_API_KEY)
        return self._groq_client

    def _get_openai(self):
        if self._openai_client is None:
            if not self.settings.OPENAI_API_KEY:
                raise ValueError("OPENAI_API_KEY not set in .env")
            from openai import OpenAI
            self._openai_client = OpenAI(api_key=self.settings.OPENAI_API_KEY)
        return self._openai_client

    def _ensure_gemini(self):
        if not self._gemini_configured:
            if not self.settings.GEMINI_API_KEY:
                raise ValueError("GEMINI_API_KEY not set in .env")
            import google.generativeai as genai
            genai.configure(api_key=self.settings.GEMINI_API_KEY)
            self._gemini_configured = True

    # ── Provider-specific generation ───────────────────────────────────────────

    def _generate_groq(self, prompt: str, json_mode: bool, temperature: float, max_tokens: int) -> str:
        client = self._get_groq()
        messages = [
            {"role": "system", "content": "You are a helpful AI assistant." + (" Always respond with valid JSON." if json_mode else "")},
            {"role": "user", "content": prompt},
        ]
        response = client.chat.completions.create(
            model=self.settings.LLM_MODEL,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"} if json_mode else {"type": "text"},
        )
        return response.choices[0].message.content.strip()

    def _generate_openai(self, prompt: str, json_mode: bool, temperature: float, max_tokens: int) -> str:
        client = self._get_openai()
        messages = [
            {"role": "system", "content": "You are a helpful AI assistant." + (" Always respond with valid JSON." if json_mode else "")},
            {"role": "user", "content": prompt},
        ]
        kwargs = dict(
            model=self.settings.OPENAI_MODEL,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        response = client.chat.completions.create(**kwargs)
        return response.choices[0].message.content.strip()

    def _generate_gemini(self, prompt: str, json_mode: bool, temperature: float, max_tokens: int) -> str:
        self._ensure_gemini()
        import google.generativeai as genai
        system = "You are a helpful AI assistant." + (" Always respond with valid JSON." if json_mode else "")
        model = genai.GenerativeModel(
            model_name=self.settings.GEMINI_MODEL,
            system_instruction=system,
            generation_config=genai.GenerationConfig(
                temperature=temperature,
                max_output_tokens=max_tokens,
                response_mime_type="application/json" if json_mode else "text/plain",
            ),
        )
        response = model.generate_content(prompt)
        return response.text.strip()

    # ── Public API (backward-compatible) ──────────────────────────────────────

    def generate(
        self,
        prompt: str,
        provider: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> str:
        """
        Generate text from the specified provider.

        Args:
            prompt:      The input prompt.
            provider:    'groq' | 'openai' | 'gemini' | None (uses DEFAULT_LLM_PROVIDER).
            temperature: Sampling temperature (overrides default).
            max_tokens:  Max output tokens (overrides default).
            json_mode:   Force JSON output.

        Returns:
            Generated text string.
        """
        resolved = (provider or self.settings.DEFAULT_LLM_PROVIDER).lower()
        temp = temperature if temperature is not None else self.settings.LLM_TEMPERATURE
        tokens = max_tokens if max_tokens is not None else self.settings.MAX_TOKENS

        try:
            if resolved == "groq":
                result = self._generate_groq(prompt, json_mode, temp, tokens)
            elif resolved == "gemini":
                result = self._generate_gemini(prompt, json_mode, temp, tokens)
            else:  # openai (default)
                result = self._generate_openai(prompt, json_mode, temp, tokens)

            logger.info(f"[LLM:{resolved}] generation ok — {len(result)} chars")
            return result

        except Exception as e:
            logger.error(f"[LLM:{resolved}] generation failed: {e}")
            raise Exception(f"LLM ({resolved}) generation failed: {e}")

    def generate_json(self, prompt: str, provider: Optional[str] = None) -> Dict[str, Any]:
        """Generate and parse JSON from the LLM. Returns a dict."""
        try:
            response_text = self.generate(prompt, provider=provider, json_mode=True)
            try:
                return json.loads(response_text)
            except json.JSONDecodeError:
                if "```json" in response_text:
                    json_str = response_text.split("```json")[1].split("```")[0].strip()
                    return json.loads(json_str)
                elif "```" in response_text:
                    json_str = response_text.split("```")[1].split("```")[0].strip()
                    return json.loads(json_str)
                raise
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON from LLM: {e}")
            raise Exception(f"LLM did not return valid JSON: {e}")

    def check_health(self, provider: Optional[str] = None) -> bool:
        """Check if the given (or default) provider is reachable."""
        try:
            result = self.generate("Say OK", provider=provider, max_tokens=10)
            return len(result) > 0
        except Exception:
            return False


# ── Singleton ──────────────────────────────────────────────────────────────────
_llm_client: Optional[MultiLLMClient] = None


def get_llm_client() -> MultiLLMClient:
    """Get or create the shared MultiLLMClient singleton."""
    global _llm_client
    if _llm_client is None:
        _llm_client = MultiLLMClient()
    return _llm_client
