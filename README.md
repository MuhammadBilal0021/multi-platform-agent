# OmniAgent
A single-tenant multi-platform assistant using LangGraph and OpenRouter. Discord and Slack provide interactive chat; signed email commands are optional. Scheduled workflows generate drafts by default.

This is a portfolio/reference application with tested security boundaries, not a claim of production certification.

## Setup
Use Python 3.13. Clone https://github.com/MuhammadBilal0021/multi-platform-agent.git, enter the repository, create a virtual environment with python -m venv .venv, activate it, then run pip install -r requirements.txt.

Copy .env.example to .env and configure only the services you use. Set OPENROUTER_API_KEY, a supported OPENROUTER_MODEL, ALLOWED_USERS (actual platform IDs), and ALLOWED_TOOLS. Both allow-lists deny by default. Environment configuration is an administrator boundary.

Generate random secrets with python -c "import secrets; print(secrets.token_urlsafe(32))". Set OMNI_ADMIN_TOKEN to protect monitoring. EMAIL_COMMAND_SECRET is a separate secret for optional signed email commands. Never commit real tokens.

Run python run_all.py for adapters/API/scheduler. Run streamlit run api/dashboard.py for the dashboard. Missing platform credentials skip that adapter. Include system in ALLOWED_USERS if scheduled workflows should generate content. ENABLE_PUBLISHING=false keeps scheduled output as drafts; enable only after reviewing recipients and permissions. ENABLE_TWITTER_WORKFLOW independently enables that scheduled job.

## Architecture and boundaries
Adapters supply verified platform identities to a shared graph: router -> tool executor -> router -> responder. Execution-time tool allow-lists remain authoritative. Conversation history and pending actions are scoped by platform, user, workspace and conversation, separating DMs from public channels. Each new run starts with fresh safety counters. /reset clears history and pending checkpoints for the current conversation.

Approval prompts show exact arguments, an expiring nonce and CANCEL. Normal chat cannot approve an action. Checkpointed tool tasks avoid repeating completed tools when resuming a later approval; external side effects still require delivery idempotency. The demonstration destructive tool is a dry run.

URL retrieval permits public HTTP(S) destinations only, validates DNS and every redirect, pins connections to validated addresses while preserving TLS hostname verification, and caps bytes/time. Retrieved content remains untrusted; these controls do not prove immunity to prompt injection.

Monitoring requires a bearer admin token. Old unsigned /webhook/slack and /webhook/email routes return 410. Use Slack Bolt (Socket Mode or signed HTTP).

## Signed email commands
Unsigned email is ignored even when its From address is allow-listed. A trusted sender attaches X-Omniagent-Timestamp (Unix seconds) and X-Omniagent-Signature (hex HMAC-SHA256). Sign the UTF-8 result of:

    json.dumps([sender_email, decoded_subject, stripped_plain_text_body, str(timestamp)],
               ensure_ascii=True, separators=(",", ":"))

Use EMAIL_COMMAND_SECRET as the key. Timestamps must be within five minutes; signatures are consumed once in persistent storage. Keep signing secrets out of email bodies. Signed body text CONFIRM <nonce> or CANCEL reaches the approval gate without a subject prefix.

## Limits and delivery
Four active graph runs; 60 requests per authenticated user/platform/hour by default (MAX_REQUESTS_PER_HOUR). Model output is capped at 1,200 tokens; calls time out; graph steps and repeated tool calls are bounded. MAX_TASK_USD is a post-response estimate, not a hard billing ceiling. Provider usage/tool fees can differ. Configure PROMPT_USD_PER_MTOK and COMPLETION_USD_PER_MTOK for your model.

Scheduled deliveries reserve a persistent key per time slot/destination before sending. Uncertain/failed deliveries are not automatically retried: inspect data/delivery.db and the destination before operator reconciliation. This favors avoiding duplicates over guaranteed delivery. Ordinary chat replies are not an exactly-once distributed delivery service.

History is bounded to 10,000 rows and seven days, pruned during writes. Completed graph checkpoints are deleted. Pending approvals expire after five minutes but abandoned checkpoint records may remain until reset/operator cleanup. Protect the data directory; logs contain conversation text. /health reports the API process, not all adapter connections.

## Docker and migration
Run docker compose up --build. A shared named volume stores agent/dashboard data under /app/data. Ports bind to localhost. Run one agent replica; multi-replica coordination is unsupported. Remote deployments need an authenticated TLS reverse proxy.

Previous api/logs.db and api/checkpoints.db are not imported automatically. New conversation keys intentionally start fresh to prevent mixing old private/public context. Archive old files securely and exclude them from images. Existing local secrets and Git history are unaffected.

## Offline validation
Run pip install -r requirements-dev.txt then python -m pytest -q. Tests mock providers and cover approval, resume, reset, privacy scope, SSRF, signed-email replay, monitoring access and duplicate delivery. CI also checks dependency consistency and advisories. Legacy root debug/test scripts may make live calls; pytest.ini restricts collection to tests/.

Live platform credentials, current provider model availability and real task quality require separate validation. See docs/verification.md. Future work: adapter health/restart supervision, prompt-injection evaluations and a measured task-success/latency benchmark.
