from typing import Annotated

import discord
from discord.ext import commands
from tortoise.transactions import in_transaction

from trident.models import Guild
from trident.utils.views import (
    ChannelSelectorCustomView,
    ConfirmCustomView,
    RoleSelectorCustomView,
)


class ConfigurationCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    config_group = discord.SlashCommandGroup(
        "settings",
        "Manage server settings.",
        default_member_permissions=discord.Permissions(manage_guild=True),
        contexts={discord.InteractionContextType.guild},
    )

    @commands.slash_command(name="setup")
    @discord.default_permissions(manage_guild=True, manage_channels=True, manage_roles=True)
    async def set_up(self, ctx: discord.ApplicationContext):
        """Runs the setup wizard."""
        view = ChannelSelectorCustomView(ctx, [discord.ChannelType.category])
        await ctx.respond("Select a category to use for tickets.", view=view)
        await view.wait()
        if not view.chosen:
            return await ctx.edit(content="No category selected.", view=None)

        async with in_transaction() as tx:
            entry, is_new = await Guild.get_or_create(id=ctx.guild.id, using_db=tx)
            entry.ticket_category = view.chosen.id

            view = ChannelSelectorCustomView(ctx, [discord.ChannelType.text])
            await ctx.edit(content="Please select a channel to send logs to.", view=view)
            await view.wait()
            if not view.chosen:
                return await ctx.edit(content="No channel selected.", view=None)
            entry.log_channel = view.chosen.id

            sr_view = RoleSelectorCustomView(ctx, 1, 25)
            sr_view.ctx = ctx
            await ctx.edit(content="Please select roles to assign to tickets. Pick between 1 and 25.", view=sr_view)
            await sr_view.wait()
            if not sr_view.roles:
                return await ctx.edit(content="No roles selected.", view=None)
            entry.support_roles = [role.id for role in sr_view.roles]

            view = ConfirmCustomView("Yes", "No")
            view.ctx = ctx
            await ctx.edit(content="Should aforementioned roles be pinged when a ticket is opened?", view=view)
            await view.wait()
            if view.chosen is None:
                view.chosen = all(x.mentionable for x in sr_view.roles)
            entry.ping_support_roles = view.chosen
            await ctx.edit(content="Saving...", view=None)
            await entry.save(tx)
            if is_new:
                return await ctx.edit(content="Finished setting up your server!")
            else:
                return await ctx.edit(content="Updated your configuration.")

    @config_group.command(name="view")
    async def view_config(self, ctx: discord.ApplicationContext):
        """Shows you your server's current settings."""
        await ctx.defer(ephemeral=True)
        guild = await Guild.get_or_none(id=ctx.guild.id)
        if not guild:
            return await ctx.respond("This server has not yet been configured. Please use /setup.", ephemeral=True)

        cmd = self.config_group.id
        embed = discord.Embed(
            title="Server Configuration",
            description=f"Use </settings:{cmd}> to see a list of settings you can change.",
            colour=discord.Colour.blurple(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="Total tickets:", value="{:,}".format(guild.ticket_count - 1))
        category_channel = ctx.guild.get_channel(guild.ticket_category)
        embed.add_field(name="Ticket category:", value=category_channel.mention if category_channel else "None")
        log_channel = ctx.guild.get_channel(guild.log_channel)
        embed.add_field(name="Log channel:", value=log_channel.mention if log_channel else "None")
        embed.add_field(name="Support roles:", value=str(len(guild.support_roles)))
        embed.add_field(name="Ping support roles:", value="Yes" if guild.ping_support_roles else "No")
        embed.add_field(name="Max open tickets:", value=str(guild.max_tickets))
        embed.add_field(name="Ticket creation enabled:", value="Yes" if guild.support_enabled else "No")
        embed.set_footer(text="Server ID: {}".format(guild.id))
        # view = ServerConfigCustomView(ctx, guild, *guild.support_roles)
        view = None
        await ctx.respond(embed=embed, view=view)
        # await view.wait()

    @config_group.command(name="reset")
    @discord.default_permissions(administrator=True)
    @commands.has_permissions(administrator=True)
    async def reset_config(self, ctx: discord.ApplicationContext):
        """Resets your server's configuration."""
        await ctx.defer(ephemeral=True)
        entry = await Guild.get_or_none(id=ctx.guild.id)
        if not entry:
            return await ctx.respond("This server has not yet been configured. Please use /setup.", ephemeral=True)

        view = ConfirmCustomView("Yes", "No")
        await ctx.respond("Are you sure you want to reset your server config? You'll have to re-run /setup!", view=view)
        await view.wait()
        if view.chosen is None or view.chosen is False:
            return await ctx.edit(content="Cancelled.", view=None)
        else:
            await entry.delete()
            return await ctx.edit(content="Reset.", view=None)

    config_support_roles_group = config_group.create_subgroup(
        "support-roles",
        "Manage the roles that are added to tickets.",
        default_member_permissions=discord.Permissions(manage_roles=True),
    )

    @config_support_roles_group.command(name="add")
    async def add_support_role(self, ctx: discord.ApplicationContext, role: discord.Role):
        """Adds a role to the list of support roles."""
        guild = await Guild.get_or_none(id=ctx.guild.id)
        if not guild:
            return await ctx.respond("This server has not yet been configured. Please use /setup.", ephemeral=True)
        await ctx.defer(ephemeral=True)
        if role.id in guild.support_roles:
            return await ctx.respond("That role is already in the list.", ephemeral=True)
        if len(guild.support_roles) == 25:
            return await ctx.respond("You can only have up to 25 support roles.", ephemeral=True)
        guild.support_roles += [role.id]
        await guild.save()
        await ctx.respond("Added {} to the list of support roles.".format(role.mention), ephemeral=True)

    @config_support_roles_group.command(name="remove")
    async def remove_support_role(self, ctx: discord.ApplicationContext, role: discord.Role):
        """Removes a role from the list of support roles."""
        guild = await Guild.get_or_none(id=ctx.guild.id)
        if not guild:
            return await ctx.respond("This server has not yet been configured. Please use /setup.", ephemeral=True)

        if role.id not in guild.support_roles:
            return await ctx.respond("That role is not in the list.", ephemeral=True)

        guild.support_roles.remove(role.id)
        await guild.save()
        await ctx.respond("Removed {} from the list of support roles.".format(role.mention), ephemeral=True)

    @config_group.command(name="log-channel")
    @discord.default_permissions(manage_channels=True)
    async def set_log_channel(self, ctx: discord.ApplicationContext, channel: discord.TextChannel):
        """Sets the channel to log ticket messages to."""
        guild = await Guild.get_or_none(id=ctx.guild.id)
        if guild is None:
            return await ctx.respond("This server has not yet been configured. Please use /setup.", ephemeral=True)

        if not channel.can_send(discord.Embed()):
            return await ctx.respond("I cannot access that channel.", ephemeral=True)

        guild.log_channel = channel.id
        await guild.save()
        await ctx.respond("Log channel set to {}.".format(channel.mention), ephemeral=True)

    @config_group.command(name="ticket-category")
    @discord.default_permissions(manage_channels=True)
    async def set_ticket_category(self, ctx: discord.ApplicationContext, category: discord.CategoryChannel):
        """Sets the category to create tickets in."""
        guild = await Guild.get_or_none(id=ctx.guild.id)
        if guild is None:
            return await ctx.respond("This server has not yet been configured. Please use /setup.", ephemeral=True)

        if not category.permissions_for(ctx.me).manage_channels:
            return await ctx.respond("I cannot manage that category.", ephemeral=True)

        guild.ticket_category = category.id
        await guild.save()
        await ctx.respond("Ticket category set to {}.".format(category.mention), ephemeral=True)

    @config_group.command(name="max-tickets")
    @discord.default_permissions(manage_channels=True)
    async def set_max_tickets(
        self,
        ctx: discord.ApplicationContext,
        max_tickets: Annotated[
            int,
            discord.Option(
                int,
                description="The maximum number of tickets that can be open at once.",
                min_value=1,
                max_value=50,
                default=50,
            ),
        ],
    ):
        """Sets the maximum number of tickets that can be open at once."""
        guild = await Guild.get_or_none(id=ctx.guild.id)
        if guild is None:
            return await ctx.respond("This server has not yet been configured. Please use /setup.", ephemeral=True)

        guild.max_tickets = max_tickets
        await guild.save()
        await ctx.respond("Max tickets set to {}.".format(max_tickets), ephemeral=True)

    @config_group.command(name="allow-new-tickets")
    @discord.default_permissions(manage_channels=True)
    async def set_support_enabled(
        self,
        ctx: discord.ApplicationContext,
        enabled: discord.Option(
            bool,
            default=None,
            description="If True, this will allow new tickets to be created. Blank toggles current setting.",
        ),
    ):
        """Enables or disables new ticket creation"""
        guild = await Guild.get_or_none(id=ctx.guild.id)
        if guild is None:
            return await ctx.respond("This server has not yet been configured. Please use /setup.", ephemeral=True)

        if enabled is None:
            enabled = not guild.support_enabled

        guild.support_enabled = enabled
        await guild.save()
        await ctx.respond("Ticket creation is now {}.".format("enabled" if enabled else "disabled"), ephemeral=True)


def setup(bot):
    bot.add_cog(ConfigurationCog(bot))
