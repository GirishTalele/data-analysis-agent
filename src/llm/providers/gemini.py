from google import genai
from google.genai import types


class GeminiProvider:
    # NOTE: spec/architecture.md and spec/agent.md specify "gemini-3.1-pro",
    # but that model ID does not exist on the live Gemini API for this key
    # (confirmed via client.models.list() — 404 NOT_FOUND). The closest real,
    # available model in the same family is "gemini-3.1-pro-preview". This is
    # a spec-vs-reality conflict (flagged to agent-builder/spec-writer);
    # overridable via AGENT_LLM_MODEL without a code change either way.
    DEFAULT_MODEL = "gemini-3.1-pro-preview"

    def __init__(self, api_key: str, model: str) -> None:
        self._client = genai.Client(api_key=api_key)
        self._model = model or self.DEFAULT_MODEL

    def call_model(self, prompt: str, *, system: str | None = None) -> str:
        config = types.GenerateContentConfig(
            system_instruction=system,
        ) if system else None
        response = self._client.models.generate_content(
            model=self._model,
            contents=prompt,
            config=config,
        )
        return response.text

    def call_model_with_usage(self, prompt: str, *, system: str | None = None):
        from llm.client import LLMResponse

        config = types.GenerateContentConfig(
            system_instruction=system,
        ) if system else None
        response = self._client.models.generate_content(
            model=self._model,
            contents=prompt,
            config=config,
        )
        usage = getattr(response, "usage_metadata", None)
        prompt_tokens = int(getattr(usage, "prompt_token_count", 0) or 0) if usage else 0
        completion_tokens = int(getattr(usage, "candidates_token_count", 0) or 0) if usage else 0
        return LLMResponse(
            text=response.text,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
