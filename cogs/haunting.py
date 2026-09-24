"""
Passive presence: Sebastian noticing things without being asked - rarely.

- He's shy. He never speaks unprompted, only in response to a real message.
- An @mention or a reply to something he said always gets an answer.
- His name, "Sebastian", is the ONLY word he answers to. When called on
  he's shy - unless the talk is about the Tri-Wizard Tournament, and then
  his passion shows.
- Otherwise, very rarely, he chimes in unasked - and only if a good pun
  fits. If none does, he stays silent.
- His own house, Thornmere, is the exception: with Thornmere students he's
  warm and talkative - longer answers when called on, and now and then he
  joins their conversation unasked (at most once per channel every few
  minutes).
- Remembering what members say, condensing it into running notes.

Sebastian does not talk to the other ghosts. He ignores every bot entirely.
"""

import asyncio
import logging
import os
import random
import re
import time

import discord
from discord.ext import commands

from cogs.personality import is_silence

log = logging.getLogger("thornmere.haunting")

# How often he considers chiming in, unasked, with a pun. Most of the time
# the model then decides nothing's good enough and he stays silent.
PUN_CHANCE = 0.03

# His own house. Thornmere students get a warmer, more talkative Sebastian:
# he answers them at more length, and now and then joins their conversation
# unasked. Matched by role ID (override with HOUSE_ROLE_ID), falling back to
# a role named exactly "Thornmere".
HOUSE_ROLE_ID = int(os.getenv("HOUSE_ROLE_ID", "1550167097622134784") or 0)
HOUSE_ROLE_NAME = "thornmere"
# Chance he joins in, unasked, when a housemate says something (he can still
# decide he has nothing to add). At most once per channel per cooldown.
HOUSE_CHIME_CHANCE = float(os.getenv("HOUSE_CHIME_CHANCE", "0.15"))
HOUSE_CHIME_COOLDOWN = int(os.getenv("HOUSE_CHIME_COOLDOWN_SECONDS", "300"))


def is_housemate(member) -> bool:
    """True if this member has the Thornmere house role."""
    for role in getattr(member, "roles", None) or []:
        if role.id == HOUSE_ROLE_ID or (role.name or "").strip().lower() == HOUSE_ROLE_NAME:
            return True
    return False


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

# Called on by one of his own house: much less shy.
HOUSE_NAME_CUE = (
    "One of your own Thornmere students said your name. With them you're at ease - warm, glad they "
    "called, and happy to talk. Answer in two or three sentences, and feel free to ask them something back."
)

# Joining a housemate's conversation, unasked.
HOUSE_CHIME_CUE = (
    "One of your own Thornmere students just said this, not to you: \"{content}\". You like them and you're "
    "comfortable around them, so you might join in - a warm comment, a little encouragement, a small hint if "
    "they're stuck, a question about what they're up to, or a pun if a good one fits. One or two sentences. "
    "If you genuinely have nothing worth adding, reply with exactly SKIP."
)

_NAME_PATTERN = re.compile(r"\bsebastian\b", re.IGNORECASE)
_TOURNAMENT_PATTERN = re.compile(r"\b(tri[- ]?wizard|tournament)s?\b", re.IGNORECASE)


def is_tournament_talk(content: str) -> bool:
    return bool(_TOURNAMENT_PATTERN.search(content or ""))


def match_keyword(content: str, rng=random, housemate: bool = False):
    """His name is his only trigger. Returns (keyword, cue) or (None, None).
    Called on while the talk is about the tournament, he answers with passion.
    Called on by a housemate, he's warm and talkative instead of shy."""
    text = (content or "").replace("\u2019", "'")
    if not _NAME_PATTERN.search(text):
        return None, None
    if is_tournament_talk(text):
        return "tournament", TOURNAMENT_CUE
    if housemate:
        return "house", HOUSE_NAME_CUE
    return "sebastian", NAME_CUE


class Haunting(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.allowed_channel_ids = _parse_channel_ids(os.getenv("HAUNT_CHANNEL_IDS"))
        self._last_house_chime = {}  # channel_id -> timestamp of his last unasked housemate chime

    def _house_chime_ready(self, channel_id: int) -> bool:
        return time.time() - self._last_house_chime.get(channel_id, 0) >= HOUSE_CHIME_COOLDOWN

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

        housemate = is_housemate(message.author)
        if housemate:
            direction = (
                "One of your own Thornmere students is talking to you directly - the last message above. "
                "With your own house you're at ease: warm, glad they came to you, and happy to talk. Answer "
                "in two or three sentences, carry on naturally from anything you said before, and feel free "
                "to ask them something back. Everything above is a real exchange you were part of - never say "
                "you don't remember it or break character. If it's about the tournament, your passion takes over."
            )
        elif replying_to_me:
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

        if housemate:
            author_name += " (a Thornmere student - your house)"
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

        housemate = is_housemate(message.author)
        keyword, matched_cue = match_keyword(content, housemate=housemate)

        cue = None
        if matched_cue:
            speaker = f"{author_name}, a Thornmere student," if housemate else "They"
            cue = f'{matched_cue} {speaker} said: "{content}"'
        elif housemate and len(content.strip()) >= 12 and self._house_chime_ready(message.channel.id) \
                and random.random() < HOUSE_CHIME_CHANCE:
            self._last_house_chime[message.channel.id] = time.time()
            cue = f"{author_name}: " + HOUSE_CHIME_CUE.format(content=content)
        elif len(content.strip()) >= 12 and random.random() < PUN_CHANCE:
            cue = (
                f'Someone said: "{content}". You were not asked. Only if a genuinely good, silly pun on what '
                "they said comes to you, slip it in shyly - one line. If not, reply with exactly SKIP."
            )

        if not cue:
            return

        if keyword:
            # Called on by name: he always answers. Shy, warm for his own
            # house, or - for the tournament - with everything he's got.
            tokens = {"tournament": 260, "house": 200}.get(keyword, 120)
            async with message.channel.typing():
                line = await personality.speak(cue, max_tokens=tokens)
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
