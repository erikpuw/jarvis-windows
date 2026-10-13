# Changelog

[Tiếng Việt](CHANGELOG.md) | **English** · [← Back to README](README.en.md)

**Numbering** `MAJOR.MINOR.PATCH`:
- The version number lives in exactly one place: the [`VERSION`](VERSION) file. `/api/health` and the dashboard (Vite) read it; the README only links to it.
- For each release: bump `VERSION` (the only place to edit), add a new entry to the log below, then tag `vX.Y.Z` in git.
- Which number to bump:
  - `PATCH`: bug fixes, no change in designed behaviour.
  - `MINOR`: new features, or prompt/flow changes that don't break existing data.
  - `MAJOR`: architecture changes, or data/DB changes that require migration.

## v9.9.6 — 2026-09-27

**Settings becomes a full-screen dashboard.** Spec and plan written by Claude, implemented by another model (plus 9 extra pages beyond the plan, on request), then reviewed and fixed by Claude.

| Issue found in review | Impact | Fix |
|---|---|---|
| `/api/settings/status` returned raw MCP `args` | Leaked the context7 API key to every client | Return only name/command/status; secret values in `args` redacted (`_redact_args`) |
| Status bundled README, prompts, commands… (≈93KB) into every poll | Settings slow, prone to timeouts | Moved to `/api/settings/catalog`, fetched when a page opens |
| `mcp_servers` changed from dict to list | HUD showed "0,1,2" with error dots | Return `{name: status}` from the real hub again |
| `/api/mcp/servers` used `_json` without importing it | MCP page broken | Fixed; status taken from the hub instead of the `enabled` flag |
| UI sent `SERVER_API_KEY`, `FISH_AUDIO_API_KEY` | Backend rejected them, showing "connection error" | Switched to `LOCAL_API_KEY`, `TTS_LOCAL_KEY` |
| Moving into `settings/` dropped the `jarvis:overlay` event | Orb didn't pause | Event emitted again |
| Voice page hard-coded 4 Google voices and saved to the wrong API | Saved fake voices | Load `/api/tts/voices`, save via `/api/tts/voice`, wire up the clone button |
| CSS forced `display:flex` on the Memory grid, ALL-CAPS text, text < 12px | Broken layout, mismatched fonts | Grid fixed, one font family, 12px minimum; 42 dead rules removed |
| Command bar suggested `/help`, `/clear`, skills, `/plugin` | Every one returned "command not found" | Only suggest commands the backend can run |
| Collapsing the Settings sidebar: labels `display:none` + icons re-centred instantly | Text/icons jumped while the width shrank | Icons keep their position, labels fade (`opacity`), no wrapping |
| Dashboard read the version number from `.env` | Out of sync with `VERSION` | Vite reads the `VERSION` file |

**Mascot on the send button** (`frontend/src/mascot.ts`) — a pure TypeScript port of [nilbuild/page-mascot](https://github.com/nilbuild/page-mascot) (MIT), no React needed (the `page-mascot` npm package is unused and can be removed).
- **Position:** sits still right above `#cmd-send`, its body overlapping the command bar's top edge (sunk 20px) so it looks perched on the bar; the status line stays on the left. 56px (44px on mobile).
- **Hit area:** only the head receives clicks; clicks pass through the body so the send button still works.
- **Interaction:** the head follows the mouse (8 directions) and blinks occasionally; click to change expression (heart, sparkle, happy), 4 quick clicks = dizzy.
- **Follows JARVIS state** via the `jarvis:mascot` event (emitted in `transition()` and `showError()`): thinking looks up, working sparkles, speaking is happy, error/restart is dizzy, idle for 60 seconds falls asleep.
- **Characters:** sprites `frontend/public/mascots/<name>-directions.webp` and `<name>-reactions.webp` (3×3 grid, transparent background); switch characters with the `name` parameter of `mountMascot` in `main.ts`.
- **Static files:** `mount_frontend_dist` (`engine/UIUX/ui_engine.py`) serves `/` and every folder in `frontend/dist` (`assets/`, `mascots/`, …) — previously only `/assets`, so mascot images 404'd in the desktop app.
- **Tests:** `frontend/e2e/mascot.cjs` (position, not covering the send button, gaze direction, expressions, states, mobile) and `tests/test_frontend_static.py`.

**Redesigned step tracker (flow_tracker) and agent cards (flow_agents)** — one UI font at 12–12.5px for both (no monospace), status markers the same size.
- **Step tracker:** header = status icon + current step + a `6/7` pill counter + a thin progress bar; the list is a vertical timeline (green dot done · pulsing blue running · grey pending), no "1. 2. 3." numbering; text after "→" becomes dimmed secondary text, trailing "..." removed from labels.
- **Agent cards:** lucide icon in a rounded tile + name + current activity (no "Executing:" prefix). The backend still sends `"<emoji> Agent <Name>"` (Telegram still uses it); the frontend strips the emoji and picks the icon by name from `AGENT_ICON` (`frontend/src/icons.ts`). New agents in `engine/agents` not yet in the table still show, with a robot icon.
- **Test:** `frontend/e2e/flow-ui.cjs` (a fake WebSocket replays a run).

**HTC Sense–style flip clock** (`frontend/src/clock.ts`) — one tile per digit (`HH:MM`; the `:` is 2 round dots emitting a "radar ping" — a blue ring spreading from each dot alternately, 2-second cycle, static when reduced motion is on), frameless, just a horizontal cut line through the digits; centred at the top of the main screen, right below the button row.
- **Effect:** on change, the top half of the old digit folds down and the bottom half of the new digit drops in (2 × 0.3 seconds). Only digits that change flip (10:59 → 11:00 keeps the leading 1). With no background tile, the two static halves fade out/in with the flap so old and new digits never overlap. Disabled when reduced motion is on.
- **Layer:** `z-index: 1`, above the orb only; the HUD, chat, map and Settings all overlay it. `pointer-events: none`, so it never blocks clicks.
- **Font:** Oswald Light (300), bundled into the build via `@fontsource/oswald` (latin subset) — the desktop app shows the right font offline.
- **Test:** `frontend/e2e/clock.cjs` (fake time via `page.clock`: shows 10:59, flips to 11:00, cleans up flaps, position, layer, font, mobile).

Also: editing and saving prompts (`POST /api/prompts/save`, only overwrites existing `prompt/*.md`); Graphfy became a live execution-flow map. Tests: `tests/test_settings_status_api.py`, `frontend/e2e/settings-dashboard.cjs`.

## v9.9.5 — 2026-09-25

**Prompt consolidation and self-reflective learning.** Spec written by Claude, planned and implemented by another model, then reviewed and fixed by Claude. Results in real use: better context understanding, faster responses, fewer tokens, easier maintenance.

| Issue found in review | Impact | Fix |
|---|---|---|
| History from the DB kept only `role` and `content` | `<ask_user>` tags were never rebuilt | Also keep the `ask_user`/`action_run` columns, tested on a temporary DB |
| History dropped every duplicate user turn | Lost earlier "yes" turns, affecting the gate too | Only merge duplicates that are adjacent |
| `unlearn_last_learning` deleted the newest lesson whenever you complained about routing | Data loss | Replaced by a controlled `retract` |
| Prompts copied into `.md` but code still used hard-coded text | Editing the `.md` had no effect | Code wired to the `.md` files, verified by golden tests |
| `learning_workflow.md` had a different output schema from the real prompt | Would have broken workflow learning | Rewritten to match the running prompt |
| Learning tests wrote to the real `data/` | Left junk in `Evolution.md` | Tests run in a temp folder; cleanup script removes the junk |
| Sampling changed after measuring on the old layout | Re-measured 10 times per scenario; the new config was worse | Kept `0.4 / 0.8 / 40` |
| Cleanup script edited `STYLE.md` before backing up, and the other model ran `--apply` on its own | Backup was missing `skills/self_evolution/` | Back up before any change |

**Further fixes after real use:**
- **Media played the wrong video**: filler words "tôi muốn … của" ("I want … by") pushed a re-upload to the top of the list. Filler words are now removed before ranking. The results table is copied verbatim from the tool and names the track actually playing.
- **Classifier**: hyphenated names such as "M-TP" count as one word, so shortened sentences are accepted.
- **Chat fabricated security-check results** when no tool ran: added `<tool_status>` to every chat turn. Re-measured: fabrication 8/10 → 0/10, correct offer protocol 10/10. Declined turns no longer claim "already opened" (1/10). Fabricated data was removed from the DB and wiki journals, with backups in `data/backups/`.

**Lessons from delegating to another model:**
- Tests must exercise the real code path, not just call functions with fake data.
- Tests must never touch the real `data/`.
- `--apply` operations on real data are run by the user.
- Only measure live on the layout actually running, with enough runs.
- When editing a prompt, prove it is byte-identical to the old one, or state clearly that it changed.
