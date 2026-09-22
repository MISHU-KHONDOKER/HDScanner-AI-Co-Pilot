# HDScanner AI Co-Pilot — Agent Engineering Reference

A production-distilled reference for building an **LLM agent with tool-calling**.
This repository contains the reusable, provider-agnostic core of a support agent
that was built to guide users through hardware troubleshooting — with the
domain-specific parts (vendor knowledge, hardware protocol, screenshots)
removed so the engineering patterns stand on their own.

> **What this is:** a clean, runnable skeleton demonstrating how to build a
> safe, stateful, tool-using agent on any OpenAI-compatible API.
>
> **What this is not:** the full scanner integration. That lives in a private
> repository because it reverse-engineers a proprietary hardware control
> interface and embeds vendor documentation.

---

## What it demonstrates

| Capability | Why it matters |
|---|---|
| **Multi-turn tool-calling loop** | The model requests an action; *your* code runs it, feeds the result back, and repeats until a real answer — not a demo, a real agent loop. |
| **Per-session isolation + SQLite persistence** | Every conversation has its own ID and survives restarts. Fixes the classic "one global list for the whole server" defect. |
| **Crash-safe conversation handling** | A failed turn rolls back to a clean snapshot instead of corrupting history; dangling tool calls self-heal on the next request. |
| **Leaked tool-call recovery** | Some models emit tool calls as plain-text markup instead of the structured field — this parses and re-runs them so a leak becomes a real action, never visible junk. |
| **Safety-first design** | Tools only run when the model explicitly calls them; a tool error can never crash the chat; nothing is invented. |

---

## Architecture

```
Browser (index.html)
   │  fetch /api/start, /api/chat, /api/session/{id}
   ▼
FastAPI (app/main.py)
   │  session lookup → SQLite (copilot.db)
   │  tool loop → OpenAI-compatible API (DeepSeek by default)
   ▼
run_tool()  ← your domain actions plug in here
```

- `app/main.py` — the agent: tool loop, session storage, crash recovery.
- `app/static/index.html` — a minimal chat front-end.
- `knowledge/system_prompt.md` — placeholder system prompt (swap in your own).
- `.env.example` — configuration template (copy to `.env`).

---

## Running it

### 1. Set up a virtual environment

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

### 2. Install dependencies

```powershell
pip install -r requirements.txt
```

### 3. Configure your API key

```powershell
Copy-Item .env.example .env
# edit .env and set DEEPSEEK_API_KEY (or point DEEPSEEK_BASE_URL at another provider)
```

### 4. Start the server

```powershell
uvicorn app.main:app --reload --port 8000
```

### 5. Open the app

Browse to **http://127.0.0.1:8000/** and try:

- *"What's the current time?"* — exercises the `current_time` tool.
- *"Add 12 and 30"* — exercises the `add_numbers` tool.

---

## Adapting it to your own domain

The tool loop is domain-agnostic. To build your own agent:

1. **Define your tools** — replace the `TOOLS` list in `app/main.py` with your
   own function schemas (actions, read-only queries, anything).
2. **Implement `run_tool()`** — dispatch each tool name to your integration.
   Keep the "never raise, always return a safe dict" contract.
3. **Replace the knowledge base** — swap `knowledge/system_prompt.md` for your
   domain instructions, or move to retrieval (RAG) once the content outgrows
   "stuff everything into the prompt".

---

## Design notes (things I learned the hard way)

- **`uvicorn --reload` only watches `.py` files.** Editing knowledge/content
  files needs a manual restart.
- **Conversation memory belongs on the server, not the browser.** A refresh
  should never start a new conversation; only an explicit "new conversation"
  should.
- **A tool call must always get a tool response**, even on error — otherwise
  the API rejects the whole next request with `tool_calls must be followed by
  tool messages`.
- **Snapshot before you mutate shared state.** If a turn fails mid-loop, roll
  back rather than leave a dangling assistant message behind.

---

## License

MIT — see [LICENSE](LICENSE).
