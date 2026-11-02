"""Quick-ask chat with Google Gemini (free tier from aistudio.google.com; needs `google-genai`)."""
import os

try:
    from google import genai
    from google.genai import errors, types
except ImportError:
    genai = None

from claude_chat import SYSTEM


class GeminiChat:
    name = "Gemini"
    key_hint = ("Нет API-ключа Gemini. Получи бесплатный ключ на aistudio.google.com → Get API key, "
                "вставь его в config.json в \"gemini\": {\"api_key\": \"...\"} и перезапусти виджет.")

    def __init__(self, cfg):
        c = cfg.get("gemini") or {}
        self.model = c.get("model", "gemini-flash-latest")
        # Tried in order when the main model is overloaded (503) or unavailable (404)
        self.fallback_models = c.get("fallback_models", ["gemini-3-flash-preview", "gemini-flash-lite-latest"])
        self.api_key = c.get("api_key") or None  # None -> SDK reads GEMINI_API_KEY / GOOGLE_API_KEY
        self.history = []
        self._client = None

    @property
    def available(self):
        return genai is not None

    @property
    def has_key(self):
        return bool(self.api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))

    def reset(self):
        self.history = []

    def ask(self, question, context, on_text):
        """Blocking: run in a worker thread. Streams answer text to on_text(chunk)."""
        if self._client is None:
            # timeout is in milliseconds: an overloaded model may hold the connection without replying
            self._client = genai.Client(api_key=self.api_key, http_options=types.HttpOptions(timeout=30_000))
        contents = self.history + [types.Content(role="user", parts=[types.Part(text=question)])]
        config = types.GenerateContentConfig(system_instruction=f"{SYSTEM}\n\n{context}")
        models = [self.model] + [m for m in self.fallback_models if m != self.model]
        answer = []
        for i, model in enumerate(models):
            try:
                for chunk in self._client.models.generate_content_stream(model=model, contents=contents, config=config):
                    if chunk.text:
                        answer.append(chunk.text)
                        on_text(chunk.text)
                break
            except Exception as e:
                # Fall back (overloaded, missing model, timeout) only if nothing was printed yet
                # and another model is left; key/request errors are raised as is
                bad_request = isinstance(e, errors.APIError) and e.code in (400, 401, 403)
                if answer or bad_request or i == len(models) - 1:
                    raise
        # History is only extended after a complete answer, so a failed request leaves it valid
        self.history = contents + [types.Content(role="model", parts=[types.Part(text="".join(answer))])]

    def describe_error(self, e):
        if genai and isinstance(e, errors.APIError):
            text = str(e).lower()
            if e.code == 429:
                return "лимит бесплатного тарифа, подожди минуту"
            if e.code in (400, 401, 403) and "key" in text:
                return "неверный API-ключ (gemini.api_key в config.json)"
            if e.code == 404:
                return "модель не найдена — проверь gemini.model в config.json"
            return f"{e.code}: {e.message}"
        return str(e)
