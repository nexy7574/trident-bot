import asyncio

import discord
from discord.ext import commands
import json
from pathlib import Path
from database import registry


class Bot(commands.Bot):
    def __init__(self):
        self.home = Path(__file__).parent
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

    async def on_ready(self):
        print("Logged in as %s." % self.user)

    async def on_application_command_error(
        self, context: discord.ApplicationContext, exception: discord.DiscordException
    ):
        if isinstance(exception, commands.MissingPermissions):
            return await context.respond(
                embed=discord.Embed(
                    title="You are missing the following permissions to run this command:",
                    description=", ".join(x.replace("_", " ").title() for x in exception.missing_permissions),
                )
            )
        await super().on_application_command_error(context, exception)


async def main():
    bot = Bot()
    await registry.create_all()
    return await bot.start(bot.config["token"])


if __name__ == "__main__":
    asyncio.run(main())
