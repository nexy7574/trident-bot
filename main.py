import asyncio
import json
import os
from datetime import timedelta
from pathlib import Path

import discord
from discord.ext import commands

from database import registry


class Bot(commands.Bot):
    def __init__(self):
        self.home = Path(__file__).parent
        os.chdir(self.home)
        with open(self.home / "config.json") as config_file:
            self.config = json.load(config_file)

        intents = discord.Intents.default()

        super().__init__(
            debug_guilds=self.config["debug_guilds"] if self.config["debug"] is True else None,
            owner_id=421698654189912064,
            intents=intents,
        )

        self.load_extension("jishaku")
        self.load_extension("cogs.ticket")
        self.load_extension("cogs.configuration")
        self.load_extension("cogs.tags")
        self.load_extension("cogs.general")
        self.connected_at = None
        self.last_reconnect = None
        self.started_at = None

    async def start(self, token: str, *, reconnect: bool = True) -> None:
        self.started_at = discord.utils.utcnow()
        return await super().start(token, reconnect=reconnect)

    async def login(self, token: str) -> None:
        await super().login(token)
        self.connected_at = discord.utils.utcnow()

    async def on_ready(self):
        self.last_reconnect = discord.utils.utcnow()
        print("Logged in as %s." % self.user)

    async def on_application_command_error(
        self, context: discord.ApplicationContext, exception: discord.DiscordException
    ):
        if isinstance(exception, commands.MissingPermissions):
            return await context.respond(
                embed=discord.Embed(
                    title="You are missing the following permissions to run this command:",
                    description=", ".join(x.replace("_", " ").title() for x in exception.missing_permissions),
                    color=discord.Color.red(),
                ),
                ephemeral=True,
            )
        elif isinstance(exception, commands.CommandOnCooldown):
            now = discord.utils.utcnow()
            end = now + timedelta(seconds=exception.retry_after)
            return await context.respond(
                embed=discord.Embed(
                    title="You're on cooldown!",
                    description=f"Try again {discord.utils.format_dt(end, 'R')}",
                    colour=discord.Colour.red(),
                ),
                ephemeral=True,
            )
        elif isinstance(exception, commands.MaxConcurrencyReached):
            return await context.respond(
                embed=discord.Embed(
                    title="Maximum concurrency for this command has been reached.",
                    description=f"Please try again later.\n\n'{exception!s}'",
                    colour=discord.Colour.red(),
                ),
                ephemeral=True,
            )
        await super().on_application_command_error(context, exception)


async def main():
    bot = Bot()
    await registry.create_all()
    return await bot.start(bot.config["token"] if bot.config["debug"] is False else bot.config["debug_token"])


if __name__ == "__main__":
    asyncio.run(main())
