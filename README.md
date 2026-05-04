# 🤖 OmniAgent — Multi-Platform AI Agent

A production-ready, autonomous AI agent that operates across **Discord**, **Slack**, **Email**, and **Twitter** — powered by **LangGraph** and **OpenRouter**.

## 🏗️ Architecture

```
              ┌─────────────────────────────────┐
              │        LangGraph Brain           │
              │   (Router → Tools → Responder)   │
              └─────────┬───────────────────────┘
                        │
        ┌───────────────┼───────────────────┐
        │               │                   │
   ┌────▼────┐    ┌─────▼─────┐      ┌─────▼─────┐
   │ Discord │    │   Slack   │      │   Email   │
   │ Adapter │    │  Adapter  │      │  Adapter  │
   └─────────┘    └───────────┘      └───────────┘
        │               │                   │
   ┌────▼────┐    ┌─────▼─────┐      ┌─────▼─────┐
   │ Twitter │    │ Scheduler │      │ Dashboard │
   │ Adapter │    │(APSchedul)│      │(Streamlit)│
   └─────────┘    └───────────┘      └───────────┘
```

## 🚀 Quick Start

### 1. Clone & Install
```bash
git clone <repo-url>
cd multi_platform_agent
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

### 2. Configure `.env`
```env
OPENROUTER_API_KEY=sk-or-...
DISCORD_BOT_TOKEN=...
SLACK_BOT_TOKEN=xoxb-...
SLACK_SIGNING_SECRET=...
SLACK_APP_TOKEN=xapp-...
TWITTER_API_KEY=...
TWITTER_API_SECRET=...
TWITTER_ACCESS_TOKEN=...
TWITTER_ACCESS_TOKEN_SECRET=...
GMAIL_ADDRESS=you@gmail.com
GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
TAVILY_API_KEY=tvly-...
```

### 3. Run Everything
```bash
python run_all.py
```
This launches all services (Discord, Slack, Email, API, Scheduler) in one command.

### 4. Run Individual Services
```bash
python adapters/discord_adapter.py    # Discord bot
python adapters/slack_adapter.py      # Slack bot
python adapters/email_adapter.py      # Email bot
python adapters/twitter_adapter.py    # Twitter (test post)
python api/main.py                    # FastAPI server
streamlit run api/dashboard.py        # Monitoring dashboard
python workflows/scheduler.py         # Automated workflows
```

## 🐳 Docker Deployment
```bash
docker-compose up --build -d
```

## 📁 Project Structure
```
multi_platform_agent/
├── core/
│   ├── brain.py          # LangGraph brain (Router → Tools → Responder)
│   ├── state.py          # AgentState TypedDict
│   ├── tools.py          # Web search, time, URL summarizer
│   └── memory.py         # SQLite conversation persistence
├── adapters/
│   ├── discord_adapter.py  # Discord bot (rate-limited, embeds, slash cmds)
│   ├── slack_adapter.py    # Slack bot (Socket Mode)
│   ├── email_adapter.py    # Gmail IMAP poller + yagmail replies
│   └── twitter_adapter.py  # Tweet posting (cloud-ready)
├── workflows/
│   ├── daily_digest.py   # AI news digest → Email/Discord/Slack
│   ├── news_tweet.py     # AI-generated news tweets
│   └── scheduler.py      # APScheduler (9AM digest, 12/6PM tweets)
├── api/
│   ├── main.py           # FastAPI health/stats/webhooks
│   └── dashboard.py      # Streamlit monitoring dashboard
├── run_all.py            # Supervisor — launches all services
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env
```

## 🧠 Features
- **Multi-Platform**: Discord, Slack, Email, Twitter
- **AI Brain**: LangGraph + OpenRouter (Gemma 4 31B)
- **Tools**: Web search (Tavily), time, URL summarizer
- **Memory**: SQLite-backed conversation history
- **Autonomous**: Scheduled daily digests and news tweets
- **Monitoring**: Streamlit dashboard + FastAPI health checks
- **Production-Ready**: Docker, rate limiting, error handling, logging
