import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN", "INSERISCI_QUI_IL_TUO_TOKEN")

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.messages = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)


@bot.event
async def on_ready():
    print(f"Logged in as: {bot.user} ({bot.user.id})")
    print(f"Connected to {len(bot.guilds)} guilds")


async def load_extensions():
    for extension in [
        "cogs.partnership",
        "cogs.tickets",
        "cogs.candidature",
    ]:
        try:
            await bot.load_extension(extension)
            print(f"Loaded: {extension}")
        except Exception as exc:
            print(f"Failed loading {extension}: {exc}")


async def main():
    await load_extensions()
    await bot.start(TOKEN)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
