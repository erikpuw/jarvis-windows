# JARVIS

<div align="center">

**Just A Rather Very Intelligent System**  
*A versatile, local-first Vietnamese voice AI assistant with multi-user security and autonomous cognitive evolution.*

**Version:** [v10.0.1](VERSION) · **Original Project:** [Ethan](https://ethanplus.ai)

[Tiếng Việt](README.md) · **English**

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688.svg)](https://fastapi.tiangolo.com/)
[![Frontend](https://img.shields.io/badge/Frontend-Vite%20%7C%20Three.js-646CFF.svg)](https://vitejs.dev/)
[![Tests](https://img.shields.io/badge/Tests-1060%2B%20Passed-brightgreen.svg)]()
[![Platform](https://img.shields.io/badge/Platform-Windows-0078D6.svg)]()
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

</div>

---

## 📌 Overview

**JARVIS** is an offline-capable, local-first AI assistant designed for Windows, communicating with large language models (LLMs) via `llama.cpp` using an OpenAI-compatible API. JARVIS eliminates reliance on third-party cloud services for personal data: conversation history, knowledge documents, fitness logs, and self-learning preferences are securely stored locally within SQLite and an Obsidian Vault.

The system is built on a **Flat Tool Routing** architecture, enhanced with a specialized **Jev Fast-Path (0.8B)** decision model for zero-latency general conversation, alongside strict **Multi-User Role-Based Access Control (RBAC)** isolating Admin and Member workspaces.

---

## ✨ Key Features

### 1. Flat Tool Routing & Jev Fast-Path
- **Non-Personified Decision Loop (Grammar JSON)**: Enforces strict structured JSON outputs `{"tool", "say", "args"}` via `llama.cpp` grammars, eliminating hallucination during tool invocation.
- **Jev Fast-Path Chat Bypass**: Specialized decision model `Jev-Style-0.8B-Decision-v3` (GGUF) running on port 8083 or in-process. For everyday conversational dialogue (greetings, chitchat, encyclopedic questions), Jev skips the primary LLM's tool-selection round, cutting ~3.5s of latency for instant replies.
- **Flexible Shortcuts**: Rapid execution with `/tool_name`, `@tool_name`, or automated attached-file routing.

### 2. Multi-User RBAC & Perimeter Security
- **Role Isolation (Admin vs. Member)**: Persistent user accounts stored in SQLite `users` table.
- **MCP Gmail Protection**: Access to Admin email via MCP is strictly gated across all layers (MCP Hub, Tool Registry, Tool Schema, Slash Commands, and REST APIs). Member accounts are completely blocked from viewing or dispatching Admin emails.
- **System Prompt Gate**: The core system prompt (`prompt/jarvis.md`) is restricted to Admin; Member requests receive a 403 Forbidden.
- **Multi-User Telegram Bot**: Secure account linking via `/link <token>` or pre-configured `telegram_chat_id`. Automatically routes permissions, blocks unauthorized chats, and isolates message history and learnings per user.

### 3. Isolated Self-Learning & Cognitive Evolution
- **Selective Reflection (Learning Engine)**: Absorbs lessons only upon explicit user instruction ("remember this", "from now on", "next time use..."). Casual chitchat is ignored.
- **Dynamic Tone Adaptation (Evolution Engine)**: Synthesizes and merges communication rules into `STYLE.md`.
- **Per-User Data Isolation**: Member lessons, preferences, and evolution files are stored independently in `data/users/{user_id}/` (`Learning.md`, `Preferences.md`, `STYLE.md`, `Evolution.md`), preventing any override of Admin wiki data.

### 4. Local Knowledge Base & RAG (`@rag`)
- **Hybrid Semantic Retrieval (Dense + FTS5)**: Powered by `EmbeddingGemma 2` (768d) embeddings combined with SQLite FTS5 lexical search.
- **Obsidian Vault Sync**: Continuously monitors `data/wiki/Documents/`, auto-indexing Markdown notes, PDFs, DOCX, and TXT files as they are saved.
- **Real-time Streaming**: Streams synthesized answers with source citations while automatically filtering garbage characters.

### 5. Local Fitness & Nutrition Tracking (`@gym`)
- Isolated user profiles for personalized fitness management.
- Logs exercises, sets, reps, and weights, automatically calculating session volume and estimated 1RM.
- Daily bodyweight tracking, hydration reminders, and WHO-aligned nutrition coaching.
- Auto-syncs training logs directly into the Obsidian Wiki (`data/wiki/Gym/`).

### 6. Retail & Pharmacy Price Comparison
- **Supermarket Price Engine**: Real-time cross-store product comparison across Bách Hóa Xanh, Co.op Online, WinMart, LOTTE Mart, and Emart.
- **Tech Gadget Search**: Cleans search queries and filters accessories for electronics from CellphoneS, FPT Shop, and Thế Giới Di Động.
- **Pharmacy Intelligence (`search_medicine`)**: Real-time extraction across major pharmacy chains (Long Châu, An Khang, Pharmacity) with item classification, price ranges, and medical safety notices.

### 7. Clean News Reader & Daily Utilities
- **Distraction-Free Reader Card**: Extracts clean article content via Trafilatura, stripping ads and bloated navigation into a lightweight modal.
- **Weather & Lunar Calendar**: Real-time multi-source weather (Báo Mới, Open-Meteo, wttr.in), hourly rain forecasts, and Vietnamese lunar/zodiac calendar lookups.
- **Windows System Controls & Vision**: Screen inspection (`read_screen`), image understanding (`read_image`), and safe desktop automation.

---

## 🏗️ System Architecture

```text
┌────────────────────────────────────────────────────────┐
│                    Client Interfaces                   │
│   Web HUD (Three.js/Vite)  ·  Telegram Bot  ·  Mobile  │
└──────────────────────────┬─────────────────────────────┘
                           │ HTTP / WebSocket
┌──────────────────────────▼─────────────────────────────┐
│                 FastAPI Server & Gateway               │
│  - Authentication & RBAC (Admin vs Member)             │
│  - Session Management & WebSocket Voice/Text Stream    │
└──────────────┬──────────────────────────┬──────────────┘
               │                          │
┌──────────────▼─────────────┐ ┌──────────▼──────────────┐
│       Jev Fast-Path        │ │    Turn Execution Loop  │
│  (Instant Chat Bypass)     │ │  - Round 1: Tool Choice │
└────────────────────────────┘ │  - Round 2: Answer Gen  │
                               └──────────┬──────────────┘
                                          │
       ┌──────────────────────────────────┴──────────────────────────────────┐
       │                                                                     │
┌──────▼─────────────────────┐ ┌──────────────────────────┐ ┌────────────────▼───────────────┐
│       Tool Catalog         │ │    Memory & Evolution    │ │      Local AI Model Services    │
│ - RAG (@rag, Documents)    │ │ - SQLite / FTS5          │ │ - LLM / llama.cpp (:8080)       │
│ - Gym Tracker (@gym)       │ │ - Obsidian Wiki Vault    │ │ - Embedding Server (:8081)      │
│ - Retail / Pharmacy Search │ │ - Learning & STYLE.md    │ │ - Jev Fast-Path Engine (:8083)  │
│ - Windows Vision / Control │ │ - Isolated data/users/   │ │ - Voice TTS (Edge / VieNeu)     │
│ - MCP Hub (Gmail...)       │ │ - Dream Cycle / Self-Heal│ │                                 │
└────────────────────────────┘ └──────────────────────────┘ └─────────────────────────────────┘
```

---

## 🚀 Installation & Configuration

### Requirements

- Windows 10/11 64-bit, Python 3.11+, Node.js, and Chrome.
- llama.cpp server compatible with OpenAI API: LLM default at port `8080`, embedding at `8081`.
- `yt-dlp` in system PATH (for media playback/search).
- OpenSSL to generate local HTTPS certificates.

### Install & Run

```powershell
git clone https://github.com/erikpuw/jarvis-windows.git
cd jarvis-windows
pip install -r requirements.txt
cd frontend; npm install; cd ..
openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem -days 365 -nodes -subj '/CN=localhost'
```

Launch llama.cpp first, then run backend and frontend in separate terminals:

```powershell
python server.py --ssl
```

```powershell
cd frontend
npm run dev
```

Open `https://localhost:8340`. If using VieNeu streaming, run `python run_vieneu.py` in a separate terminal; otherwise, Edge-TTS is used by default.

To run the dedicated Jev Fast-Path decision engine:
```powershell
python run_jev.py --cpu
```

### Configuration (`.env`)

Copy template and configure:

```powershell
copy .env.example .env
```

Frequently used variables:

| Variable | Description |
|---|---|
| `LOCAL_URL`, `LOCAL_API_KEY`, `LOCAL_MODEL` | Local LLM endpoint, API key, and model name. |
| `LOCAL_EMBED_URL`, `LOCAL_EMBED_MODEL` | Embedding endpoint and model for RAG and learning. |
| `EDGE_TTS_ENABLED`, `VIENEU_TTS_ENABLED` | Select Vietnamese voice engine (only enable one at a time). |
| `USER_NAME`, `HONORIFIC` | Name and honorific; configurable in Settings. |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_CHAT_IDS` | Enable and restrict Telegram bot access. |
| `JARVIS_CORS_ORIGINS` | Allowed browser origins. Do not use `*`. |
| `RAG_WATCH_FOLDER` | Folder watched for automatic indexing (default `data/documents`). |
| `MEMORY_PASSWORD` | Protects Memory Control and Logs pages in Settings. |
| `DREAM_ENABLED` | Enable/disable Dream Cycle. |

Default values and extra options reside in `.env.example`; never commit secret keys.

Remote access via Tailscale: install Tailscale on both host and client, expose frontend to network with `npm run dev -- --host`, then add host Tailscale origin to `JARVIS_CORS_ORIGINS`. No port forwarding required.

---

## 🧪 Testing & Quality Assurance

JARVIS features comprehensive automated test coverage with over **1,060 unit and integration tests**:

```powershell
# Execute the complete backend test suite
python -m pytest tests/ -q

# Verify Frontend TypeScript integrity
npx tsc --noEmit -p frontend/tsconfig.json

# Test VieNeu-TTS health and VRAM allocation (if enabled)
python -m pytest tests/test_vieneu_health_and_memory.py -v
```

---

## 🔒 Acknowledgments, License & Disclaimer

- **Original Project**: Built upon, extended, and deeply customized from **[Ethan](https://ethanplus.ai)**.
- **License**: Distributed under the [MIT License](LICENSE).
- This is an independent open-source enthusiast project and is not affiliated with, endorsed by, or connected to Marvel Entertainment, The Walt Disney Company, or any of their subsidiaries. The name JARVIS is used solely for creative and technological inspiration.
