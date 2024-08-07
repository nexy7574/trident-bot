import tomllib
import sys
import logging
from datetime import timedelta

import discord
import httpx
import tortoise
from discord.ext import commands


class Bot(commands.Bot):
    def __init__(self):
        with open("config.toml", "rb") as config_file:
            self.config = tomllib.load(config_file)
            self.config.setdefault("trident", {})
            self.config["trident"].setdefault("debug", False)
            self.config["trident"].setdefault("debug_guilds", None)
            self.config["trident"].setdefault("owner_id", None)

        intents = discord.Intents.default()

        super().__init__(
            debug_guilds=self.config["trident"]["debug_guilds"] if self.config["trident"]["debug"] is True else None,
            owner_id=self.config["trident"]["owner_id"],
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
        self.session = httpx.AsyncClient(timeout=httpx.Timeout(60))

        self.server = None
        self.server_task = None

    async def start(self, token: str, *, reconnect: bool = True) -> None:
        self.started_at = discord.utils.utcnow()
        await super().start(token, reconnect=reconnect)

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
    logging.basicConfig(
        datefmt="%Y-%m-%d",
        format="%(asctime)s - %(name)s - %(levelname)s: %(message)s",
        level=bot.config["trident"].get("log_level", "INFO").upper(),
    )
    await tortoise.Tortoise.init(
        config={
            "connections": {"default": bot.config["database"]["url"]},
            "apps": {
                "models": {
                    "models": ["trident.models"],
                    "default_connection": "default",
                },
            },
        }
    )
    await tortoise.Tortoise.generate_schemas()
    return await bot.start(
        bot.config["trident"]["token"]
        if bot.config["trident"]["debug"] is False
        else bot.config["trident"]["debug_token"]
    )


if __name__ == "__main__":
    sys.path.append("..")
    tortoise.run_async(main())
