# Sebastian Thornmere

A Discord bot that plays Sebastian Thornmere, the shy Thornmere ghost who
rebuilt the Tri-Wizard Tournament. It speaks in character via the Claude API
(dynamic, not canned lines) when someone has spoken — name cues, replies and
mentions, rare pun asides, and the occasional housemate chime — remembers
things members say and brings them up later, and answers direct questions
through `/ask`. `/pun` coaxing a pun out of him, `/mazejournal` turning pages
of his old maze journals, and `/mood` for admins.

The name is configurable via `GHOST_NAME` in `.env` if you ever want to
rename it — it's woven into the system prompt, the bot's Discord presence,
and `/mood`.

This is meant to run as a **separate bot/service** from the other Velmora
ghosts — its own Discord application, its own Railway service — so the
personalities don't collide in the same process. He only ever speaks in
response to someone, and he never talks to the other ghosts.

## Setup

1. Create a Discord application + bot at https://discord.com/developers/applications
   - Enable the **Message Content Intent** and **Server Members Intent** under Bot settings.
   - Invite it to your server with the `bot` and `applications.commands` scopes,
     and at least: View Channels, Send Messages, Read Message History, Embed Links.
2. `cp .env.example .env` and fill in `DISCORD_TOKEN` and `ANTHROPIC_API_KEY`.
3. `pip install -r requirements.txt`
4. `python bot.py`

Slash commands sync automatically on startup (guild-instant if you set
`DEV_GUILD_ID` / `ALLOWED_GUILD_IDS` in `.env`, otherwise global sync which
can take up to an hour the first time).

## Commands

- `/ask question:<text>` — ask Sebastian something; he's shy, but he answers.
- `/pun [topic]` — coax a pun out of him — the one thing he's brave about.
- `/mazejournal` — a page from his old maze journals.
- `/mood` — (admin) peek at his current mood, for debugging.

## Structure

```
bot.py                 # entrypoint and client setup
cogs/
  personality.py       # Claude API wrapper + ghost voice/mood/memory
  haunting.py           # passive behaviors: name cues, puns, housemate chimes, memory
  commands.py           # /ask, /pun, /mazejournal, /mood
  diary.py              # long-term diary memory mixed into personality
data/
  memory_store.json     # persisted member quotes + mood + lore progress (runtime-created)
  lore.json              # maze-journal fragments, revealed in order
  velmora_lore.json      # shared Velmora ghost lore
  shared_history.json    # shared stories with Cassy and others
```

## Notes

- All dialogue is generated at request time by Claude (Haiku by default,
  configurable via `THORNMERE_MODEL`) using a system prompt that defines its
  voice, current mood, and any relevant remembered snippets — nothing is
  hardcoded canned text, though there are graceful fallback lines if the API
  call fails.
- State (mood, memories, lore progress) is persisted to a small JSON file
  under `STATE_DIR` (defaults to `data/`) so it survives restarts.
- Academy rumors (`/rumor` and the scheduled posts) live in Housecup.
