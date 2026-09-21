"""
Passive presence: Sebastian noticing things without being asked - rarely.

- He's shy. He never speaks unprompted, only in response to a real message.
- An @mention or a reply to something he said always gets an answer.
- His name, "Sebastian", is the ONLY word he answers to. When called on
  he's shy - unless the talk is about the Tri-Wizard Tournament, and then
  his passion shows.
- Otherwise, very rarely, he chimes in unasked - and only if a good pun
  fits. If none does, he stays silent.
- Remembering what members say, condensing it into running notes.

Sebastian does not talk to the other ghosts. He ignores every bot entirely.
"""

import asyncio
import logging
import os
import random
import re

import discord
from discord.ext import commands

from cogs.personality import is_silence

log = logging.getLogger("thornmere.haunting")

# How often he considers chiming in, unasked, with a pun. Most of the time
# the model then decides nothing's good enough and he stays silent.
PUN_CHANCE = 0.03


def _parse_channel_ids(env_value: str | None):
    if not env_value:
        return None
    ids = set()
    for part in env_value.split(","):
        part = part.strip()
        if part.isdigit():
            ids.add(int(part))
    return ids or None


# His name is the only word he answers to. Nothing else calls him out.
NAME_CUE = (
    "Someone said your name. You're a little startled and pleased to be noticed. Answer shyly, briefly."
)

# ...unless they're talking about the tournament when they call on him.
# That's the one subject that brings him fully out of his shell.
TOURNAMENT_CUE = (
    "Someone called on you by name, and they're talking about the Tri-Wizard Tournament - YOUR "
    "tournament, your life's work. The shyness is gone. Answer with real passion and confidence: eager, "
    "vivid, proud, full of what makes it work and why it matters. Three or four sentences."
)

_NAME_PATTERN = re.compile(r"\bsebastian\b", re.IGNORECASE)
_TOURNAMENT_PATTERN = re.compile(r"\b(tri[- ]?wizard|tournament)s?\b", re.IGNORECASE)


def is_tournament_talk(content: str) -> bool:
    return bool(_TOURNAMENT_PATTERN.search(content or ""))


def match_keyword(content: str, rng=random):
    """His name is his only trigger. Returns (keyword, cue) or (None, None).
    Called on while the talk is about the tournament, he answers with passion."""
    text = (content or "").replace("\u2019", "'")
    if not _NAME_PATTERN.search(text):
        return None, None
    if is_tournament_talk(text):
        return "tournament", TOURNAMENT_CUE
    return "sebastian", NAME_CUE


class Haunting(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.allowed_channel_ids = _parse_channel_ids(os.getenv("HAUNT_CHANNEL_IDS"))

    async def _write_notes_safely(self, personality):
        try:
            await personality.update_notes()
        except Exception:
            log.exception("Failed to update server notes")

    async def _resolve_reply_chain(self, message: discord.Message, limit: int = 3):
        """Walk up a Discord reply chain from `message`, nearest first."""
        chain = []
        current = message
        for _ in range(limit):
            ref = getattr(current, "reference", None)
            if not ref:
                break
            original = ref.resolved if isinstance(ref.resolved, discord.Message) else None
            if original is None and ref.message_id:
                try:
                    original = await current.channel.fetch_message(ref.message_id)
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    break
            if original is None:
                break
            chain.append(original)
            current = original
        return chain

    async def _maybe_answer_direct_address(self, message: discord.Message, personality) -> bool:
        """A reply to something Sebastian said, or an @mention, always gets a
        real answer, with the exchange passed as genuine conversation turns
        so he never doubts his own earlier words."""
        me = self.bot.user
        if me is None:
            return False

        chain = await self._resolve_reply_chain(message)
        replying_to_me = bool(chain) and chain[0].author.id == me.id
        mentioned = any(u.id == me.id for u in message.mentions)
        if not (replying_to_me or mentioned):
            return False

        author_name = str(message.author.display_name)
        asked = re.sub(r"<@!?&?\d+>", "", message.content or "").strip()
        if not asked:
            return False

        history = []
        for msg in reversed(chain):
            text = (msg.content or "").strip()
            if not text:
                continue
            if msg.author.id == me.id:
                history.append({"role": "assistant", "content": text})
            else:
                history.append({"role": "user", "content": f"{msg.author.display_name}: {text}"})

        if replying_to_me:
            direction = (
                "Someone has just replied directly to something you said, and their reply is the last "
                "message above. Answer them, in character, carrying on naturally from your own last "
                "message. Everything above is a real exchange you were part of - never say you don't "
                "remember it, never question whether you said it, and never apologise or break character "
                "to explain yourself. Stay shy - a sentence or two at most - unless the talk is about the "
                "tournament, where your passion takes over."
            )
        else:
            direction = (
                "Someone has just spoken to you directly. Answer them in character - shy, brief, "
                "a little flustered to be noticed, but you DO answer. If it's about the tournament, "
                "the shyness falls away and your passion shows."
            )

        async with message.channel.typing():
            line = await personality.speak(
                f"{author_name}: {asked}", max_tokens=260, history=history, direction=direction,
            )
        try:
            await message.reply(line, mention_author=False)
        except discord.HTTPException:
            log.exception("Failed to answer direct address in %s", message.channel.id)
        return True

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Sebastian keeps to himself and the students. Other ghosts, and
        # every other bot, simply don't register.
        if message.author.bot or not message.guild:
            return
        if self.allowed_channel_ids and message.channel.id not in self.allowed_channel_ids:
            return

        personality = self.bot.get_cog("Personality")
        if not personality:
            return
        personality.maybe_shift_mood()

        content = message.content or ""
        author_name = str(message.author.display_name)

        if len(content.strip()) >= 12:
            if personality.remember(author_name, content, message.channel.id):
                asyncio.create_task(self._write_notes_safely(personality))

        if await self._maybe_answer_direct_address(message, personality):
            return

        keyword, matched_cue = match_keyword(content)

        cue = None
        if matched_cue:
            cue = f'{matched_cue} They said: "{content}"'
        elif len(content.strip()) >= 12 and random.random() < PUN_CHANCE:
            cue = (
                f'Someone said: "{content}". You were not asked. Only if a genuinely good, silly pun on what '
                "they said comes to you, slip it in shyly - one line. If not, reply with exactly SKIP."
            )

        if not cue:
            return

        if keyword:
            # Called on by name: he always answers. Shy, or - for the
            # tournament - with everything he's got.
            async with message.channel.typing():
                line = await personality.speak(cue, max_tokens=260 if keyword == "tournament" else 120)
        else:
            line = await personality.speak(cue, max_tokens=120, allow_silence=True)
        if is_silence(line):
            return
        try:
            await message.channel.send(line)
        except discord.HTTPException:
            log.exception("Failed to send reaction in %s", message.channel.id)


async def setup(bot: commands.Bot):
    await bot.add_cog(Haunting(bot))
