from nexa.config import DEFAULT_LIMITS, PRESETS, JsonMode


def test_presets_are_complete_and_distinct() -> None:
    assert set(PRESETS) == {"groq", "gemini"}
    assert all(p.base_url.startswith("https://") for p in PRESETS.values())
    assert len({p.api_key_env for p in PRESETS.values()}) == len(PRESETS)
    assert len({p.model_env for p in PRESETS.values()}) == len(PRESETS)
    assert all(p.default_model for p in PRESETS.values())
    assert all(isinstance(p.json_mode, JsonMode) for p in PRESETS.values())


def test_default_limits_are_bounded() -> None:
    assert DEFAULT_LIMITS.max_attempts_per_provider <= 6
    assert DEFAULT_LIMITS.max_repairs <= 4
    assert DEFAULT_LIMITS.default_max_tokens >= 1024  # reasoning models need room to think
    assert DEFAULT_LIMITS.case_token_budget > DEFAULT_LIMITS.default_max_tokens
