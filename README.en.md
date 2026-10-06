# JARVIS

[Tiếng Việt](README.md) | **English**

**Just A Rather Very Intelligent System** — a Vietnamese-speaking voice AI assistant whose "brain" runs right on your Windows machine.

> *"Thưa ngài, tôi có thể giúp gì cho ngài?"* — *"How may I help you, sir?"*

**Version:** see the [`VERSION`](VERSION) file (single source of truth) · [Changelog](CHANGELOG.en.md)

![JARVIS home screen: an audio-reactive particle orb, a clock and a telemetry panel](assets/screenshots/hud-main.webp)

## 🎯 What Does JARVIS Do?

You speak or type in Vietnamese, and JARVIS understands and **does real work** on your machine:

- 🎙️ **Real-time voice conversation** in Vietnamese.
- 🖥️ **Machine control**: open/close apps, read the screen, use the webcam, create and edit Word/Excel/PowerPoint files.
- 🔎 **Lookups**: news, weather, gold prices and exchange rates, YouTube.
- 📄 **Question answering over your own documents** (RAG).
- 🧠 **Remembers and learns** from conversations, with a mirror in Obsidian you can read back.

**Where does it run?** The LLM, embeddings and memory run **on your machine** (llama.cpp, SQLite). Speech recognition (Chrome's Web Speech API), the default voice (Edge-TTS) and web lookups need internet.

**What do you need?** Windows 10/11, Python 3.11+, Node.js 18+, Chrome, a llama.cpp server (LLM and embeddings) and Redis. Details in [Installation and configuration](#-installation-and-configuration).

**Forms of address:** JARVIS calls itself "tôi" (I) and addresses the user as "ngài" (sir) — a hard rule in [`prompt/identity.md`](prompt/identity.md); edit that file and `prompt/user.md` to change it. This document says "you" for the reader.

> **Status:** a personal project under active development. Found a bug or have an idea? Open an [issue](https://github.com/erikpuw/jarvis-windows/issues) (templates included).
>
> JARVIS is built for Vietnamese: prompts, voice recognition (`vi-VN`), TTS voices and most command keywords are Vietnamese. Example commands below keep the original Vietnamese with an English gloss.

## 📑 Table of Contents

1. [What Does JARVIS Do?](#-what-does-jarvis-do)
2. [Key Features](#-key-features)
3. [How a Conversation Turn Works](#-how-a-conversation-turn-works)
4. [Prompts in One Place](#-prompts-in-one-place)
5. [Offers, "Yes" and Anti-Fabrication](#-offers-yes-and-anti-fabrication)
6. [27 Task Agents](#-27-task-agents)
7. [Self-Learning, Evolution, Dream, Self-Healing](#-self-learning-evolution-dream-self-healing)
8. [Memory, Memory Center and Obsidian Wiki](#️-memory-memory-center-and-obsidian-wiki)
9. [Frontend](#-frontend)
10. [Extending: Commands, Skills, Hooks, MCP, Telegram](#-extending-commands-skills-hooks-mcp-telegram)
11. [Core Tooling: Web Scraping and Windows Control](#-core-tooling-web-scraping-and-windows-control)
12. [Document Store (`@rag`)](#-document-store-rag)
13. [Job Search (`@jobs`)](#-job-search-jobs)
14. [System Architecture](#️-system-architecture)
15. [Installation and Configuration](#-installation-and-configuration)
16. [API](#-api)
17. [Directory Structure](#-directory-structure)
18. [Testing and Measurement](#-testing-and-measurement)
19. [Security](#-security)
20. [Changelog](#-changelog)
21. [License & Disclaimer](#-license--disclaimer)

---

## 🌟 Key Features

### 🧱 Core — conversation and machine control

| Feature | Description |
|---------|-------------|
| **Local LLM** | Gemma 4 E4B-it QAT (current profile), Qwen3.5-9B or Bonsai (chosen by a flag in `.env`), served by llama.cpp at `http://localhost:8080/v1`; handles both text and images |
| **Local embeddings** | `nomic-embed-text-v1.5-q8_0` at `http://localhost:8081/v1`, used for RAG and semantic memory |
| **Vietnamese voice** | Speech recognition via the Web Speech API (`vi-VN`) with recognition-error correction. Speech output via Edge-TTS (`vi-VN-NamMinhNeural`) or VieNeu streaming (port 8082); only one may be enabled |
| **Windows control** | The `win_control` agent uses cua-driver (UI Automation) to drive apps in the background without taking the mouse; asks before every machine-changing action. How to install cua-driver: see [details](#-core-tooling-web-scraping-and-windows-control) |
| **Web scraping** | Two-tier Scrapling: browser-imitating HTTP first, a headless browser as fallback for bot-protected or JavaScript-only pages. Used for news, product prices, jobs, weather |
| **Two-tier routing** | The gate only decides **chat or work**, without knowing which agents exist. The orchestrator picks agents via native tool calling and can chain several agents |
| **Controlled offers** | While you are just chatting, Jarvis offers actions it can take using `<ask_user>`/`<action_run>` tags. When you reply "yes" (`ừ`), code runs exactly the offered tool — the LLM does not guess again |
| **Centralised prompts** | All prompt text lives in `prompt/*.md`; the code that assembles prompts lives in `engine/prompts/` |
| **Anti-fabrication** | Every chat turn carries a `<tool_status>` directive stating that no tool ran this turn, so chat cannot claim it "checked" something or report system state |
| **Security** | Prompt-injection guardrails, IP firewall + Origin check (against CSRF / WebSocket hijacking) for REST and WebSocket, connection monitoring. Memory, chat history and logs are locked behind the `MEMORY_PASSWORD` password |

### 🧠 Memory and learning

| Feature | Description |
|---------|-------------|
| **HyperRAG** | Dense vectors + BM25 + Reciprocal Rank Fusion for local document retrieval. Watches the `data/documents/` folder |
| **Memory & Obsidian** | SQLite + FTS5 (`data/jarvis.db`) is the source of truth. The Obsidian vault (`data/wiki/`) is a one-way mirror. The Memory Center in the WebUI is the only place to edit |
| **Self-reflective learning** | Each learning pass has a proposal step and a critique step, then code enforces hard checks. The latest lesson can be undone precisely (`retract`). Successful workflows are replayed when a command matches verbatim |
| **Dream Cycle** | Runs during idle night hours to summarise and clean up conversations, agent results and old wiki pages. Always backs up before merging |
| **Self-Healing** | Scans logs every 60 seconds, classifies errors and writes them to `Errors.md`. Only asks Goose to fix code after you approve |

### 🇻🇳 Extras (optional)

Each extra is its own agent in `engine/agents/` (full list in [27 task agents](#-27-task-agents)):

- **Vietnam daily life**: weather, news, gold/fuel prices and exchange rates, lunar calendar, zodiac, CGV showtimes, Epic free games, maps and directions.
- **Entertainment**: music, YouTube, livestreams.
- **Work**: Outlook email and calendar, notes, `@jobs` job search and cover-letter drafting (sends only after you approve).

---

## 🔀 How a Conversation Turn Works

`engine/router/decide.py` checks the steps below in order and stops at the first match:

| # | Step | When | Result |
|---|------|------|--------|
| 0 | Explicit command | `/command …` (Command Bar), `@commands/<tool>.md …` or "Dùng lệnh `<tool>` …" ("Use command `<tool>`") | Runs the agent that owns that tool directly, bypassing the gate and classifier |
| 1 | `@plans` | Message starts with `@plans <goal>`, e.g. `@plans hôm nay không biết ăn gì` ("no idea what to eat today") | Goal mode ([engine/plans](engine/plans)): plan lookups → call read-only agents (search/web/history) → re-plan if needed → one conclusion. Chat **never** offers this mode on its own |
| 2 | `@jobs` | Message starts with `@jobs`, or an interview / letter approval is in progress | Job search ([engine/jobs](engine/jobs)), see "Job search (`@jobs`)" |
| 3 | `@rag` | Message starts with `@rag` | Long-term document store ([engine/rag](engine/rag)), see "Document store (`@rag`)". Runs before `@mention`, so `@rag` no longer falls into the file-only RAG agent |
| 4 | `@mention` | Message starts with `@desktop`, `@mail`… (names and aliases come from `skills/agents/*/skill.md`) | Calls that agent directly |
| 5 | Reply to an offer | Jarvis asked with `<ask_user>` last turn, and you now answer "ừ" (yes), "đồng ý" (agree), "không" (no)… | Code runs exactly the tool in `<action_run>`, bypassing the LLM |
| 6 | Voice control | Volume, shutdown commands… | `win_control` agent |
| 7 | Routing complaint | "sai rồi, tôi chỉ hỏi thôi" ("wrong, I was only asking") | Removes the workflow that just ran by mistake and records a `routing_correction` |
| 8 | Workflow replay | Message **matches verbatim** a command that previously succeeded | Runs the stored tool chain directly |
| 9 | Gate (LLM, `temperature 0`) | Everything else | `general`, `general_knowledge`, `orchestrator`, or `attachment_clarify` when a file is attached. Per-label guidance lives in `skills/router/*/SKILL.md` |

- **orchestrator**: the classifier picks agents. For commands embedded in chat, the classifier may shorten the sentence (e.g. "…bạn mở giúp tôi được không?" → "mở Notepad", i.e. "…could you open it for me?" → "open Notepad"), but only if the shortened sentence **only removes words** and adds none. After an agent finishes, `next_tasks` decides whether to call another agent. Multiple results are merged into one answer by the `synthesizer`.
- **plan** (`@plans`): at most 3 rounds × 3 steps (5 in total), 60 seconds per step; the model only chooses targets and writes lookup queries (schema-validated JSON) and never holds tools; a round with no successful step stops the run. Web lookups go through the `web_research` tool (Google News RSS, then reads 3 articles), and each page is checked for injected instructions. Preferences in `Preferences.md` are only visible to the conclusion step and are never sent out in lookup queries.
- **general / general_knowledge**: the chat branch assembles 5 message blocks (see next section). If an agent declines, the turn also falls back to chat with a "could not be done" directive.
- **Attachments**: the picker only offers agents that can read the format (`attachment_agents_for`, built from `rag_tool` + `image_engine` + Office extensions): pdf/txt/md/csv/json/html → RAG; docx/xlsx/pptx → RAG or OfficeCLI; jpg/png/webp/bmp → Upscayl. Other formats: Jarvis says it "can't handle this yet". If a file is attached but the classifier chose an agent that doesn't use files → it asks again with the picker (except for `@mention`).
- **Archives** (`.zip .rar .7z .tar .gz .tgz .bz2 .xz .zst`, [engine/router/archive.py](engine/router/archive.py)): handled **before the gate** with Windows' built-in `bsdtar` (no extra libraries). **Exactly 1** usable file inside → extract only that file and treat it as if sent directly; **several files** → stop, list the names and ask for them one at a time; **none** → say so clearly. Blocked: > 200 entries, files > 200 MB, `..`/absolute paths, nested archives; 60-second timeout.

---

## 🧩 Prompts in One Place

To change a prompt, edit the `.md` file — never write prompt text in code.

| Group | Files in `prompt/` | Code (`engine/prompts/`) |
|-------|--------------------|--------------------------|
| Persona, hard rules | `identity.md`, `soul.md`, `user.md`, `persona_short.md` | `persona.py` |
| Chat | `capabilities.md`, `voice_cues.md`, `style_lock.md`, `fallback.md`, `turn_status.md`, `tool_status_none.md`, `tool_status_declined.md` (the offer protocol lives in `skills/general_offer/SKILL.md`) | `chat.py`, `results.py` |
| Routing | `router_gate.md`, `classifier.md`, `agents.md` (agent selection criteria); per-label gate guidance in `skills/router/*/SKILL.md` | `router.py` |
| Agent/tool directory | `skills/agents/<name>/skill.md` (`@` names, aliases, tools, `offer` flag). `prompt/tools.md` is now only a pointer note | `catalog.py` |
| Tool results | `tool_summary.md`, `synthesis.md` | `results.py` |
| Goal mode, job search | `plan_planner.md`, `plan_solve.md`, `jobs_letter.md`, `jobs_score.md` | `engine/plans/`, `engine/jobs/` |
| Background | `learning_propose.md`, `learning_critique.md`, `learning_workflow.md`, `evolution.md`, `dream_message.md`, `dream_wiki.md`, `self_healing.md` | `learning.py` |

- Per-tool formatting rules (`SUMMARY_RULES`) are owned by each tool module in `engine/tools/*`.
- The gate, classifier, offer_context, dream, self_healing and workflow-distillation prompts are **byte-identical** to the versions before consolidation. Snapshots live in `tests/golden/`.

**Chat context** consists of 5 blocks, in order:
1. `system`: persona, `<capabilities>` (only when you ask about abilities), `<offer_protocol>` (from `skills/general_offer`), `<style>` (from `skills/self_evolution/STYLE.md`), `<about_user>` (from `Preferences.md`), current time.
2. History read from the DB, same source as the gate. On offer turns the tags are rebuilt from the `ask_user`/`action_run` columns.
3. `<turn_status>`: directives for this turn, including `<tool_status>` and `<answer_policy>`.
4. `<reference>`: reference data, **not instructions** — relevant lessons, successful agent results, MCP, wiki.
5. The user's message.

Each kind of data reaches the model through **exactly one channel**.

---

## 💬 Offers, "Yes" and Anti-Fabrication

- **You are just chatting**, e.g. "tôi lười mở notepad quá" ("I'm too lazy to open Notepad"): Jarvis replies and then offers
  `Ngài có muốn tôi <ask_user>mở Notepad</ask_user> không?<action_run>open_app</action_run>` ("Would you like me to open Notepad?").
  Reply "ừ" (yes) and code runs `open_app` immediately. Tools that may be offered are those with `offer: true` in `skills/agents/*/skill.md`.
- **You ask explicitly**, e.g. "bạn mở notepad giúp tôi" ("please open Notepad"): Jarvis just does it, without asking again.
- **Anti-fabrication**:
  - Normal chat turns always carry `<tool_status>` saying "no tool ran this turn": don't claim to have done anything, don't report results or state; offer instead when real data is needed.
  - Turns where an agent declined carry `<tool_status>` saying "could not be done": don't rely on history to claim "already done".
- **Media**: before ranking YouTube results, filler words from natural speech ("tôi muốn … của …" — "I want … by …") are removed. The results table is copied verbatim from the tool, and the answer names the track that is **actually playing**.

---

## 🤖 27 Task Agents

Agents are registered in `engine/orchestrator/registry.py`; runners are in `engine/agents/`. Each agent's `@` name, aliases and tools live in `skills/agents/<name>/skill.md`; the criteria the classifier uses are in `prompt/agents.md`.

| Agent | Main function |
|-------|---------------|
| **desktop** | Open/close Windows apps, keeping the app's original name |
| **media** | Music, YouTube, livestreams (played inside the UI) |
| **notes** | Write, view, delete notes |
| **vision** | Capture and analyse the screen with a vision LLM |
| **webcam** | Capture and analyse a webcam frame |
| **office** | Create/edit attached Word, Excel, PowerPoint files (`officecli` skill) |
| **rag** | Read, summarise and answer questions over attached files or indexed documents |
| **security** | Check network security, ports, firewall |
| **system** | CPU, RAM, disks, running processes, machine health |
| **email** | Last 10 emails and the next 7 days of appointments in Outlook |
| **history** | Review conversation history |
| **image** | Upscale images with Upscayl |
| **project** | Inspect a code project, scan for syntax errors |
| **goose** | Open the Goose UI for you to drive yourself |
| **win_control** | Control background Windows apps via cua-driver (open apps, click, type), change window state |
| **dream** | Run a Dream cycle immediately |

**Lookup group**: each tool is its own agent, all running through `engine/agents/agent_search.py`, so the classifier picks the exact tool in a single LLM call.

| Agent | Tool | Function |
|-------|------|----------|
| **weather** | `weather_search` | Weather, temperature, forecast for a place |
| **news** | `search_news` | News from domestic newspapers |
| **market** | `get_market_data` | Gold, exchange rates, fuel, gas, electricity and water prices today |
| **shop** | `search_products` | Product prices, reviews, comparison |
| **route** | `map_route` | Directions |
| **places** | `map_pois` | Find places and venues nearby |
| **cinema** | `get_cgv_movies` | Now showing and upcoming films at CGV |
| **games** | `get_epic_free_games` | Free games on the Epic Games Store |
| **lunar** | `get_vannien_data` | Today's lunar calendar |
| **zodiac** | `get_zodiac_data` | Daily horoscope for the 12 zodiac signs |
| **web** | `web_research` | Web lookups for `@plans`. Reachable only through goal mode; the classifier never sees it |

### ➕ Adding a new agent

Chat, the WebUI (`@` suggestions), Telegram `/agents` and the classifier all **read** the agent list from the files below — no prompt or chat code changes needed. Just complete every step:

| # | File | What to do |
|---|------|------------|
| 1 | `engine/agents/agent_<name>.py` | Write the agent: a `run_<name>_agent` function (a new lookup agent can reuse `run_search_agent`) |
| 2 | `engine/orchestrator/registry.py` | Add `"<name>": {"module": ..., "runner": ...}` to `AGENT_REGISTRY`. An agent that runs a single tool also gets `"tool": "<tool_name>"` |
| 3 | `skills/agents/<name>/skill.md` | YAML frontmatter: `name`, `title`, `aliases` (the `@` names), `description`, `tools` (each with `name`, `label`, `offer`). `offer: true` means chat may offer that tool. Chat will automatically see **"Agent <Name>"** |
| 4 | `prompt/agents.md` | Add `- <name>: <when to pick this agent>`. This is the tool description the classifier sees |
| 5 | `commands/<tool>.md` | Each of the agent's tools needs a command file |
| 6 | Tests | Update `EXPECTED_AGENT_CRITERIA` in `tests/test_prompts_catalog.py` (and the `offer` tool list if you added any), then re-snapshot the classifier golden with the command below |
| 7 | Re-run | `python -m pytest tests -q --ignore=tests/live --ignore-glob="tests/test_live_*"`, then **restart JARVIS** (the agent directory is read once and cached in memory) |

```bash
python -c "import json; from engine.orchestrator.classifier import _build_tools; open('tests/golden/classifier_tools.json','w',encoding='utf-8').write(json.dumps(_build_tools(), ensure_ascii=False, indent=1))"
```

If a step is missing, `tests/test_prompts_catalog.py` fails. It requires the agent sets in `skills/agents/`, `agents.md` and `AGENT_REGISTRY` to be identical, and every tool to have a command file owned by the right agent — so an agent can never run without chat and the classifier knowing about it.

---

## 🧬 Self-Learning, Evolution, Dream, Self-Healing

All of these run in the background when the system is idle and never slow down a conversation turn. If you keep chatting, the running background task yields and retries later.

### 📖 Self-reflective learning ([learning.py](engine/core/learning.py))

1. **Propose** (`learning_propose.md`): the model reads the last 3–5 turns from the DB and successful agent results, then proposes at most 2 items. Each item has a `kind`: `user_fact`, `preference`, `behaviour_lesson` or `routing_note`.
2. **Critique** (`learning_critique.md`): the model compares each proposal with the closest existing item and decides `skip`, `merge`, `replace` or `new`.
3. **Code gatekeeping**:
   - Evidence must match the conversation verbatim; for `user_fact`/`preference` it must come from your own words.
   - Transient states ("lazy", "tired") are not learned.
   - Behaviour rules may not talk about asking, permissions, tools, agents or tags.
   - `merge`/`replace` may only touch the exact existing item shown to the model.
4. **Retracting a lesson**: if you deny exactly what was just learned, the next learning pass proposes `retract`. Code can only undo items written by the previous pass: new items are deleted, merged items are restored to their old content.
5. **Workflows**: successful tool chains are stored in `validated_workflows` and replayed when a command matches verbatim (case-insensitive). By design there is no fuzzy matching and no diacritic stripping, since stripping diacritics collides words such as `bật`/`bắt` (turn on / catch) and `tắt`/`tát` (turn off / slap).
6. `routing_note` is only written as a **proposal** to `data/wiki/System/Evolution.md` for human review. It is never applied automatically.

### 🧬 Evolution ([evolution.py](engine/core/evolution.py))
- Only writes **tone** rules (forms of address, emoji, length, humour) to `skills/self_evolution/STYLE.md`. New rules may not touch the persona, `<soul_rules>` or `<offer_protocol>`.
- Every update bumps the version and appends a short changelog entry to `Evolution.md`.

### 💤 Dream Cycle ([dream.py](engine/core/dream.py))
- **When**: within the quiet window (default 02:00–05:00), every 24 hours, when the system is idle. Can be triggered manually with `@dream`, natural language, or `POST /api/dream/run`.
- **What**: summarises old conversations (older than 14 days), prunes `agent_outcomes`, merges monthly journals, compacts `topics/*.md`, rotates `Errors.md` and `Evolution.md`.
- **Safety**: always backs up to `data/dream_archive/` or `data/wiki/.trash/dream/` before merging. If the LLM fails to respond, Dream leaves the original data untouched and retries next cycle.

### 🛡️ Self-Healing ([self_healing.py](engine/core/self_healing.py))
- Scans logs every 60 seconds when idle. The LLM classifies errors (`CODE_BUG`, `TRANSIENT`, `CONFIG`, `DEPENDENCY`, `OTHER`) and writes an entry to `data/wiki/System/Errors.md`.
- For code bugs, Jarvis **asks for your approval** in the WebUI session before asking Goose CLI to fix exactly one file. No session to approve in → no fix.

---

## 🗂️ Memory, Memory Center and Obsidian Wiki

- **Source of truth**: `data/jarvis.db` (SQLite + FTS5), with tables `messages` (including `ask_user`/`action_run` columns), `memories`, `learnings`, `agent_outcomes`, `validated_workflows`.
- **Memory Center** (WebUI, `/api/memory-control/*`, `/api/learnings/*`…) is the **only place to edit**. Every write path, including automatic learning and cleanup scripts, goes through the same Memory Center functions.
- **Obsidian vault** `data/wiki/` is a **one-way** mirror of the DB:
  - `System/Preferences.md`, `System/Learning.md`, `System/Workflows/*.md`;
  - `System/Evolution.md`, `System/Errors.md`, `System/Dream.md`;
  - daily journals `daily/MM-YYYY/YYYY-MM-DD.md`.

  Jarvis never reads data back from Obsidian.
- **Dual lookup**: `history_engine.py` and `wiki_retrieval.py` search SQLite FTS5 and the Markdown files in parallel.
- **Notes** (`note_engine.py`): Markdown with YAML frontmatter, openable and editable in Obsidian.

---

## 🎨 Frontend

Built with **Vite + TypeScript + Three.js**, Dark-Tech Glassmorphism style.

<p align="center"><img src="assets/screenshots/mobile.webp" alt="JARVIS on a phone: the 8/8 step tracker and the reply" width="260"></p>

*On a phone: the step tracker shows each step (guardrail, routing, LLM, TTS) before the reply.*

![Graphfy: a module map generated from code](assets/screenshots/graphfy.webp)

*Graphfy in Settings: a module map generated from the code; purple edges are LLM call sites.*

![Graphfy on hover: only one module's edges are kept](assets/screenshots/graphfy-focus.webp)

*Hover a block to keep only the edges that touch it.*

Source in `frontend/src/`:

| File | Role |
|------|------|
| `main.ts` | State machine, Command Bar (Ctrl+K; `/` suggests commands from `commands/`, `@` suggests agents), interactive cards, media player, MapLibre map |
| `orb.ts` | Audio-reactive Three.js particle orb |
| `bot.ts`, `bot-mouth.ts` | Mascot (`bot-avatars` library) above the send button with its own behaviour per state: looks around, sleeps, nods when it hears you, opens its mouth when talking, three dots while thinking |
| `status-orb.ts`, `status-label.ts` | Small dotted orb (`thinking-orbs`) and the status text, both following the JARVIS state |
| `clock.ts`, `edge-aura.ts`, `metal-ring.ts`, `stream-loader.ts` | Flip clock above the orb, glowing edge around the Command Bar, liquid-metal ring around the send button (WebGL2), loader shown before the first text of a reply |
| `anim-gate.ts` | One switch that stops every decorative animation loop when something covers the screen (Settings, map, media) or the tab is hidden, so PCs and phones do not heat up |
| `voice.ts` | Web Speech API, microphone, audio playback, instant TTS interruption |
| `ws.ts` | WebSocket client with auto-reconnect |
| `icons.ts` | Morphing icons (morphicons + lucide) for buttons, flow steps, tracker; `runAction` for buttons with spinner → ✓/✗ |
| `perf-debug.ts` | Performance panel, loaded only with `?debug=1` (see below) |
| `settings/` | Full-screen settings dashboard (see below) |
| `style.css` | Main styling |

**Performance debugging**: open `https://localhost:8340/?debug=1` (or `:5173`). Once a second the panel prints frames per second, `requestAnimationFrame` calls per loop, long tasks, DOM size, running CSS animations, the `anim-gate` state and the JS heap; the data is also on `window.__perf`. Use it together with Edge DevTools when the machine runs hot or stutters.

**Settings dashboard** (`frontend/src/settings/`): opens full-screen and pauses the orb; 16-page sidebar that becomes a drawer on mobile.

| File | Role |
|------|------|
| `index.ts` | Shell: open/close, sidebar, page switching, first-run setup, data loading, save/test buttons |
| `pages.ts` | Page HTML: Overview (hardware and service telemetry), Connections & API, Voice, User, System, Memory, Logs, Agents, Hooks, Skills, Prompts (editable and savable), Commands, Plugins, MCP Connect, Graphfy, About (README) |
| `memory.ts` | Memory Center: view, edit, delete with relationship checks, multi-select delete |
| `logs.ts` | Logs page: chat history (everything or by session), `jarvis.log`, security log, TTS log. Rendered with `textContent`, so stored content cannot inject HTML |
| `lock.ts` | Password screen shared by Memory and Logs. The token lives only in a JS variable, never in storage |
| `graphfy.ts` | Structure map **generated from code** via `GET /api/graphfy` (`engine/UIUX/graphfy.py` scans imports with `ast`): one block per `engine/` package, with `core/` and `server/` split per file; purple edges = LLM call sites; the LLM block is drawn as a **circuit brain** (half brain · half circuit with running pulses, 90% width), with edges from below plugging into its signal pins. Lanes: Input · Turn processing · LLM (centre axis) · Response / Memory · Document ingestion · Background · Support (dimmed) · Other. New modules appear in "Other" until assigned in `LANES`. Light pulses animate flow on every edge; hover filters a block's edges and shows its files; drag and drop, layout saved as `jarvis.graphfy.positions.v4` |
| `api.ts`, `types.ts`, `styles.css` | API calls (20s timeout, shows the backend's actual error), types, styling |

Memory, chat history and logs are locked on the backend (`engine/UIUX/memory_lock.py`): set `MEMORY_PASSWORD` in `.env`, otherwise these pages stay **fully locked**. Heavy lists (agents, hooks, skills, prompts, commands, plugins) come from `/api/settings/catalog` when the relevant page opens, not from `/api/settings/status` (which is polled every 5 seconds).

---

## 🔌 Extending: Commands, Skills, Hooks, MCP, Telegram

- **32 Markdown commands** in `commands/` (`open_app`, `check_mail`, `search_media`, `rag_tool`, `win_control`, `dream`…), hot-reloaded.
- **Skills** in `skills/`: `officecli` (OfficeCLI usage guide), `self_evolution` (`STYLE.md` tone rules). The other three folders are prompt data: `agents/` (agent directory), `router/` (gate label guidance), `general_offer/` (offer protocol).
- **Hooks & plugins**: events `on_startup`, `on_shutdown`, `ON_MESSAGE_RECEIVE`, `ON_RESPONSE_GENERATE`; dynamic loading of `.py`/`.ts` plugins.
- **Self-installing extensions** (`install_extension`): hot-load new plugins/skills/hooks from a URL or code, no restart needed.
- **MCP** (`config/mcp_config.json`): `wikipedia-mcp` (enabled); `gitnexus`, `headroom`, `codebase-memory-mcp` (configured, disabled by default). Scrapling and cua-driver are **not** MCP servers: JARVIS calls them directly, see [Core tooling](#-core-tooling-web-scraping-and-windows-control).
- **Command Bar**: `/command_name <args>` runs a command from `commands/` (type `/command_name` with no args and JARVIS asks for each argument); `@agent message` calls an agent directly (router step 1). The Commands and Agents pages in Settings document this exact syntax.
- **Telegram bot**: remote control with Chat ID authentication. The `/agents` command reads the directory from `skills/agents/`.

---

## 🔧 Core Tooling: Web Scraping and Windows Control

JARVIS calls these two **directly from code**: they do not go through the MCP hub and are not listed in `config/mcp_config.json`.

### Web scraping (Scrapling)

Source: [`engine/tools/browser.py`](engine/tools/browser.py). Uses Scrapling instead of plain Playwright, in two tiers:

| Tier | How it runs | When |
|------|-------------|------|
| `AsyncFetcher` | Plain HTTP request imitating a browser's TLS fingerprint and headers; no browser | Default: fast and light |
| `StealthyFetcher` | Headless browser (Patchright), aimed at bot-protected pages such as Cloudflare | Fallback when tier 1 is blocked, or the page needs JavaScript to show its content (e.g. product listings) |

- `StealthyFetcher` prefers an already-installed Edge/Chrome over the bundled "Chrome for Testing" build (which may fail to launch on some Windows machines).
- Used by: news (Google News RSS, DuckDuckGo), product prices on approved retail sites (`shop_engine`), `@plans` lookups (`web_research`), job posts (`@jobs`), weather.
- Tool results are filtered for suspected prompt-injection lines before they reach prompts (`scrub_untrusted`, see [Security](#-security)).

### Windows control (cua-driver)

The `win_control` agent ([`engine/tools/windows_control.py`](engine/tools/windows_control.py)) drives Windows apps in the background, without taking over the mouse or keyboard, using [cua-driver](https://github.com/trycua/cua). cua-driver reads the UI tree through UI Automation (UIA); JARVIS acts by `element_index`, never by screen coordinates.

**Install cua-driver** (PowerShell, once):

```powershell
irm https://cua.ai/driver/install.ps1 | iex
```

JARVIS looks for `cua-driver.exe` in this order: the `CUA_DRIVER_PATH` variable → `PATH` → `%LOCALAPPDATA%\Programs\Cua\cua-driver\bin`. If it is not installed, `win_control` reports "cua-driver not found".

- **How it is called**: for each command JARVIS starts one `cua-driver mcp` process (talking over stdio, ~0.2 s startup, no daemon or Docker) and closes it afterwards. This is a direct connection from code, **not** an MCP server in `config/mcp_config.json`.
- **How it runs**: the active LLM picks each step as JSON, text only (no vision needed). At most `CUA_MAX_STEPS` steps per command (default 12).
- **Safety**: by default (`CUA_CONFIRM=each`) it asks for confirmation before every action that changes the machine; buttons labelled Delete/Uninstall/Xóa… always ask, even with `off`. Only tools that target an element by `element_index` and a specific process are allowed: no x/y coordinate clicks, no typing into the whole screen.
- **What cua-driver cannot see**: the taskbar and the Start/Search menu go through `pywinauto` (UIA). Maximise/minimise/restore also use `pywinauto`, reading the state back to verify.
- Opening/closing apps by name belongs to the `desktop` agent (PowerShell + Start Menu), separate from `win_control`.

---

## 📚 Document Store (`@rag`)

Documents saved to the store are retrieved with explicit commands. The router matches the `@rag` prefix with a regex, not the LLM, so it never confuses it with chat or other commands. Sub-commands are Vietnamese keywords:

- `@rag <question>` — search the store (dense + BM25 + RRF + rerank), drop chunks with `hybrid_score` < `RAG_MIN_SCORE` (default `0.2`); the LLM answers only from evidence, with sources (file name, page). If a file is attached: ask about that file.
- `@rag lưu` ("save") + an attached file — save it to the long-term store. Without a file, "lưu…" is treated as a question.
- `@rag danh sách` ("list") — documents in the store and their IDs.
- `@rag xóa <id>` ("delete") — remove from the store. Accepts exactly one ID; `xóa` followed by several words is treated as a question.
- `@rag` — help.

Files dropped into `data/documents/` (or `RAG_WATCH_FOLDER`) are also indexed into the same store by the watcher. Changing the embedding model requires re-indexing: vectors from two models are not comparable, and a different dimension is rejected.

## 💼 Job Search (`@jobs`)

JARVIS interviews you to build a profile + a Vietnamese PDF CV, searches every morning (after 08:00) for job posts **that accept CVs by email**, drafts cover letters, and only sends them via Gmail once you approve.

Gmail setup (once): enable 2-Step Verification, create an "App password" at `myaccount.google.com/apppasswords`, then add it to `.env` yourself:

    GMAIL_ADDRESS=you@gmail.com
    GMAIL_APP_PASSWORD=xxxxxxxxxxxxxxxx

Commands (UI or Telegram; keywords are Vietnamese):
- `@jobs phỏng vấn` (interview) / `@jobs tiếp tục` (continue) / `@jobs sửa hồ sơ` (edit profile)
- `@jobs tìm` (search) — search now; `@jobs tin <text or link>` (post) — evaluate one post
- Review: `gửi 1, 3` (send), `bỏ 2` (skip), `sửa thư 1: <request>` (edit letter) (the list expires after 3 days, max 10 letters/day)
- `@jobs trạng thái` (status)

Data lives in `data/jobs/` (profile, CV, pending list, sent log). It never applies on sites that require login (TopCV, vLance, LinkedIn); it doesn't write English CVs; posts requiring more English than the profile states are skipped.

---

## 🏗️ System Architecture

```
                     Chrome / Web Client (https://localhost:8340)
┌──────────────────────────────────────────────────────────────────────────┐
│ voice.ts (STT/TTS) · orb.ts (Three.js) · main.ts (Cards, Media, Map)       │
│ bot.ts · status-orb.ts (status) · settings/ (Dashboard, Memory)          │
└───────────────────────────────┬──────────────────────────────────────────┘
                                │ WebSocket /ws/voice
                                ▼
┌──────────────────────── server.py (FastAPI) ─────────────────────────────┐
│ WebSocket · UIEngine REST · Security Firewall · Self-Healing watcher     │
└───────────────────────────────┬──────────────────────────────────────────┘
                                ▼
┌──────────── engine/router ────────────┐   ┌──── engine/prompts ──────────┐
│ decide: command → @plans/@jobs/@rag → │◄──│ prompt/*.md → persona, chat, │
│ @mention → "ừ" → voice → complaint →  │   │ router, results, learning,   │
│ replay → gate                         │   │ catalog                      │
└──────┬─────────────────────┬──────────┘   └──────────────────────────────┘
       │ orchestrator        │ general
       ▼                     ▼
┌──── engine/orchestrator ───┐  ┌── chat (5 blocks) ┐
│ classifier → agents →      │  │ system · history  │
│ next_tasks → synthesizer   │  │ turn_status ·     │
└──────┬─────────────────────┘  │ reference · user  │
       ▼                        └───────────────────┘
┌── engine/agents (27) ──┐  ┌── engine/tools ───────────────┐  ┌── engine/core ─────────────┐
│ desktop, search, media │─►│ desktop automation, scrapling,│  │ memory, learning, evolution│
│ office, rag, ...       │  │ media, office, weather, ...   │  │ dream, self_healing, RAG   │
└────────────────────────┘  └───────────────────────────────┘  └────────────────────────────┘
                                ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ llama.cpp :8080 (Gemma 4 / Qwen3.5) · llama.cpp :8081 (embeddings)       │
│ Stream TTS :8082 (VieNeu) · Edge-TTS · Redis :6379                       │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 🚀 Installation and Configuration

### Requirements
- Windows 10/11 64-bit, Python 3.11+, Node.js 18+, Google Chrome.
- llama.cpp server: LLM on `:8080`, embeddings on `:8081`.
- Redis on port 6379 (native Windows or WSL).
- `yt-dlp` on PATH (for YouTube search).
- Set `MEMORY_PASSWORD` in `.env` if you want to open Memory, Chat history and Logs in Settings.
- Optional: [cua-driver](https://github.com/trycua/cua) for the `win_control` agent. Install in PowerShell: `irm https://cua.ai/driver/install.ps1 | iex` (see [details](#-core-tooling-web-scraping-and-windows-control)).

### Notes after downloading

- **Some features were removed** from the public version: legal document lookup, Vietlott analysis, administrative-unit lookup (provinces, wards). Each lookup tool is its own agent (27 agents registered).
- **officecli**: `skills/officecli` only holds usage guidance. Install officecli from its original source and take the `examples/` folder (Word/Excel/PowerPoint samples) from there instead of the copy in this repo.
- **Goose**: the `goose` agent only opens the Goose GUI and, once you approve, asks the Goose CLI to edit one file. It needs the Goose CLI and Goose for Windows. If you do not use it, ignore it, or swap in another tool you prefer (remove the agent from `engine/orchestrator/registry.py`, `skills/agents/goose/` and the related `commands/`).
- **Using a large model (Claude, Gemini, ChatGPT)**: change `LOCAL_URL`, `LOCAL_API_KEY`, `LOCAL_MODEL` in `.env` to the provider's OpenAI-compatible endpoint. If their API is not OpenAI-shaped, adjust or rewrite [`engine/server/llm_server.py`](engine/server/llm_server.py) (request format, parameters, streaming). The prompts in `prompt/` are tuned for small local models; larger models may need re-tuning.
- **Tests may fail on your machine**: some depend on external services (llama.cpp, Redis, `bsdtar`, network). After downloading, run `python -m pytest tests -q --ignore=tests/live --ignore-glob="tests/test_live_*"` and check failing tests before changing code.

- **The project is written purely for Vietnamese**: prompts, voice, speech recognition and data sources all assume Vietnamese. For another language see [Changing language and voice](#changing-language-and-voice) right below.

#### Changing language and voice

1. **Voice output (TTS)**. Default is Edge TTS (`vi-VN-NamMinhNeural`).
   - Switch language in `.env`: `TTS_LOCAL_MODEL=en-US-GuyNeural` (voice list: `edge-tts --list-voices`). Keep `EDGE_TTS_ENABLED=true` and `VIENEU_TTS_ENABLED=false`, because VieNeu reads Vietnamese only.
   - For a stronger service (ElevenLabs, OpenAI TTS, Azure, Google...): add an engine in `engine/server/` modelled on `tts_engine.py` and register it in `tts_manager.py` (reads `TTS_ENGINE`). The service should return audio sentence by sentence so `voice_streamer.py` can play it continuously.
2. **Speech recognition (STT)**: `engine/server/whisper_server.py` hardcodes `language="vi"`. Change it (e.g. `"en"`) or drop the argument so Whisper auto-detects.
3. **Prompts**: all prompts live in `prompt/*.md`. Start with `identity.md`, `soul.md`, `user.md`, `style_lock.md`, `voice_cues.md`, `persona_short.md`. They currently require Vietnamese replies and the "tôi - ngài" form of address. Add an explicit instruction for the model at the top of `identity.md`, for example:
   ```
   The user's language is English. Always reply in English, even when tool results come back in Vietnamese.
   Address the user as "sir" and refer to yourself as "I". Keep sentences short and natural for speech.
   ```
   After editing, rerun the tests: many compare prompts against the samples in `tests/golden/`, so update those files to match.
4. **Vietnamese data and keywords**: news, weather, gold/fuel prices, lunar calendar, agent-selection keywords (`engine/agents/`) and command names in `commands/` are Vietnamese/Vietnam-specific. When changing language, review these or disable commands you do not use.

### Steps

```bash
git clone https://github.com/erikpuw/jarvis-windows.git
cd jarvis-windows
pip install -r requirements.txt
cd frontend && npm install && cd ..

# SSL certificate for HTTPS/WSS
openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem -days 365 -nodes -subj '/CN=localhost'

# Create .env from the template and fill it in (see the table below). If you forget, the server copies the template on startup.
cp .env.example .env           # PowerShell: Copy-Item .env.example .env
# Start llama.cpp (8080, 8081) and Redis (6379)

python server.py               # backend; also starts Stream TTS :8082 when using VieNeu (or run it alone: python run_vieneu.py)
cd frontend && npm run dev     # frontend, in a separate terminal
# Open Chrome: https://localhost:8340
```

### `.env` configuration

The full list with comments is in [`.env.example`](.env.example). The most important variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `LOCAL_URL` | `http://localhost:8080/v1` | llama.cpp LLM endpoint |
| `LOCAL_API_KEY` | `sk-no-key-required` | API key for the local LLM |
| `LOCAL_MODEL` / `VISION_MODEL` | name of the running model | Text / vision model |
| `LOCAL_EMBED_URL` | `http://localhost:8081/v1` | Embeddings endpoint |
| `LOCAL_EMBED_MODEL` | `nomic-embed-text-v1.5-q8_0` | Embeddings model |
| `EDGE_TTS_ENABLED` / `VIENEU_TTS_ENABLED` | `true` / `false` | Pick the TTS engine; both may not be enabled |
| `TTS_LOCAL_MODEL` | `vi-VN-NamMinhNeural` | Edge-TTS voice |
| `USER_NAME` / `HONORIFIC` | (empty) | Only stored and shown by the Settings page. How JARVIS addresses you in conversation ("tôi" – "ngài", i.e. "I" – "sir") lives in `prompt/identity.md` and `prompt/user.md`, not in these two variables |
| `MEMORY_PASSWORD` | (empty) | Password for Memory, Chat history and Logs in Settings. **Empty means those pages are fully locked.** No API sets or changes it; edit `.env` only |
| `STREAM_TTS_HOST` / `STREAM_TTS_PORT` | `127.0.0.1` / `8082` | Stream TTS address when run alone with `run_vieneu.py` |
| `REDIS_URL` | `redis://localhost:6379` | Redis |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_ALLOWED_CHAT_IDS` | optional | Telegram bot |
| `JARVIS_CORS_ORIGINS` | `localhost:5173`, `localhost:8340` | Comma-separated browser origins allowed to call the API/WebSocket. `*` is ignored. Pages served from the same host as the server (`https://<ip>:8340`) are always allowed |
| `RAG_WATCH_FOLDER` | `data/documents` | Folder watched by RAG |
| `DREAM_ENABLED` | `true` | Enable/disable Dream |
| `DREAM_RETENTION_DAYS` | `14` | Days data is kept as-is before Dream merges it |
| `DREAM_OUTCOME_RETENTION_DAYS` | `= DREAM_RETENTION_DAYS` | Days successful `agent_outcomes` are kept (failures are kept twice as long) |
| `DREAM_QUIET_HOUR_START` / `_END` | `2` / `5` | Window in which Dream may run automatically |
| `DREAM_INTERVAL_HOURS` | `24` | Minimum gap between two Dream runs |

**Chat-branch sampling** (Gemma, `engine/server/llm_server.py`): `temperature 0.4 / top_p 0.8 / top_k 40`, measured and kept as-is. The gate and classifier always use `temperature 0`.

### 📱 Remote access via Tailscale
1. Install Tailscale on the JARVIS machine and on your phone, signed in to **the same account**.
2. On the host: run `npm run dev -- --host` in `frontend/`, and set `JARVIS_CORS_ORIGINS=http://<PC-Tailscale-IP>:5173` in `.env` (don't use `*`: it is ignored, and the WebSocket rejects origins not on the list).
3. On the phone: open Safari or Chrome and go to `http://<PC-Tailscale-IP>:5173`.

No router port forwarding needed, and your IP is not exposed.

---

## 🌐 API

**WebSocket**: `/ws/voice` carries voice, streamed text and audio, interactive cards, `media_open`, map pins.

| Group | Endpoints |
|-------|-----------|
| Health | `GET /api/health`, `/api/health/detailed`, `/api/usage` |
| Memory lock | `GET /api/memory-lock/status`, `POST /api/memory-lock/unlock` (returns a token; send it back in the `X-Memory-Token` header) |
| Settings | `/api/settings/status`, `/api/settings/catalog`, `/api/settings/keys` (accepts only `LOCAL_API_KEY`, `TTS_LOCAL_KEY`, `LOCAL_URL`, `TTS_LOCAL_MODEL`, `USER_NAME`, `HONORIFIC`), `/api/settings/preferences`, `/api/settings/test-llm`, `/api/settings/test-tts`, `/api/settings/reset-tokens`, `POST /api/prompts/save`, `/api/system/readme`, `POST /api/restart` |
| TTS/STT | `/api/tts/voices`, `/api/tts/voice`, `/api/tts/voices/clone`, `/api/tts-test`, `/api/stt` |
| Memory Center 🔒 | `/api/memory-control/{summary,dependencies,update,delete}`, `/api/learnings/*`, `/api/notes/*`, `/api/workflows/*`, `/api/evolution/*`, `/api/outcomes/list` |
| Conversations and logs 🔒 | `/api/history`, `/api/logs`, `/api/logs/security`, `/api/logs/tts`, `/api/conversations`, `/api/conversations/sessions`, `/api/conversations/session/{id}`, `/api/conversations/update`, `/api/conversations/delete` |
| Media | `/api/media/search`, `/api/media/resolve`, `/api/media/local/{path}` |
| RAG & files | `/api/rag/status`, `DELETE /api/rag/document`, `/api/upload` |
| MCP | `/api/mcp/servers`, `POST /api/mcp/servers/{name}/enabled` (live status from the hub; secret values in `args` are redacted) |
| Other | `GET /api/graphfy`, `/api/command-bar/skills`, `/api/command-bar/context`, `/api/feedback`, `/api/feedback/stats`, `POST /api/dream/run`, `/api/agents/goose/launch` |

🔒 = needs the token from `/api/memory-lock/unlock`, otherwise it returns `401 locked`.

---

## 📂 Directory Structure

```
jarvis/
├── server.py              # FastAPI + WebSocket
├── prompt/                # TEXT of every prompt (*.md), including agents.md (agent selection criteria)
├── commands/              # 32 hot-reloaded Markdown commands
├── skills/                # agents/ (agent directory), router/, general_offer/, officecli, self_evolution (STYLE.md)
├── hooks/, plugins/       # lifecycle hooks and dynamically loaded plugins
├── run_vieneu.py          # run the VieNeu Stream TTS alone (keeps the model in RAM/VRAM)
├── config/                # mcp_config.json
├── scripts/               # bench_llama.py; cleanup_learning_2026_09.py (dry-run by default, --apply to clean)
├── data/                  # jarvis.db, wiki/ (Obsidian), documents/, backups/, dream_archive/
├── docs/superpowers/      # specs/, plans/, reports/ (internal, not in the repo)
├── engine/
│   ├── router/            # decide, gate, replay, ask_user, fast_paths, dispatch, chat
│   ├── orchestrator/      # classifier, dispatcher, synthesizer, registry
│   ├── prompts/           # prompt assembly: persona, chat, router, results, learning, catalog
│   ├── agents/            # runners of the 27 agents (lookup agents share agent_search.py)
│   ├── tools/             # executable tools (media_search, desktop_automation, ...)
│   ├── core/              # memory, learning, evolution, dream, self_healing, RAG, guardrails
│   ├── server/            # llm_server, tts_manager, stream_tts, telegram_bot
│   ├── plans/             # goal mode @plans
│   ├── jobs/              # job search @jobs
│   ├── rag/               # document store @rag
│   ├── security/          # firewall, connection monitor
│   ├── UIUX/              # REST router, interactive cards
│   ├── main/              # FlowTracker, FlowAgents, user confirmation
│   └── chunking/          # AST chunker (Tree-sitter)
├── frontend/src/          # main.ts, orb.ts, bot.ts, status-orb.ts, voice.ts, ws.ts, icons.ts, style.css, ...
│   └── settings/          # settings dashboard: index, pages, memory, logs, lock, graphfy, api, styles
├── frontend/e2e/          # Playwright scripts (*.cjs)
└── tests/                 # unit tests, golden/, live/probes/
```

---

## 🧪 Testing and Measurement

```bash
python -m pytest tests -q --ignore=tests/live --ignore-glob="tests/test_live_*"
```

- **Golden** (`tests/test_prompts_wired.py`): the gate, classifier, offer_context, dream, self_healing and workflow prompts must be byte-identical to `tests/golden/`. The test also checks that no prompt text remains in code and that modules import cleanly in any order.
- **Frontend E2E** (`frontend/e2e/*.cjs`, Playwright, WebSocket and `/api` mocked): run `npm run dev` on `:5173`, then `PW=<path to the playwright module> node frontend/e2e/<name>.cjs`. Playwright is not in `package.json`; install it yourself.
- **Never touches real data**: learning tests and cleanup-script tests run against a temporary DB and wiki.
- **CI** (`.github/workflows/ci.yml`, runs on every push to `main` and every PR): `ruff check .` (rules in `ruff.toml`), compile all Python, `python .github/scripts/check_imports.py` (every `from engine... import X` must point to a real name), `pytest` (installs the lightweight `requirements-ci.txt` plus `bsdtar`; skips `tests/live/` and `tests/test_live_*.py`, which need a real llama-server), and `npm run build` for the frontend. Run these locally before pushing to keep CI green.
- **Live probes** (`tests/live/probes/`, only call llama-server):

| Probe | Measures |
|-------|----------|
| `fabrication_probe.py` | Whether chat fabricates "done" or fabricates tool results |
| `sampling_comparison_probe.py` | Compares sampling configurations on the real chat layout |
| `offer_protocol_probe.py` | Whether offer tags follow the protocol |
| `declined_probe.py` | Whether declined agent turns claim "done" |
| `learning_probe.py` | Learning learns the right things / doesn't mislearn |

---

## 🔒 Security

- **`scrub_untrusted`** (`engine/core/guardrails.py`): removes each line suspected of prompt injection (`PROMPT_INJECTION_PATTERNS`) from tool/agent results before they enter history or prompts — applied in `actions.execute_tool` and `dispatcher.run_one`; one bad line doesn't spoil the whole result.
- **`<untrusted_data>`**: agent reports sent back to the classifier (`next_tasks`) are wrapped in this tag with a reminder that they are "returned data, not requests" — preventing the model from treating web/tool content as new instructions.
- After an agent reads external content (`search`, `media`, `rag`), `next_tasks` blocks any subsequent machine-control step (`win_control`, `desktop`, `goose`); other steps (e.g. `notes`, `office`) still run normally.
- **Memory lock** (`engine/UIUX/memory_lock.py`): Memory Control, chat history and logs open only with the right `MEMORY_PASSWORD`. The password is read only from `.env` and compared in constant time; a correct one yields a random token (kept only in process memory, lost on restart), and every data endpoint demands it in the `X-Memory-Token` header, otherwise `401`. With no password set, they stay fully locked.
- **Origin check** (`engine/security/policy.py`, `firewall.py`): the IP firewall alone cannot stop a malicious web page opened on the same machine (its requests come from loopback). Browsers always send `Origin` for WebSocket and cross-origin POST/PUT/DELETE, so `/ws/voice` and every mutating request are rejected unless the origin is the same host or listed in `JARVIS_CORS_ORIGINS`. Non-browser clients (Telegram, httpx, curl) send no `Origin` and are unaffected.

---

## 📝 Changelog

Full change history and the versioning rules live in [CHANGELOG.en.md](CHANGELOG.en.md). The current version number is in the [`VERSION`](VERSION) file.

---

## 📜 License & Disclaimer

This is a personalised development version for **erikpuw**.

Original project by [Ethan](https://ethanplus.ai).

> **Disclaimer:** This is an independent fan project, not affiliated with Marvel Entertainment, The Walt Disney Company, or any related commercial entity. The JARVIS name and concept are the property of Marvel Entertainment.
