"""
Multi-LLM Client — supports Groq (LLaMA), OpenAI (GPT), Google Gemini, and Azure OpenAI.

All existing callers use get_llm_client().generate(prompt) which automatically
uses DEFAULT_LLM_PROVIDER from settings.

User-facing features (email, proposal) can pass provider='groq'|'openai'|'gemini'|'azure'
to override the default per-request.
"""
import json
import logging
from typing import Any, Dict, Optional

from app.config import get_settings

logger = logging.getLogger(__name__)

# Cost per 1M tokens (USD) — update if provider pricing changes
_COST_RATES: Dict[str, Dict[str, float]] = {
    "groq":   {"input": 0.59,  "output": 0.79},   # llama-3.3-70b-versatile
    "openai": {"input": 0.15,  "output": 0.60},   # gpt-4o-mini
    "gemini": {"input": 0.075, "output": 0.30},   # gemini-1.5-flash
    "azure":  {"input": 0.15,  "output": 0.60},   # gpt-4.1-mini (approx gpt-4o-mini tier)
}


def compute_llm_cost(provider: str, tokens_in: int, tokens_out: int) -> float:
    """Return estimated USD cost for a single LLM call."""
    rates = _COST_RATES.get(provider.lower(), {"input": 0.15, "output": 0.60})
    return (tokens_in * rates["input"] + tokens_out * rates["output"]) / 1_000_000


class MultiLLMClient:
    """Unified LLM client supporting Groq, OpenAI, Google Gemini, and Azure OpenAI."""

    def __init__(self):
        self.settings = get_settings()
        self._groq_client = None
        self._openai_client = None
        self._azure_client = None
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

    def _get_azure(self):
        if self._azure_client is None:
            if not self.settings.AZURE_OPENAI_API_KEY:
                raise ValueError("AZURE_OPENAI_API_KEY not set in .env")
            if not self.settings.AZURE_OPENAI_ENDPOINT:
                raise ValueError("AZURE_OPENAI_ENDPOINT not set in .env")
            from openai import AzureOpenAI
            self._azure_client = AzureOpenAI(
                api_key=self.settings.AZURE_OPENAI_API_KEY,
                azure_endpoint=self.settings.AZURE_OPENAI_ENDPOINT,
                api_version=self.settings.AZURE_OPENAI_API_VERSION,
            )
        return self._azure_client

    def _ensure_gemini(self):
        if not self._gemini_configured:
            if not self.settings.GEMINI_API_KEY:
                raise ValueError("GEMINI_API_KEY not set in .env")
            import google.generativeai as genai
            genai.configure(api_key=self.settings.GEMINI_API_KEY)
            self._gemini_configured = True

    # ── Provider-specific generation ───────────────────────────────────────────

    # Each _generate_* returns (text, tokens_in, tokens_out).
    # generate() unwraps and returns just the text — all existing callers unchanged.

    def _generate_groq(self, prompt: str, json_mode: bool, temperature: float, max_tokens: int):
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
        usage = response.usage
        return (
            response.choices[0].message.content.strip(),
            getattr(usage, "prompt_tokens", 0) or 0,
            getattr(usage, "completion_tokens", 0) or 0,
        )

    def _generate_openai(self, prompt: str, json_mode: bool, temperature: float, max_tokens: int):
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
        usage = response.usage
        return (
            response.choices[0].message.content.strip(),
            getattr(usage, "prompt_tokens", 0) or 0,
            getattr(usage, "completion_tokens", 0) or 0,
        )

    def _generate_gemini(self, prompt: str, json_mode: bool, temperature: float, max_tokens: int):
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
        meta = getattr(response, "usage_metadata", None)
        return (
            response.text.strip(),
            getattr(meta, "prompt_token_count", 0) or 0,
            getattr(meta, "candidates_token_count", 0) or 0,
        )

    def _generate_azure(self, prompt: str, json_mode: bool, temperature: float, max_tokens: int):
        client = self._get_azure()
        messages = [
            {"role": "system", "content": "You are a helpful AI assistant." + (" Always respond with valid JSON." if json_mode else "")},
            {"role": "user", "content": prompt},
        ]
        kwargs = dict(
            model=self.settings.AZURE_OPENAI_DEPLOYMENT_NAME,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        response = client.chat.completions.create(**kwargs)
        usage = response.usage
        return (
            response.choices[0].message.content.strip(),
            getattr(usage, "prompt_tokens", 0) or 0,
            getattr(usage, "completion_tokens", 0) or 0,
        )

    # ── Public API ─────────────────────────────────────────────────────────────

    def _dispatch(self, resolved: str, prompt: str, json_mode: bool, temp: float, tokens: int):
        """Call the right provider and return (text, in_tok, out_tok)."""
        if resolved == "groq":
            return self._generate_groq(prompt, json_mode, temp, tokens)
        elif resolved == "gemini":
            return self._generate_gemini(prompt, json_mode, temp, tokens)
        elif resolved == "azure":
            return self._generate_azure(prompt, json_mode, temp, tokens)
        else:
            return self._generate_openai(prompt, json_mode, temp, tokens)

    def generate(
        self,
        prompt: str,
        provider: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> str:
        """Generate text. Returns string only — backward-compatible with all existing callers."""
        resolved = (provider or self.settings.DEFAULT_LLM_PROVIDER).lower()
        temp = temperature if temperature is not None else self.settings.LLM_TEMPERATURE
        tokens = max_tokens if max_tokens is not None else self.settings.MAX_TOKENS
        try:
            text, _, _ = self._dispatch(resolved, prompt, json_mode, temp, tokens)
            logger.info(f"[LLM:{resolved}] generation ok — {len(text)} chars")
            return text
        except Exception as e:
            logger.error(f"[LLM:{resolved}] generation failed: {e}")
            raise Exception(f"LLM ({resolved}) generation failed: {e}")

    def generate_with_usage(
        self,
        prompt: str,
        provider: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
    ):
        """Generate text and return (text, tokens_in, tokens_out)."""
        resolved = (provider or self.settings.DEFAULT_LLM_PROVIDER).lower()
        temp = temperature if temperature is not None else self.settings.LLM_TEMPERATURE
        tokens = max_tokens if max_tokens is not None else self.settings.MAX_TOKENS
        try:
            text, tok_in, tok_out = self._dispatch(resolved, prompt, json_mode, temp, tokens)
            logger.info(f"[LLM:{resolved}] generation ok — {len(text)} chars | in={tok_in} out={tok_out}")
            return text, tok_in, tok_out
        except Exception as e:
            logger.error(f"[LLM:{resolved}] generation failed: {e}")
            raise Exception(f"LLM ({resolved}) generation failed: {e}")

    def generate_json(self, prompt: str, provider: Optional[str] = None) -> Dict[str, Any]:
        """Generate and parse JSON. Returns dict only — backward-compatible."""
        result, _, _ = self.generate_json_with_usage(prompt, provider=provider)
        return result

    def generate_json_with_usage(
        self, prompt: str, provider: Optional[str] = None
    ):
        """Generate and parse JSON. Returns (dict, tokens_in, tokens_out)."""
        try:
            text, tok_in, tok_out = self.generate_with_usage(prompt, provider=provider, json_mode=True)
            try:
                return json.loads(text), tok_in, tok_out
            except json.JSONDecodeError:
                if "```json" in text:
                    json_str = text.split("```json")[1].split("```")[0].strip()
                    return json.loads(json_str), tok_in, tok_out
                elif "```" in text:
                    json_str = text.split("```")[1].split("```")[0].strip()
                    return json.loads(json_str), tok_in, tok_out
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
