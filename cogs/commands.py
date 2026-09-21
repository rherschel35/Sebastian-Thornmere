"""
Slash commands for talking to Sebastian directly:

- /ask <question>   - ask Sebastian something (he's shy, but he'll answer)
- /pun [topic]      - coax a pun out of him - the one thing he's brave about
- /mazejournal      - a page from his old maze journals
- /mood             - (admin) peek at his current mood

There is no /interact. Sebastian doesn't talk to the other ghosts.
"""

import json
import logging
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger("thornmere.commands")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
LORE_PATH = DATA_DIR / "lore.json"

COLOR = 0xB8434F  # Thornmere red


def _load_lore():
    try:
        with open(LORE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        log.exception("Failed to load lore.json")
        return []


class GhostCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.lore = _load_lore()

    def _personality(self):
        return self.bot.get_cog("Personality")

    @app_commands.command(name="ask", description="Ask Sebastian Thornmere a question. He's shy - be gentle.")
    @app_commands.describe(question="What do you want to ask him?")
    async def ask(self, interaction: discord.Interaction, question: str):
        personality = self._personality()
        if not personality:
            await interaction.response.send_message("No one's answering right now.", ephemeral=True)
            return

        await interaction.response.defer(thinking=True)

        asker = str(interaction.user.display_name)
        prior = personality.memories_about(asker, limit=1)
        memory_hint = prior[0] if prior else None

        cue = (
            f'{asker} asks you directly: "{question}". Answer as yourself - shy, a little flustered '
            "to be asked, but kind and genuinely engaged with what they actually asked. Keep it short - "
            "unless it's about the tournament, in which case let your passion show."
        )
        line = await personality.speak(cue, memory_hint=memory_hint, max_tokens=260)

        embed = discord.Embed(description=line, color=COLOR)
        embed.set_author(name=f"{asker} asks Sebastian…")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="pun", description="Coax a pun out of Sebastian.")
    @app_commands.describe(topic="Optional: something for the pun to be about")
    async def pun(self, interaction: discord.Interaction, topic: str | None = None):
        personality = self._personality()
        if not personality:
            await interaction.response.send_message("*a faint, embarrassed laugh, and nothing else.*",
                                                     ephemeral=True)
            return

        await interaction.response.defer(thinking=True)

        asker = str(interaction.user.display_name)
        about = f' about "{topic}"' if topic else ""
        cue = (
            f"{asker} has asked you for a pun{about}. This is the one thing you're brave about. Give "
            "exactly one gentle, silly, groan-worthy pun - wordplay, not arithmetic - and then, at most, "
            "a few shy words afterwards. No explanation of the joke."
        )
        line = await personality.speak(cue, max_tokens=100)

        embed = discord.Embed(description=line, color=COLOR)
        embed.set_footer(text="Sebastian looks faintly embarrassed about it.")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="mazejournal", description="Read a page from Sebastian's old maze journals.")
    async def mazejournal(self, interaction: discord.Interaction):
        personality = self._personality()
        if not personality:
            await interaction.response.send_message("The journals stay shut tonight.", ephemeral=True)
            return

        await interaction.response.defer(thinking=True)

        fragment = personality.next_lore_fragment(self.lore)
        if fragment is None:
            line = await personality.speak(
                "Someone has asked to read more of your old maze journals, but there are no more pages "
                "you're willing to share. Say so shyly and gently, in character, in a line or two - "
                "without explaining why.",
                max_tokens=100,
            )
            await interaction.followup.send(embed=discord.Embed(description=line, color=0x5A5A5A))
            return

        cue = (
            "Someone is reading a page from your old maze journals, from when you were alive and secretly "
            f'working out the maze. The page says: "{fragment}" React to it in your own voice, now - a line '
            "or two, shy and honest. Don't repeat the page."
        )
        line = await personality.speak(cue, max_tokens=140)

        embed = discord.Embed(title="From the maze journals of Sebastian Thornmere…",
                              description=f"*{fragment}*", color=COLOR)
        embed.add_field(name="Sebastian", value=line[:1024], inline=False)
        remaining = len(self.lore) - personality.state.get("lore_index", 0)
        embed.set_footer(text=f"{remaining} page{'s' if remaining != 1 else ''} still unread.")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="mood", description="(admin) Peek at Sebastian's current mood.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def mood(self, interaction: discord.Interaction):
        personality = self._personality()
        if not personality:
            await interaction.response.send_message("No mood to report.", ephemeral=True)
            return
        from cogs.personality import GHOST_NAME
        await interaction.response.send_message(
            f"{GHOST_NAME}'s current mood: `{personality.current_mood()}`", ephemeral=True
        )

    @mood.error
    async def mood_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("You need permission for this one.", ephemeral=True)
        else:
            log.exception("Unhandled error in /mood", exc_info=error)


async def setup(bot: commands.Bot):
    await bot.add_cog(GhostCommands(bot))
