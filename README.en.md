# JARVIS

[Tiếng Việt](README.md) | **English**

**Just A Rather Very Intelligent System** — a Vietnamese-speaking voice AI assistant that runs locally on Windows.

**Version:** see the [`VERSION`](VERSION) file (single source of truth) · [Changelog](CHANGELOG.en.md) · **Original project:** [Ethan](https://ethanplus.ai)

> [!IMPORTANT]
> **This project is built by a Vietnamese developer, for Vietnamese speakers, and it is Vietnamese-only.** It is not bilingual and has no language switch. Prompts, speech recognition (`vi-VN`), TTS voices, string-matching keywords in code, tests and the UI text are all Vietnamese, so English input will often fail to match. **If you want to use it in English, fork it and convert the whole project**, not just `.env`: see [Forking for another language](#forking-for-another-language).
> Example commands below keep the original Vietnamese with an English gloss. The Vietnamese [README.md](README.md) is the complete reference and has far more UI detail than this page.

JARVIS uses a local language model to chat, handle requests and call tools on your machine. It ships a WebUI, Vietnamese voice, conversation memory and a flat, general-purpose tool system. The main memory data is stored locally.

## Contents

- [Features](#features)
- [Flat tool routing](#flat-tool-routing-2026-10-12)
- [Shortcuts and special tools](#shortcuts-and-special-tools)
- [Memory and self-learning](#memory-and-self-learning)
- [Interface and integrations](#interface-and-integrations)
- [Architecture](#architecture)
- [Install and configure](#install-and-configure)
- [Forking for another language](#forking-for-another-language)
- [API, testing and security](#api-testing-and-security)
- [Version and license](#version-and-license)

## Features

| System | What it does |
|---|---|
| **Local LLM** | Connects to llama.cpp through an OpenAI-compatible API; checks ports 8080 (LLM) and 8081 (embeddings) and keeps a "waiting for connection" state so errors do not spam the log when the server is not up. |
| **Vietnamese voice** | Browser speech recognition (`vi-VN`); replies are read aloud by Edge-TTS or VieNeu streaming through the stream_TTS server on port 8082. Only one TTS engine is on at a time. |
| **Flat tool routing** | An impersonal decision step (Gemma 4 picks the tool and fills its arguments, up to 3 rounds) followed by an in-character JARVIS reply; supports code shortcuts and automatic "working" lines. |
| **Attachments** | Detects the file type (PDF, text, Office, images…) and offers only the tools that can handle it (`file_tools_for`). |
| **RAG** | Local document search with embeddings, BM25 and rank fusion; streams the answer, filters junk characters and cites sources. |
| **Memory** | SQLite/FTS5 stores conversations, lessons, preferences and tool results. Memory Center in Settings manages the data. |
| **Workout tracking** | The Gym tool remembers the selected profile, normalises local time zones, understands natural commands, mirrors logs to an Obsidian wiki (`data/wiki/Gym/`, isolated from the AI vectors) and is managed in the Gym Memory tab of Memory Control. |
| **Self-learning and background jobs** | Reflective Learning, Evolution, the Dream Cycle and Self-Healing run in the background when the machine is idle; code edits need your approval. |
| **Input protection** | Filters untrusted instructions, checks Origin/IP for the API and WebSocket, and limits follow-up actions after reading outside content. |

## Flat tool routing (2026-10-12)

Each turn: code shortcuts (archives, `/tool_name`, `@tool_name`, `@rag`) → if none matches, the `engine/turn` loop:

- **Tool-choice round** (`prompt/jarvis.md` + `prompt/turn_tool.md` + the tool catalog): llama.cpp grammar forces JSON `{"tool","say","args"}`. When a tool is called, `say` is a short status line (🛠️ in front, streamed to the UI and TTS); code sends `status: working` while the tool runs and `thinking` while the model thinks, appends the result, and repeats up to 4 rounds.
- `tool = "none"` → **answer round** in plain text (`prompt/jarvis.md` + `prompt/turn_answer.md`, no JSON, no tool catalog), so long answers (a menu, a news summary) carry real content instead of promises.
- Tables from `display=True` tools are shown verbatim by code; the answer round only comments. Tools that already summarise themselves (vision `read_screen`/`read_webcam`/`read_image`, `rag_ask`) are also shown verbatim and not summarised twice.
- **Code gates** (`loop._NEEDS_WORD`): `read_screen` only runs when the sentence mentions the screen; `system_status` only for CPU/RAM/disk/process questions. A real request without those words must use `@read_screen` / `@system_status`.
- A reply stuck repeating one word or phrase (≥ 7 times) is cut and the connection closed so llama-server stops generating.
- Tool results fed to the answer round are capped at 8,000 characters (`search_news` splits the budget evenly per article). History keeps the latest turn at 3,000 characters and older turns at 300.
- Sentence by sentence, `loop._breaks_promise` drops lines that promise work no tool did in this turn, or promise to remind/follow up later, and replaces them with an honest sentence (the prompt only reduces fabrication; code blocks it).
- Each tool turn writes one `outcomes` row (tools, sentence, success/failed/partial, each step; `win_control` adds the cua actions). A successful turn whose arguments all came from your words is saved in `workflows` (`engine/turn/outcome.py`). The exact same sentence later (lower-cased, punctuation stripped) replays the saved tool chain and skips the tool-choice round.

Tool descriptions live in `prompt/tools/<name>.md`. To add a tool: an `@tool` function in `engine/tools/catalog/` plus its `.md` file. The `/` and `@` suggestions are generated from the registry (`engine.turn.entry.mention_list`: `@rag` plus every tool). Spec: `docs/superpowers/specs/2026-10-12-turn-rebuild-design.md` (internal).

### Attachments

The loop offers only the file tools that fit the extension: PDF/text/spreadsheet/Office → RAG (`rag_tool`) or OfficeCLI (`office_tool`); images (jpg, png, webp, bmp) → upscale (`upscale_image`) or analyse (`read_image`); zip archives are unpacked safely and the supported file inside is used. The list is configured with `@tool(file_extensions=[...])` in `engine/tools/catalog/`.

## Shortcuts and special tools

### Workout tracking (`@gym`)

Type `@gym` alone to see the active profile and the command table. Examples (the keywords are Vietnamese):

- Profiles: `@gym tạo hồ sơ <name>` ("create profile") / `@gym chọn hồ sơ <name>` ("select profile").
- Log a workout: `@gym vừa tập Bench Press 3 hiệp 10 reps 60kg` (volume and estimated 1RM are computed).
- Body weight: `@gym hôm nay cân nặng 72kg`.
- Exercise lookup (with YouTube technique links): `@gym tìm bài tập ngực`; stats/history: `@gym thống kê tiến độ`, `@gym lịch sử tập luyện`.
- Nutrition advice (WHO guidance) and habits: `@gym tư vấn dinh dưỡng tăng cơ`, `@gym hôm nay đã uống đủ 2 lít nước`.

### Knowledge store and documents (`@rag`)

`@rag` searches the local knowledge store and analyses documents (PDF, DOCX, TXT…). Type `@rag` alone to see the store status and the command table.

- `@rag <question>`: answers as a real-time stream with source citations.
- `@rag danh sách` ("list"): numbered documents and their chunk counts.
- `@rag lưu` ("save") with an attachment: copies the file to `data/wiki/Documents/`; the watcher indexes it automatically. Without an attachment, "lưu…" is treated as a question.
- `@rag xóa <number or file name>` ("delete"): removes it from the index **and** moves the original to `data/wiki/.trash/Documents/` (drag it back to restore).
- **Single source**: `data/wiki/Documents/` (change with `RAG_WATCH_FOLDER`) lives inside the Obsidian vault, so Obsidian can read the originals. The index (`data/rag_index/rag_vectors.tq` + `rag_metadata.json`) can be rebuilt from that folder. After changing the embedding model, delete both index files and `data/rag_watch.db` to re-ingest.
- Junk characters, null bytes and control characters are cleaned automatically when PDFs/text are ingested.
- **No `@rag` needed**: the `search_documents` tool lets the router search the store on its own when you ask about document contents, the store or rag. For an attachment, "summarise / what is it about" (or no question at all) makes `rag_ask` summarise the whole document instead of returning the 5 chunks that match the question. After ingesting, it returns a summary (topic, abstract, 3–6 key points; `engine/rag/summary.py`). Attaching a file without saying what to do adds **Save to the document store** (same path as `@rag lưu`) to the choice list.

## Memory and self-learning

- **Source of truth:** `data/jarvis.db` (SQLite + FTS5). The Obsidian vault in `data/wiki/` is a read-only mirror.
- **Memory Center:** manages memories, learnings, workflows, tool results and history. It is the main place to view and edit memory data.
- **Learning:** runs only when you teach it explicitly ("ghi nhớ" remember, "học đi" learn this, "từ giờ" from now on, "lần sau" next time…), correct a tool ("sai rồi… dùng X" wrong, use X) or retract something just learnt; ordinary chat and vague criticism are not learnt. The model (JSON grammar, think 128, `prompt/learning_propose.md`) writes at most 4 items, only from the latest turn: behaviour lessons (`lesson`), preferences/facts about you, general tool-choice rules (`tool_rule`, e.g. "food prices → search_products", stored in `corrections` and loaded into the tool descriptions of the tool-choice round) and one-off tool fixes (`tool_fix`). Code keeps the guardrails: the evidence must be your own words verbatim in the latest turn, and near-duplicates (cosine ≥ 0.90) are dropped.
- **Evolution:** pass 1: the model proposes removing/merging duplicate lessons, and code only does so when cosine ≥ 0.90; lessons mentioning things JARVIS dropped (agent, @control) are removed by code; contradicting lessons are not deleted. Pass 2 writes `STYLE.md` (≤ 12 rules, loaded into `<giong_dieu>` every turn) from the remaining lessons, newest first, so newer wins. `Evolution.md` only records removed/merged items (with their old text) so they can be restored; the active rules are in `STYLE.md`.
- **Tool corrections that stick:** when you correct a tool choice ("beef prices must use search_products"), a `corrections` row is stored (only if `outcomes` shows that exact sentence used the wrong tool in the last 24 hours). In the tool-choice round, similar sentences (cosine ≥ 0.85) become `<vi_du>` examples; after ≥ 2 corrections and similarity ≥ 0.95 a wrong choice is forced to the right tool (`engine/turn/corrections.py`). View/delete: `GET /api/corrections/list`, kind `correction` at `/api/memory-control/delete`.
- **Dream Cycle:** runs when idle to summarise and clean old data, with a backup before merging. The model answers in grammar-constrained JSON (`trivial` boolean, `bullets` ≤ 3); broken JSON is left for the next cycle.
- **Self-Healing:** classifies errors from the log with a grammar (enum CODE_BUG/TRANSIENT/CONFIG/DEPENDENCY/OTHER, think 128); code assembles the `Errors.md` entry (time, file, error) with the model's summary and next step; only CODE_BUG asks you to approve sending a fix to fix_self (Goose).
- **Multiple sessions:** WebUI and Telegram have separate sessions; history and routing state are kept apart per session.

## Interface and integrations

The frontend uses Vite, TypeScript and Three.js in `frontend/`: chat/HUD, a Command Bar, a media player and the Settings dashboard. The map feature (MapLibre panel, location pins, administrative boundaries) was removed entirely on 2026-10-13 (`tests/test_map_removed.py`). The webcam shows only as a small frame.

- Type `/` or `@` in the Command Bar to get tool and shortcut suggestions.
- Settings is a button on the control bar; the restart button is in the "Connections & API" tab.
- Chat bubbles render GFM Markdown with highlighted code blocks (language label and copy button) and scrollable responsive tables.
- Settings manages prompts, user, connections, MCP, memory, history and logs.
- `check_mail` (Gmail through the MCP server `@gongrzhe/server-gmail-autoauth-mcp`) is read-only: the latest 10 mails or one mail by ID. `MCPHub.call_tool` blocks every Gmail tool except `search_emails`/`read_email` in code (no sending, deleting or labelling) and caps `maxResults` at 10. The status line shows the name of the part in use (`registry.label`: "Gmail", "Thời tiết"…), never the raw command.
- On phones JARVIS is portrait-only: in landscape (touch screen, height ≤ 500px) the page is covered by "Rotate your phone to use JARVIS" and all effects stop, because iOS ignores the manifest `orientation` and Safari cannot lock it.
- Open the page with `?debug=1` to get the performance panel (`frontend/src/perf-debug.ts`): the `orb` row shows `webgpu`, `webgl2` or `off`, it measures main-thread lag, and it posts one sample per second to `POST /api/perf-log` (written to `logs/perf.jsonl`, one file per page load). The background orb uses three's `WebGPURenderer` and falls back to WebGL 2.
- Telegram can share the same backend (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_CHAT_IDS`); it detects network loss, pauses polling so the log is not spammed, and reconnects automatically.
- Skills, hooks and MCP extend the system. MCP servers are configured in `config/mcp_config.json` and managed in Settings.
- Many UI details (mascot bot, status orb, notification island, iPhone behaviour, keyboard and scroll handling) are documented, with their e2e tests, in the Vietnamese [README.md](README.md).

## Architecture

```text
WebUI / Telegram
       ↓ HTTP + WebSocket
FastAPI server → Router → Tools (Catalog)
       ↓                   ↓
SQLite + Memory Center     LLM / Embedding / Windows / Web
```

| Component | Location | Role |
|---|---|---|
| Server and API | `server.py`, `engine/server/` | FastAPI, WebSocket, settings, history and result delivery. |
| Conversation loop | `engine/turn/` | `/` `@` shortcuts, the constrained `{say, tool, args}` generation loop, tool execution, answer streaming. |
| Tools | `engine/tools/` | The flat tool system (`engine/tools/catalog/`) doing the specialised work. |
| Prompts | `prompt/`, `engine/prompts/` | Instruction text and the code that assembles context. |
| Frontend | `frontend/src/` | Chat, HUD, voice controls and Settings. |
| Data | `data/` | Database, documents, wiki, logs and user data. |

## Install and configure

### Requirements

- Windows 10/11 64-bit, Python 3.11+, Node.js and Chrome.
- A llama.cpp server with an OpenAI-compatible API: LLM on port `8080` by default, embeddings on `8081`.
- Redis on port `6379`.
- `yt-dlp` on PATH if you use YouTube search/playback.
- OpenSSL to create the local HTTPS certificate.

### Install and run

```powershell
git clone https://github.com/erikpuw/jarvis-windows.git
cd jarvis-windows
pip install -r requirements.txt
cd frontend; npm install; cd ..
openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem -days 365 -nodes -subj '/CN=localhost'
Copy-Item .env.example .env
```

Start llama.cpp and Redis first, then run the backend and the frontend in separate terminals:

```powershell
python server.py
```

```powershell
cd frontend
npm run dev
```

Open `https://localhost:8340`. If you use VieNeu streaming, also run `python run_vieneu.py` in its own terminal; otherwise use Edge-TTS.

### `.env` settings

| Variable | Purpose |
|---|---|
| `LOCAL_URL`, `LOCAL_API_KEY`, `LOCAL_MODEL` | Endpoint, key and name of the local LLM. |
| `LOCAL_EMBED_URL`, `LOCAL_EMBED_MODEL` | Embedding endpoint and model for RAG/semantic memory. |
| `EDGE_TTS_ENABLED`, `VIENEU_TTS_ENABLED` | Choose the Vietnamese TTS engine; enable only one. |
| `USER_NAME`, `HONORIFIC` | Name and form of address; editable in Settings. |
| `REDIS_URL` | Redis address. |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_CHAT_IDS` | Enable and restrict the Telegram bot. |
| `JARVIS_CORS_ORIGINS` | Browser origins allowed to connect. Never use `*`. |
| `RAG_WATCH_FOLDER` | Folder the watcher indexes automatically. |
| `MEMORY_PASSWORD` | Password for the Memory and Logs pages in Settings. **If empty, those pages stay locked.** |
| `DREAM_ENABLED` | Turn the Dream Cycle on/off. |

Defaults and additional variables are in `.env.example`. Never put secrets in the README or in a commit; `.env` is git-ignored.

Remote access through Tailscale: install Tailscale on the JARVIS machine and on the device, expose the frontend with `npm run dev -- --host`, then add the machine's Tailscale origin to `JARVIS_CORS_ORIGINS`. No router port needs to be opened.

## Forking for another language

Rough size of the Vietnamese content (lines containing Vietnamese text): `engine/` over 3,000, `frontend/src/` over 500, plus hundreds more across `prompt/`, `prompt/tools/` and `tests/`. The maintainer does not plan to support other languages, so treat this as a full port. Convert, in this order:

1. **Prompts**: `prompt/jarvis.md`, `prompt/turn_tool.md`, `prompt/turn_answer.md`, `prompt/voice_cues.md`, every tool description in `prompt/tools/*.md`, and the background prompts (`learning_*`, `evolution`, `dream_*`, `self_healing`). Add an explicit instruction at the top of `prompt/jarvis.md`, for example:
   ```
   The user's language is English. Always reply in English, even when tool results come back in Vietnamese.
   Address the user as "sir" and refer to yourself as "I". Keep sentences short and natural for speech.
   ```
2. **Keyword matching in code** (the part that silently breaks): `_NEEDS_WORD`, `_FUTURE`, `_ACT` and the replacement sentence `_NO_PROMISE` in `engine/turn/loop.py`; `_PREF_STYLE` and the weekday names in `engine/turn/prompt.py`; Vietnamese text in the tools under `engine/tools/catalog/` and `engine/tools/*.py`; wiki file names such as `Học hỏi.md` in `engine/core/learning.py`. `PROMPT_INJECTION_PATTERNS` in `engine/core/guardrails.py` already includes English.
3. **Voice**:
   - TTS: set `TTS_LOCAL_MODEL=en-US-GuyNeural` in `.env` (`edge-tts --list-voices` lists voices). Keep `EDGE_TTS_ENABLED=true` and `VIENEU_TTS_ENABLED=false`, because VieNeu reads Vietnamese only. For ElevenLabs, OpenAI TTS, Azure or Google, add an engine in `engine/server/` modelled on `tts_engine.py` and register it in `tts_manager.py` (reads `TTS_ENGINE`); it should return audio sentence by sentence so playback is continuous.
   - Speech input: the browser side uses `vi-VN` in `frontend/src/voice.ts`; `engine/server/whisper_server.py` hardcodes `language="vi"`. Change both.
4. **Data sources**: news, weather, gold/fuel prices, lunar calendar, CGV cinemas, Epic and shop sources are Vietnam-specific. Replace them or remove the matching tools (`engine/tools/catalog/` + `prompt/tools/<name>.md`).
5. **Frontend text** in `frontend/src/` and the Settings pages.
6. **Tests**: many tests and the `tests/golden/` snapshots contain Vietnamese phrases; update them with the prompts, then re-run the full suite.
7. **Measure again**: the prompts were tuned for small local models in Vietnamese. After translating, re-run the probes in `tests/live/` against your own llama-server.

**Using a large hosted model (Claude, Gemini, ChatGPT)**: change `LOCAL_URL`, `LOCAL_API_KEY`, `LOCAL_MODEL` in `.env` to the provider's OpenAI-compatible endpoint. If their API is not OpenAI-shaped, adjust or rewrite [`engine/server/llm_server.py`](engine/server/llm_server.py) (request format, parameters, streaming); the prompts may need re-tuning because they were tuned for small local models.

**After downloading**: `skills/officecli` only holds usage guidance; install officecli from its original source and take the `examples/` folder from there. The tools `legal_lookup` (Vietnamese law) and `vn_admin_lookup` (provinces, wards) are Vietnam-specific data. Keep them if you need them; otherwise delete the tools (`engine/tools/catalog/lookup.py`, `prompt/tools/<name>.md`) and `engine/tools/legal_engine.py`.

## API, testing and security

### API

- `GET /api/health` and `/api/health/detailed`: server/service status.
- `/api/settings/*`: configuration and connection tests used by Settings.
- `/api/memory-control/*`, `/api/learnings/*`, `/api/conversations/*`: memory and history (locked behind `MEMORY_PASSWORD`).
- `GET /api/outputs/{token}`: download a result file delivered to the session.
- `WS /ws/voice`: voice, text, audio and UI events.

Sensitive APIs require the right state/permission; see the routers in `engine/server/` and `engine/UIUX/` for the full endpoint list.

### Testing

```powershell
python -m pytest tests -q --ignore=tests/live --ignore-glob="tests/test_live_*"
# Diagnose RAM and check the HuggingFace model cache for VieNeu-TTS:
python scripts/check_vieneu_memory.py
python -m pytest tests/test_vieneu_health_and_memory.py -v
```

The frontend has Playwright scripts in `frontend/e2e/*.cjs`: run `npm run dev` on `:5173`, then `PW=<path to the playwright module> node frontend/e2e/<name>.cjs` (Playwright is not in `package.json`; install it yourself). CI (`.github/workflows/ci.yml`, on every push to `main` and every PR) runs `ruff check .`, compiles the Python, runs `python .github/scripts/check_imports.py` (every `from engine... import X` must point to a real name), runs `pytest` (with `requirements-ci.txt` and `bsdtar`) and `npm run build` for the frontend; run these before pushing. Some tests need a real machine (VieNeu, llama-server) and skip themselves on CI; if a test fails on your machine, check it before changing code. Learning/wiki data tests run in a temporary folder so your data is untouched.

### Security

- Data-changing REST calls and the WebSocket check `Origin`; IPs are restricted by the security settings.
- Web/tool results are marked as untrusted data and filtered for forged instructions before being passed on.
- After reading an outside source, the router blocks action chains that could control the machine.
- `MEMORY_PASSWORD` protects Memory Center and Logs; secrets live only in `.env`, which is git-ignored.

## Version and license

The version lives in [`VERSION`](VERSION) (single source of truth); older history is in [CHANGELOG.en.md](CHANGELOG.en.md). The Vietnamese [README.md](README.md) keeps the running "unreleased" notes in more detail.

This is an independent fan project, not affiliated with Marvel Entertainment or The Walt Disney Company. The JARVIS name and concept belong to their respective owners.
