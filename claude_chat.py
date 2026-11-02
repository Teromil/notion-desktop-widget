"""Quick-ask chat with Claude for the widget (needs the `anthropic` package)."""
import os

try:
    import anthropic
except ImportError:
    anthropic = None

SYSTEM = (
    "Ты — быстрый помощник в маленьком виджете на рабочем столе Windows. "
    "Отвечай кратко и по делу, на языке вопроса. Окно узкое: без таблиц и тяжёлого Markdown, "
    "списки — короткими строками. Ниже контекст: задачи пользователя из Notion и Google Календаря — "
    "используй его, когда вопрос про планы, расписание или дела."
)


class ClaudeChat:
    name = "Claude"
    key_hint = ("Нет API-ключа Claude. Создай ключ на platform.claude.com → API keys, "
                "вставь его в config.json в \"claude\": {\"api_key\": \"...\"} и перезапусти виджет.")

    def __init__(self, cfg):
        c = cfg.get("claude") or {}
        self.model = c.get("model", "claude-opus-5-5")
        self.effort = c.get("effort", "low")  # quick answers; raise to "medium"/"high" for harder questions
        self.api_key = c.get("api_key") or None  # None -> SDK reads ANTHROPIC_API_KEY
        self.history = []
        self._client = None

    @property
    def available(self):
        return anthropic is not None

    @property
    def has_key(self):
        return bool(self.api_key or os.environ.get("ANTHROPIC_API_KEY"))

    def reset(self):
        self.history = []

    def ask(self, question, context, on_text):
        """Blocking: run in a worker thread. Streams answer text to on_text(chunk)."""
        if self._client is None:
            self._client = anthropic.Anthropic(api_key=self.api_key)
        self.history.append({"role": "user", "content": question})
        try:
            with self._client.beta.messages.stream(
                model=self.model,
                max_tokens=4000,
                system=f"{SYSTEM}\n\n{context}",
                messages=self.history,
                output_config={"effort": self.effort},
                # If a request is declined by safety classifiers, the API retries it on a fallback model
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            ) as stream:
                for text in stream.text_stream:
                    on_text(text)
                final = stream.get_final_message()
        except Exception:
            self.history.pop()  # keep history valid for the next question
            raise
        if final.stop_reason == "refusal":
            on_text("\n[запрос отклонён]")
        self.history.append({"role": "assistant", "content": final.content})

    def describe_error(self, e):
        return describe_error(e)


def describe_error(e):
    if anthropic:
        if isinstance(e, anthropic.AuthenticationError):
            return "неверный API-ключ (claude.api_key в config.json)"
        if isinstance(e, anthropic.RateLimitError):
            return "слишком много запросов, попробуй через минуту"
        if isinstance(e, anthropic.APIConnectionError):
            return "нет соединения с API"
        if isinstance(e, anthropic.APIStatusError):
            return f"{e.status_code}: {e.message}"
    return str(e)
