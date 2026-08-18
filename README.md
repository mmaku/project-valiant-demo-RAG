# Valiant AI Engine

An agentic **RAG** (Retrieval-Augmented Generation) API built on **FastAPI** and **LangGraph**,
running on the **Azure** stack: Azure OpenAI for LLMs and embeddings, Azure AI Search for
retrieval. The application exposes a single agentic chat endpoint — `POST /api/chat/get_answer`.

The application assumes that the **Azure AI Search index already exists** — it queries the index but does
not build it. Document ingestion (index building) is out of scope for this repository and lives in a
separate pipeline.

## Architecture at a glance

- **Main agent** — a LangGraph ReAct loop that calls tools. It currently has one internal
  tool: `rag_agent_tool`.
- **`rag_agent_tool`** — a separate LangGraph sub-agent over Azure AI Search, treated by the main
  agent as just another tool. The sub-agent has **one** search tool:
  - `get_information_from_rag_documents` — hybrid search in **Azure AI Search** (keywords
    + vectors).

## Requirements

| Component | Version / notes |
|---|---|
| **Python** | 3.13+ (see `.python-version`, [pyproject.toml](pyproject.toml)) |
| **uv** | dependency and environment manager — [installation guide](https://docs.astral.sh/uv/getting-started/installation/) |
| **Docker** + **Docker Compose** | optional — for running in a container |
| **Azure OpenAI** | a resource with deployments named: `gpt-standard`, `gpt-51`, `gpt-52`, `text-embedding-3-large` |
| **Azure AI Search** | an existing index (hybrid search) |

> **Azure OpenAI deployment names are hardcoded** ([app/api/config/settings/base.py:56-62](app/api/config/settings/base.py#L56-L62)):
> `gpt-standard`, `gpt-51`, `gpt-52`, `text-embedding-3-large`. The Azure OpenAI resource must expose
> deployments with exactly these names.

## Configuration (`.env`)

The **[.env.example](.env.example)** file is a ready-made **template (example) of the `.env` file** — it
contains all supported keys. Copy it and fill in the values:

```powershell
copy .env.example .env
```

Place `.env` in the **repository root** — this works both locally (the application looks for `.env`
by walking up the directory tree) and in Docker (Compose reads `env_file: .env`). Alternatively, you can
set the variables directly in a PowerShell session via `$env:NAME = "..."`.

> **All `AZURE_*` variables are required** (they have no default values). The settings
> (`settings = BackendSettings()`) are built at application startup, so **a missing value for any one of
> them means the application will not start** — this also applies to CLI mode (`python main.py chat`),
> even with `--mock-rag`. The simplest path: copy `.env.example` (it contains the complete set of keys)
> and fill it in.

### Environment variables

| Variable | Required? | Default | Description |
|---|---|---|---|
| `AZURE_OPENAI_ENDPOINT` | ✅ yes | — | Azure OpenAI resource endpoint |
| `AZURE_OPENAI_API_KEY` | ✅ yes | — | Azure OpenAI API key |
| `AZURE_SEARCH_ENDPOINT` | ✅ yes | — | Azure AI Search endpoint |
| `AZURE_SEARCH_API_KEY` | ✅ yes | — | Azure AI Search API key |
| `AZURE_SEARCH_INDEX_NAME` | ✅ yes | — | name of the index in Azure AI Search |
| `AZURE_SEARCH_SEMANTIC_CONFIG` | ✅ yes | (`default` in `.env.example`) | name of the index's semantic configuration |
| `FAST_API_ENVIRONMENT` | ⬜ no | `dev` | settings profile: `dev` / `staging` / `prod` |
| `RUN_FROM_FILE` | ⬜ no | `False` | `true` → `python main.py` starts the uvicorn server |
| `API_PORT` | ⬜ no | `7861` | host port in Docker (mapped to 8000 in the container) |
| `SERVER_HOST` | ⬜ no | `0.0.0.0` | server host (locally) |


> In `--mock-rag` mode the `AZURE_SEARCH_*` keys must **exist** in `.env` (they may have empty values —
> `.env.example` already contains them), but `AZURE_OPENAI_*` must be real, because the main agent
> actually calls Azure OpenAI.

## Running locally (without Docker)

> **Important:** the import root is the **`app/`** directory — run Python from `app/`.

```powershell
# 1. Install the dependencies (from the repo root)
uv sync

# 2. Configure .env (see above) or set the variables in the session, e.g.:
$env:RUN_FROM_FILE = "true"

# 3. Enter the app/ directory and start the server
cd app
uv run python main.py
# or directly via uvicorn:
uv run uvicorn main:backend_app --host 0.0.0.0 --port 8000
```

You can also use the shortcuts from the [Makefile](Makefile): `make sync` (install) and `make run`
(uvicorn with hot reload).

By default the server starts over **HTTP** on port **8000**.
Once it is up:

- Health check: `GET http://localhost:8000/health`
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
- Chat: `POST http://localhost:8000/api/chat/get_answer`

## Quick agent test from the CLI (without a server)

`main.py` has a `chat` subcommand that runs the main agent once and prints the full `ChatOutput`
as JSON (the same logic as `POST /api/chat/get_answer`):

```powershell
cd app
uv run python main.py chat                                   # default question (IT service desk), real RAG
uv run python main.py chat -q "Your question" --mock-rag     # custom question, mocked RAG (skips Azure Search)
uv run python main.py chat --mock-rag --user-id error        # mocked "no results in the documents" path
```

Flags:

- `-q` / `--question` — the question for the agent (defaults to a sample IT service desk question).
- `--mock-rag` / `--no-mock-rag` — mock the RAG (defaults to `--no-mock-rag`, i.e. the real sub-agent;
  `--mock-rag` returns a canned response without Azure AI Search).
- `--user-id error` — in mock mode, forces the "no results" path.

> The application requires the **complete** set of `AZURE_*` variables (settings load at import). Without
> `--mock-rag`, working `AZURE_SEARCH_*` keys are also needed.

## Running in Docker

The image is built from the [Dockerfile](Dockerfile) in the repo root (`WORKDIR /valiant_ai/app`), and the
container starts over **HTTP**.

### What you need

1. **Docker** and **Docker Compose**.
2. A **`.env` file in the repo root** — Compose reads it via `env_file: .env` (see the
   [Configuration](#configuration-env) section).

### Commands

```powershell
# Build the image and run the container in the background
docker compose up -d --build

# Follow the logs
docker compose logs -f

# Stop and remove the container
docker compose down
```

- The container listens internally on port **8000** (HTTP), exposed on the host as **`API_PORT`**
  (default **7861**) → mapping `7861:8000`. Change the host port by setting `API_PORT` in `.env`.
- Access after startup: `http://localhost:7861/health`, Swagger: `http://localhost:7861/docs`.
- Configuration in [compose.yaml](compose.yaml): `restart: unless-stopped` and a healthcheck querying
  `/health` over HTTP.

Building the image on its own (without Compose):

```powershell
docker build -t valiant-ai-engine .
```

### TLS in production

The container serves **plain HTTP** by design — it does not terminate TLS itself. In a deployment,
put it behind something that does (Azure Container Apps / App Service ingress, Application Gateway,
or your own reverse proxy) and let that layer own the certificates.

The image starts uvicorn with `--proxy-headers --forwarded-allow-ips=*`, so the app honours the
`X-Forwarded-Proto` / `X-Forwarded-For` headers set by that proxy and generates correct `https://`
URLs in redirects and `request.url_for()`. The `*` trusts those headers from any peer, which is
correct when the container is only reachable through the ingress — narrow it to the proxy's CIDR
if you ever expose the container port to an untrusted network.

> **Outbound traffic is verified.** Calls to Azure OpenAI and Azure AI Search use normal
> certificate validation. If your network has a TLS-inspecting proxy with a private root CA, point
> `SSL_CERT_FILE` at that CA bundle (both `httpx` and `azure-core` honour it, so no code change is
> needed) rather than disabling verification.

## Disabling search in the RAG agent

The RAG agent has **one** search tool, and turning it on/off happens in a specific place in the
code. **There is no environment-variable-driven switch** — the tool is always registered, so a "clean"
shutdown requires editing the tool list.

| What you disable | Where | How |
|---|---|---|
| **The whole RAG** (a stub — skips the sub-agent and Azure AI Search) | [app/agents/rag/rag_tool.py:24](app/agents/rag/rag_tool.py#L24) — the `MOCK_RAG` constant | Set `MOCK_RAG = True` (the tool returns a canned, artificial response). From the CLI: the `--mock-rag` / `--no-mock-rag` flag ([app/main.py:89](app/main.py#L89)). |
| **Hybrid search** (Azure AI Search) — `get_information_from_rag_documents` | [app/agents/rag/agent.py](app/agents/rag/agent.py) — the entry in `RagAgent._get_tools()` | Comment out / remove the `get_information_from_rag_documents,` entry from the list returned by `_get_tools()`. |

The `RagAgent._get_tools()` method ([app/agents/rag/agent.py](app/agents/rag/agent.py))
returns the list of tools — it is the only place where they are registered in the graph. Removing or
commenting out an entry effectively takes that tool away from the agent.

> Leaving the `AZURE_SEARCH_*` variables empty does **not** disable the tool "gracefully" — it will
> still be registered and will return a runtime error when something tries to use it. To permanently
> disable a given search, edit `_get_tools()` (or `MOCK_RAG` for the whole RAG).

## Project structure / further reading

- [app/main.py](app/main.py) — entry point (server + the `chat` CLI subcommand).
- [app/api/config/settings/base.py](app/api/config/settings/base.py) — settings (environment
  variables, model deployments).
- [app/agents/rag/](app/agents/rag/) — the RAG sub-agent (`agent.py`, `rag_tool.py`, prompts).
- [app/chats/assistant/](app/chats/assistant/) — the main agent (`builder.py`, `parser.py`).
- [Dockerfile](Dockerfile), [compose.yaml](compose.yaml) — containerization.
