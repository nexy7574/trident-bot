import functools
import subprocess
import time
from datetime import timedelta

import discord
import humanize
from discord.ext import commands

from database import Guild


def percent(part: float, whole: float, decimals: int = 1) -> str:
    return "%s%%" % round(part / whole * 100, decimals)


class GeneralCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.slash_command()
    async def invite(
        self,
        ctx: discord.ApplicationContext,
        with_permissions: discord.Option(
            bool,
            default=True,
            name="with-required-permissions",
            description="Whether to include the permissions required to operate the bot.",
        ),
    ):
        # noinspection GrazieInspection
        """Gives you an invite link to the bot"""
        required_permissions = discord.Permissions(274877959184)
        scope = ("bot", "applications.commands")
        if not with_permissions:
            required_permissions = discord.Permissions.none()

        url = discord.utils.oauth_url(self.bot.user.id, permissions=required_permissions, scopes=scope)
        return await ctx.respond(url, ephemeral=True)

    @commands.slash_command()
    async def ping(self, ctx: discord.ApplicationContext):
        """Shows the bot's latency"""
        return await ctx.respond(f"Pong! {round(self.bot.latency * 1000)}ms (WebSocket)")

    @commands.slash_command()
    async def about(self, ctx: discord.ApplicationContext):
        """Shows information about the bot."""
        await ctx.defer()

        # get git revision
        version = await self.bot.loop.run_in_executor(
            None,
            functools.partial(
                subprocess.run,
                ("git", "rev-parse", "--short", "HEAD"),
                capture_output=True,
                encoding="utf-8",
            ),
        )
        invite_link = discord.utils.oauth_url(self.bot.user.id, scopes=("bot", "applications.commands"))
        version = version.stdout.strip()
        system_started = discord.utils.utcnow() - timedelta(seconds=time.monotonic())
        owner = await self.bot.get_or_fetch_user(421698654189912064)

        total_users = len(self.bot.users)
        all_channels = list(self.bot.get_all_channels())
        all_text_channels = list(filter(lambda channel: channel.type == discord.ChannelType.text, all_channels))
        all_voice_channels = list(filter(lambda channel: channel.type == discord.ChannelType.voice, all_channels))
        all_stage_channels = list(filter(lambda channel: channel.type == discord.ChannelType.stage_voice, all_channels))
        ram_used = 0.0
        cpu_percent = 0.0
        disk_usage = (0.0, 1.0)
        proc_id = 0
        guilds_set_up = len(await Guild.objects.all())

        # system-stat related stuff will be done only if psutil is installed
        try:
            import psutil
        except ImportError:
            psutil = None
        else:
            process = psutil.Process()
            with process.oneshot():
                cpu_percent = await self.bot.loop.run_in_executor(None, process.cpu_percent, 1)
                _mem_info = await self.bot.loop.run_in_executor(None, process.memory_full_info)
                ram_used = _mem_info.uss
                proc_id = process.pid
            disk_usage = psutil.disk_usage(__file__)

        embed = discord.Embed(
            title="About Me",
            description=f"[Invite Link]({invite_link})\n"
            f"[Support Server](https://discord.gg/TveBeG7)\n"
            f"Trident is a simple, small bot designed to help you manage tickets in your server. "
            f"It allows you to give a way for users to create private channels with staff (tickets), with "
            f"a compete feature set to allow you to manage that. Trident is very simple to use, "
            f"amazingly fast, and super reliable.",
            colour=ctx.me.colour,
        )
        embed.set_author(name=str(owner), icon_url=owner.display_avatar.url)

        if psutil:
            disk_used_nice = humanize.naturalsize(disk_usage.used, binary=True)
            disk_total_nice = humanize.naturalsize(disk_usage.total, binary=True)
            embed.add_field(
                name="System Stats",
                value=f"CPU Usage: {cpu_percent}%\n"
                f"RAM Usage: {humanize.naturalsize(ram_used, binary=True)}\n"
                f"Disk Usage: {disk_used_nice}/{disk_total_nice}\n"
                f"Process ID: {proc_id}",
            )
        embed.add_field(
            name="Channels",
            value=f"Total: {len(all_channels):,}\n"
            f"Total text channels: {len(all_text_channels):,} ({percent(len(all_text_channels), len(all_channels))})\n"
            f"Total voice channels: {len(all_voice_channels):,} ({percent(len(all_voice_channels), len(all_channels))})\n"
            f"Total stage channels: {len(all_stage_channels):,} ({percent(len(all_stage_channels), len(all_channels))})",
        )
        embed.add_field(name="Users", value=f"Total: {total_users:,}")
        embed.add_field(name="Guilds", value=f"Total: {len(self.bot.guilds):,} ({guilds_set_up} database entries)")
        embed.add_field(
            name="Uptime",
            value=f"Bot started: {discord.utils.format_dt(self.bot.started_at, 'R')}\n"
            f"Bot connected: {discord.utils.format_dt(self.bot.connected_at, 'R')}\n"
            f"Bot last websocket reconnect: {discord.utils.format_dt(self.bot.last_reconnect, 'R')}\n"
            f"System started: {discord.utils.format_dt(system_started, 'R')}\n",
        )
        embed.set_footer(text="Trident v{}".format(version))
        return await ctx.respond(embed=embed)


def setup(bot):
    bot.add_cog(GeneralCog(bot))
