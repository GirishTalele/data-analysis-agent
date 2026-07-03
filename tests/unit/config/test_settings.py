"""Settings + provider auto-detection — no LLM key required."""
import pytest
import os


def test_auto_detects_anthropic(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_ANTHROPIC_API_KEY", "sk-ant-fake")
    monkeypatch.setenv("AGENT_GEMINI_API_KEY", "")
    monkeypatch.setenv("AGENT_LLM_PROVIDER", "")
    monkeypatch.setenv("AGENT_DATABASE_URL", f"sqlite:///{tmp_path}/t.db")

    import config.settings as m
    m._settings = None
    s = m.get_settings()
    assert s.anthropic_api_key == "sk-ant-fake"
    assert s.gemini_api_key == ""


def test_auto_detects_gemini(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("AGENT_GEMINI_API_KEY", "AIza-fake")
    monkeypatch.setenv("AGENT_LLM_PROVIDER", "")
    monkeypatch.setenv("AGENT_DATABASE_URL", f"sqlite:///{tmp_path}/t.db")

    import config.settings as m
    m._settings = None
    s = m.get_settings()
    assert s.gemini_api_key == "AIza-fake"


def test_provider_raises_with_no_key(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("AGENT_GEMINI_API_KEY", "")
    monkeypatch.setenv("AGENT_LLM_PROVIDER", "")
    monkeypatch.setenv("AGENT_DATABASE_URL", f"sqlite:///{tmp_path}/t.db")

    import config.settings as m
    m._settings = None

    from llm.client import _make_provider
    with pytest.raises(RuntimeError, match="No LLM provider configured"):
        _make_provider()


def test_explicit_provider_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_ANTHROPIC_API_KEY", "sk-ant-fake")
    monkeypatch.setenv("AGENT_GEMINI_API_KEY", "AIza-fake")
    monkeypatch.setenv("AGENT_LLM_PROVIDER", "gemini")
    monkeypatch.setenv("AGENT_DATABASE_URL", f"sqlite:///{tmp_path}/t.db")

    import config.settings as m
    m._settings = None
    s = m.get_settings()
    assert s.llm_provider == "gemini"


def test_new_settings_defaults(monkeypatch, tmp_path):
    """spec/architecture.md -> New Settings table — defaults apply when unset."""
    for var in (
        "AGENT_DATA_DIR",
        "AGENT_MAX_UPLOAD_MB",
        "AGENT_SANDBOX_TIMEOUT_SECONDS",
        "AGENT_MAX_SUMMARY_ROWS",
        "AGENT_MAX_SUMMARY_ITEMS",
        "AGENT_MAX_STEPS",
        "AGENT_GEMINI_INPUT_PRICE_PER_1M",
        "AGENT_GEMINI_OUTPUT_PRICE_PER_1M",
        "AGENT_HISTORY_TURNS",
        "LANGCHAIN_TRACING_V2",
        "LANGCHAIN_API_KEY",
        "LANGCHAIN_PROJECT",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("AGENT_DATABASE_URL", f"sqlite:///{tmp_path}/t.db")

    import config.settings as m
    m._settings = None
    s = m.get_settings()

    assert s.data_dir == "./data"
    assert s.max_upload_mb == 100
    assert s.sandbox_timeout_seconds == 20
    assert s.max_summary_rows == 20
    assert s.max_summary_items == 50
    assert s.max_steps == 1
    assert s.gemini_input_price_per_1m == 1.25
    assert s.gemini_output_price_per_1m == 5.00
    assert s.agent_history_turns == 10
    assert s.langchain_tracing_v2 is False
    assert s.langchain_api_key == ""
    assert s.langchain_project == ""


def test_new_settings_env_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_DATABASE_URL", f"sqlite:///{tmp_path}/t.db")
    monkeypatch.setenv("AGENT_DATA_DIR", "/tmp/custom-data")
    monkeypatch.setenv("AGENT_MAX_UPLOAD_MB", "250")
    monkeypatch.setenv("AGENT_SANDBOX_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("AGENT_MAX_SUMMARY_ROWS", "30")
    monkeypatch.setenv("AGENT_MAX_SUMMARY_ITEMS", "75")
    monkeypatch.setenv("AGENT_MAX_STEPS", "5")
    monkeypatch.setenv("AGENT_GEMINI_INPUT_PRICE_PER_1M", "2.5")
    monkeypatch.setenv("AGENT_GEMINI_OUTPUT_PRICE_PER_1M", "10.0")
    monkeypatch.setenv("AGENT_HISTORY_TURNS", "20")

    import config.settings as m
    m._settings = None
    s = m.get_settings()

    assert s.data_dir == "/tmp/custom-data"
    assert s.max_upload_mb == 250
    assert s.sandbox_timeout_seconds == 45
    assert s.max_summary_rows == 30
    assert s.max_summary_items == 75
    assert s.max_steps == 5
    assert s.gemini_input_price_per_1m == 2.5
    assert s.gemini_output_price_per_1m == 10.0
    assert s.agent_history_turns == 20


def test_langsmith_settings_are_unprefixed(monkeypatch, tmp_path):
    """LANGCHAIN_* env vars are bare (no AGENT_ prefix) per LangSmith's convention."""
    monkeypatch.setenv("AGENT_DATABASE_URL", f"sqlite:///{tmp_path}/t.db")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    monkeypatch.setenv("LANGCHAIN_API_KEY", "ls-fake-key")
    monkeypatch.setenv("LANGCHAIN_PROJECT", "data-analysis-agent")
    # Ensure no AGENT_-prefixed variants leak in.
    monkeypatch.delenv("AGENT_LANGCHAIN_TRACING_V2", raising=False)
    monkeypatch.delenv("AGENT_LANGCHAIN_API_KEY", raising=False)
    monkeypatch.delenv("AGENT_LANGCHAIN_PROJECT", raising=False)

    import config.settings as m
    m._settings = None
    s = m.get_settings()

    assert s.langchain_tracing_v2 is True
    assert s.langchain_api_key == "ls-fake-key"
    assert s.langchain_project == "data-analysis-agent"
