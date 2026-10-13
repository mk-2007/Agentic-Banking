# Model gateway (Phase 5a)

One interface over interchangeable model providers, so the platform never depends on a single vendor
and every model call is reliable, budgeted and validated. Nothing outside `nexa.llm` talks to a
provider directly.

## Why one adapter serves both Groq and Gemini

Both expose an OpenAI-style `chat/completions` endpoint:

| Provider | Base URL | Key variable | Model variable |
|---|---|---|---|
| Groq | `https://api.groq.com/openai/v1` | `GROQ_API_KEY` | `NEXA_GROQ_MODEL` |
| Gemini | `https://generativelanguage.googleapis.com/v1beta/openai/` | `GEMINI_API_KEY` | `NEXA_GEMINI_MODEL` |

`OpenAiCompatibleProvider` handles both. Adding another OpenAI-compatible provider is a few lines of
configuration in `config/llm.py`.

## What the gateway adds

| Feature | Behaviour |
|---|---|
| Retries | Rate limits, timeouts, 5xx and empty answers are retried with exponential backoff (honouring `Retry-After`, capped) |
| Failover | After a provider's attempts are used up, or if its key or model is rejected, the next provider is tried. With both keys set, Groq down means Gemini answers |
| Token budget | Each case has a token budget, checked **before** every call, so a looping agent cannot burn quota |
| Structured output | Ask for JSON that matches a Pydantic model; the gateway validates it, and on failure shows the model the exact error and asks again (up to 2 repairs) |
| Untrusted text | `wrap_untrusted` fences third-party text (merchant names, memos) and tells the model it is data |
| Accounting | Tokens and cost per case (`UsageLedger`); models without a listed price count as free tier |

**Models are never trusted to return valid JSON.** Provider JSON modes are used when available, but
every reply is parsed and validated against the schema regardless. Fences, chatter around the JSON,
extra fields and wrong types are all handled.

## Setting it up (Windows)

1. Copy `.env.example` to `.env` in the repository root and fill in one or both keys. `.env` is git-ignored.
2. `cd backend`, activate your virtual environment, then `pip install -e ".[dev]"`.
3. From the repository root, see which models your keys can use today:
   `python scripts/llm_smoke_test.py --list-models`
4. If the default model is unavailable, set `NEXA_GROQ_MODEL` / `NEXA_GEMINI_MODEL` in `.env`.
5. Prove it works: `python scripts/llm_smoke_test.py`. Each configured provider makes one validated call
   and reports model, tokens, latency and repairs.

Provider order comes from `NEXA_LLM_PROVIDERS` (default `groq,gemini`, first is primary). A provider
with no key is skipped, so one key is enough.

## Troubleshooting

| Message | Meaning and fix |
|---|---|
| `API key rejected (HTTP 401/403)` | Mistyped or revoked key. Re-copy it into `.env`. |
| `model or endpoint not found ... The provider said: ...` | The model name is retired or not available to your key. Run `--list-models`, then try `--model PROVIDER=NAME`, and once it works put it in `.env` as `NEXA_GROQ_MODEL` or `NEXA_GEMINI_MODEL`. |
| `empty answer (token limit reached...)` | A reasoning model spent its token limit thinking. Raise `default_max_tokens` in `config/llm.py`. |
| `HTTP 429` | Free-tier rate limit. The gateway retries and then fails over; wait a minute and retry. |
| `no provider is configured` | Neither key is set in `.env` or the environment. |

Model ids copied from `--list-models` work with or without a leading `models/`.

## Security notes

- Keys are read from the environment only. They are never logged, never put in error messages (errors
  are redacted), and never stored in the audit log.
- Never paste a key into a chat, issue or commit. If one leaks, revoke it in the provider's console.
- Prompts and replies are not written to any log by the gateway. Audit records (Phase 5b) will store hashes.

## Honest limits

- **Verified live: Groq** (`openai/gpt-oss-20b`, structured call succeeded with no repairs). **Gemini is not yet
  verified**: the default `gemini-2.5-flash` was listed by the API but the chat endpoint answered "not found".
  Try another model with `python scripts/llm_smoke_test.py --model gemini=gemini-flash-latest`.
- **Default model names are my best guess** and model catalogues change often. That is why the model is a
  setting and the smoke script can list what your key allows.
- **Gemini reasoning models spend output tokens thinking.** The default `max_tokens` is 2048 so answers are
  not cut off; an empty answer is retried and the error says why.
- **Groq's strict schema mode works on few models**, so the default is the portable JSON mode plus our own
  validation.
- Streaming and tool calling are not used; agents here call tools through our own tool layer.
- The price table is empty (free tier). Add prices in `config/llm.py` if you move to a paid plan.
