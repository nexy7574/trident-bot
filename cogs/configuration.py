import discord
from discord.ext import commands

from database import Guild, orm
from utils.views import ChannelSelectorView, RoleSelectorView, ConfirmView, ServerConfigView


class ConfigurationCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    config_group = discord.SlashCommandGroup(
        "settings", "Manage server settings.", default_member_permissions=discord.Permissions(manage_guild=True)
    )

    @commands.slash_command(name="setup")
    @discord.default_permissions(manage_guild=True, manage_channels=True, manage_roles=True)
    @commands.has_permissions(manage_guild=True, manage_channels=True, manage_roles=True)
    async def set_up(self, ctx: discord.ApplicationContext):
        """Runs the setup wizard."""
        db_kwargs = {
            "id": ctx.guild.id,
        }

        view = ChannelSelectorView(lambda: ctx.guild.categories, "category")
        view.ctx = ctx
        await ctx.respond("Select a category to use for tickets.", view=view)
        await view.wait()
        if not view.chosen:
            return await ctx.edit(content="No category selected.", view=None)
        db_kwargs["ticketCategory"] = int(view.chosen)

        view = ChannelSelectorView(lambda: ctx.guild.text_channels, "channel")
        view.ctx = ctx

        await ctx.edit(content="Please select a channel to send logs to.", view=view)
        await view.wait()
        if not view.chosen:
            return await ctx.edit(content="No channel selected.", view=None)
        db_kwargs["logChannel"] = int(view.chosen)

        view = RoleSelectorView(lambda: ctx.guild.roles, (1, 25))
        view.ctx = ctx
        await ctx.edit(content="Please select roles to assign to tickets. Pick between 1 and 25.", view=view)
        await view.wait()
        if not view.roles:
            return await ctx.edit(content="No roles selected.", view=None)
        db_kwargs["supportRoles"] = view.roles

        view = ConfirmView("Yes", "No")
        view.ctx = ctx
        await ctx.edit(content="Should aforementioned roles be pinged when a ticket is opened?", view=view)
        await view.wait()
        if view.chosen is None:
            view.chosen = all(ctx.guild.get_role(role).mentionable for role in db_kwargs["supportRoles"])
        db_kwargs["pingSupportRoles"] = view.chosen
        await ctx.edit(content="Saving...", view=None)
        without_id = db_kwargs.copy()
        without_id.pop("id")
        instance, created = await Guild.objects.update_or_create(defaults=without_id, id=ctx.guild.id)
        if created:
            return await ctx.edit(content="Finished setting up your server!")
        else:
            return await ctx.edit(content="Updated your configuration.")

    @config_group.command(name="view")
    async def view_config(self, ctx: discord.ApplicationContext):
        """Shows you your server's current settings."""
        try:
            guild = await Guild.objects.get(id=ctx.guild.id)
        except orm.NoMatch:
            return await ctx.respond("This server has not yet been configured. Please use /setup.", ephemeral=True)

        embed = discord.Embed(
            title="Server Configuration",
            description="Use `/settings ` to see a list of settings you can change.",
            colour=discord.Colour.blurple(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="Total tickets:", value="{:,}".format(guild.ticketCounter - 1))
        category_channel = ctx.guild.get_channel(guild.ticketCategory)
        embed.add_field(name="Ticket category:", value=category_channel.mention if category_channel else "None")
        log_channel = ctx.guild.get_channel(guild.logChannel)
        embed.add_field(name="Log channel:", value=log_channel.mention if log_channel else "None")
        embed.add_field(name="Support roles:", value=str(len(guild.supportRoles)))
        embed.add_field(name="Ping support roles:", value="Yes" if guild.pingSupportRoles else "No")
        embed.add_field(name="Max open tickets:", value=str(guild.maxTickets))
        embed.add_field(name="Ticket creation enabled:", value="Yes" if guild.supportEnabled else "No")
        embed.set_footer(text="Server ID: {}".format(guild.id))
        view = ServerConfigView(ctx, guild, *guild.supportRoles)
        await ctx.respond(embed=embed, view=view)
        await view.wait()

    @config_group.command(name="reset")
    @discord.default_permissions(administrator=True)
    @commands.has_permissions(administrator=True)
    async def reset_config(self, ctx: discord.ApplicationContext):
        """Resets your server's configuration."""
        try:
            guild = await Guild.objects.get(id=ctx.guild.id)
        except orm.NoMatch:
            return await ctx.respond("This server has not yet been configured. Please use /setup.", ephemeral=True)

        view = ConfirmView("Yes", "No")
        await ctx.respond("Are you sure you want to reset your server config? You'll have to re-run /setup!", view=view)
        await view.wait()
        if view.chosen is None or view.chosen is False:
            return await ctx.edit(content="Cancelled.", view=None)
        else:
            await guild.delete()
            return await ctx.edit(content="Reset.", view=None)

    config_support_roles_group = config_group.create_subgroup(
        "support-roles", "Manage the roles that're added to tickets."
    )

    @config_support_roles_group.command(name="add")
    @discord.default_permissions(manage_roles=True)
    async def add_support_role(self, ctx: discord.ApplicationContext, role: discord.Role):
        """Adds a role to the list of support roles."""
        try:
            guild = await Guild.objects.get(id=ctx.guild.id)
        except orm.NoMatch:
            return await ctx.respond("This server has not yet been configured. Please use /setup.", ephemeral=True)

        if role.id in guild.supportRoles:
            return await ctx.respond("That role is already in the list.", ephemeral=True)
        if len(guild.supportRoles) == 25:
            return await ctx.respond("You can only have up to 25 support roles.", ephemeral=True)
        await guild.update(supportRoles=guild.supportRoles + [role.id])
        await ctx.respond("Added {} to the list of support roles.".format(role.mention), ephemeral=True)

    @config_support_roles_group.command(name="remove")
    @discord.default_permissions(manage_roles=True)
    async def remove_support_role(self, ctx: discord.ApplicationContext, role: discord.Role):
        """Removes a role from the list of support roles."""
        try:
            guild = await Guild.objects.get(id=ctx.guild.id)
        except orm.NoMatch:
            return await ctx.respond("This server has not yet been configured. Please use /setup.", ephemeral=True)

        if role.id not in guild.supportRoles:
            return await ctx.respond("That role is not in the list.", ephemeral=True)

        guild.supportRoles.remove(role.id)
        await guild.update(supportRoles=guild.supportRoles)
        await ctx.respond("Removed {} from the list of support roles.".format(role.mention), ephemeral=True)

    @config_group.command(name="log-channel")
    @discord.default_permissions(manage_channels=True)
    async def set_log_channel(self, ctx: discord.ApplicationContext, channel: discord.TextChannel):
        """Sets the channel to log ticket messages to."""
        try:
            guild = await Guild.objects.get(id=ctx.guild.id)
        except orm.NoMatch:
            return await ctx.respond("This server has not yet been configured. Please use /setup.", ephemeral=True)

        if not channel.can_send(discord.Embed()):
            return await ctx.respond("I cannot access that channel.", ephemeral=True)

        await guild.update(logChannel=channel.id)
        await ctx.respond("Log channel set to {}.".format(channel.mention), ephemeral=True)

    @config_group.command(name="ticket-category")
    @discord.default_permissions(manage_channels=True)
    async def set_ticket_category(self, ctx: discord.ApplicationContext, category: discord.CategoryChannel):
        """Sets the category to create tickets in."""
        try:
            guild = await Guild.objects.get(id=ctx.guild.id)
        except orm.NoMatch:
            return await ctx.respond("This server has not yet been configured. Please use /setup.", ephemeral=True)

        if not category.permissions_for(ctx.me).manage_channels:
            return await ctx.respond("I cannot manage that category.", ephemeral=True)

        await guild.update(ticketCategory=category.id)
        await ctx.respond("Ticket category set to {}.".format(category.mention), ephemeral=True)

    @config_group.command(name="max-tickets")
    @discord.default_permissions(manage_channels=True)
    async def set_max_tickets(
        self,
        ctx: discord.ApplicationContext,
        max_tickets: discord.Option(
            int,
            description="The maximum number of tickets that can be open at once.",
            min_value=1,
            max_value=50,
            default=50,
        ),
    ):
        """Sets the maximum number of tickets that can be open at once."""
        try:
            guild = await Guild.objects.get(id=ctx.guild.id)
        except orm.NoMatch:
            return await ctx.respond("This server has not yet been configured. Please use /setup.", ephemeral=True)
        await guild.update(maxTickets=max_tickets)
        await ctx.respond("Max tickets set to {}.".format(max_tickets), ephemeral=True)

    @config_group.command(name="new-tickets-enabled")
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
        try:
            guild = await Guild.objects.get(id=ctx.guild.id)
        except orm.NoMatch:
            return await ctx.respond("This server has not yet been configured. Please use /setup.", ephemeral=True)

        if enabled is None:
            enabled = not guild.supportEnabled

        await guild.update(supportEnabled=enabled)
        await ctx.respond("Ticket creation is now {}.".format("enabled" if enabled else "disabled"), ephemeral=True)


def setup(bot):
    bot.add_cog(ConfigurationCog(bot))
