from typing import Optional

import discord
from discord.ext import commands
from discord.ui import Modal, InputText

from database import Ticket, Guild, orm

yes = discord.PermissionOverwrite(
    read_messages=True,
    send_messages=True,
    add_reactions=True,
    read_message_history=True,
    embed_links=True,
    attach_files=True,
    external_emojis=True,
    use_slash_commands=True,
)
no = discord.PermissionOverwrite.from_pair(discord.Permissions.none(), discord.Permissions.all())


class TicketCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def log_channel(self, config, guild: discord.Guild) -> Optional[discord.TextChannel]:
        if not config.logChannel:
            return
        channel = self.bot.get_channel(config.logChannel)
        if not channel:
            return
        if not channel.can_send(discord.Embed()):
            return
        return channel

    tickets_group = discord.SlashCommandGroup("tickets", "Manage tickets.")

    @tickets_group.command()
    @commands.max_concurrency(1, commands.BucketType.member, wait=True)
    async def new(self, ctx: discord.ApplicationContext, topic: str = None):
        """Creates a new support ticket in the current server."""
        if not ctx.guild:
            return await ctx.respond("This command can only be used in a server.")

        if topic is None:

            class TopicModal(Modal):
                def __init__(self):
                    super().__init__(title="Enter a topic for your ticket")
                    self.add_item(
                        InputText(
                            label="Why are you opening this ticket?",
                            placeholder="This thing does that when it shouldn't.......",
                            min_length=2,
                            max_length=2000,
                            required=False,
                        )
                    )

                async def callback(self, interaction: discord.Interaction):
                    nonlocal topic
                    topic = self.children[0].value
                    await interaction.response.send_message("Input successful.", ephemeral=True)
                    await interaction.delete_original_message(delay=0.2)
                    self.stop()

            modal = TopicModal()
            await ctx.send_modal(modal)
            await modal.wait()

        else:
            await ctx.defer(ephemeral=True)  # Show loading until we can actually respond

        # First, we need to check to see if the guild has set the bot up. We see this by checking if the guild has an
        # entry in the Guilds table
        try:
            guild = await Guild.objects.get(id=ctx.guild.id)
        except orm.NoMatch:
            return await ctx.respond(
                "This server has not yet set the bot up. Please ask an administrator to run `/setup`.", ephemeral=True
            )

        # Next, we need to check to see if the user has a ticket open, in this server.
        try:
            ticket = await Ticket.objects.get(author=ctx.author.id, guild=guild)
        except orm.NoMatch:
            pass
        else:
            # Notify the user of the location of their ticket
            channel = self.bot.get_channel(ticket.channel)
            if not channel:
                await ticket.delete()
                return await ctx.respond(
                    "Your previous ticket was not closed correctly. It has now been deleted, please try again.",
                    ephemeral=True,
                )

            return await ctx.respond(
                f"You already have a ticket open: <#{ticket.channel}>. Please go there first.", ephemeral=True
            )

        # If we've made it this far, we can create the ticket.
        # First step is getting the guild's ticket category (if any)
        category = self.bot.get_channel(guild.ticketCategory)
        if category is None and guild.ticketCategory is not None:
            await guild.update(ticketCategory=None)
            await ctx.respond("This server is not set up properly. Please ask an administrator to run `/setup`.")
        else:
            # We now need to check to see if we can create and manage channels in this category.
            if not category.permissions_for(ctx.guild.me).manage_channels:
                return await ctx.respond(
                    "I do not have permission to manage channels in the ticket category. Please ask an administrator to"
                    f" give me the `Manage Channels` permission in the category {category.name!r}",
                    ephemeral=True,
                )
            elif len(category.channels) == 50:
                return await ctx.respond(
                    "The ticket category is full. Please wait for support to close some tickets.", ephemeral=True
                )
            elif len(category.channels) >= guild.maxTickets:
                return await ctx.respond(
                    "The ticket category is full. Please wait for support to close some tickets.", ephemeral=True
                )
            else:
                await ctx.respond("Creating ticket...", ephemeral=True)
                support_roles = list(filter(lambda r: r is not None, map(ctx.guild.get_role, guild.supportRoles)))
                overwrites = {
                    ctx.guild.default_role: no,
                    ctx.user: yes,
                    ctx.me: yes,
                    **{r: yes for r in support_roles},
                }
                try:
                    channel = await category.create_text_channel(
                        f"ticket-{guild.ticketCounter}",
                        overwrites=overwrites,
                        position=0,
                        reason=f"Ticket created by {ctx.author.name}.",
                    )
                    await channel.edit(topic=topic)
                except discord.HTTPException as e:
                    return await ctx.edit(content="Failed to create ticket - {!s}".format(e))
                try:
                    ticket = await Ticket.objects.create(
                        localID=guild.ticketCounter,
                        guild=guild,
                        channel=channel.id,
                        author=ctx.author.id,
                        openedAt=discord.utils.utcnow(),
                        subject=topic,
                    )
                except Exception as e:
                    await channel.delete()
                    await ctx.respond(content="Failed to create ticket - {!s}".format(e), ephemeral=True)
                    raise
                else:
                    await guild.update(ticketCounter=guild.ticketCounter + 1)
                    if guild.pingSupportRoles:
                        paginator = commands.Paginator(prefix="", suffix="", max_size=2000)
                        for role in support_roles:
                            paginator.add_line(f"{role.mention}")
                        pages = [" ".join(page.splitlines()) for page in paginator.pages]
                        for page in pages:
                            await channel.send(page, allowed_mentions=discord.AllowedMentions(roles=True))

                    await channel.send(
                        ctx.author.mention,
                        embed=discord.Embed(
                            title="Ticket #{:,}".format(ticket.localID),
                            description="Subject: {}".format(topic),
                            colour=discord.Colour.green(),
                            timestamp=channel.created_at,
                        ).set_author(name=str(ctx.author), icon_url=ctx.author.display_avatar.with_format("png")),
                    )
                    return await ctx.edit(content="Ticket created! {}".format(channel.mention))

    @tickets_group.command(name="add-member")
    async def add_member(self, ctx: discord.ApplicationContext, member: discord.Member):
        """Adds a member to this ticket. Support only."""
        try:
            ticket = await Ticket.objects.get(channel=ctx.channel.id)
        except orm.NoMatch:
            return await ctx.respond(content="This is not a ticket channel.", ephemeral=True)
        await ticket.guild.load()
        if not any(x.id in ticket.guild.supportRoles for x in ctx.author.roles):
            return await ctx.respond(content="You are not a support member.", ephemeral=True)

        if ctx.channel.permissions_for(member).read_messages:
            return await ctx.respond(content="{} is already in this ticket.".format(member.mention), ephemeral=True)
        if not ctx.channel.permissions_for(ctx.me).manage_permissions:
            return await ctx.respond(content="I don't have permission to add members.", ephemeral=True)
        await ctx.channel.set_permissions(member, overwrite=yes, reason=f"Added by {ctx.author}")
        await ctx.respond(content="\N{inbox tray} {} has been added to this ticket. Say hi!".format(member.mention))

    @tickets_group.command(name="remove-member")
    async def remove_member(self, ctx: discord.ApplicationContext, member: discord.Member):
        """Removes a member from this ticket. Support only."""
        try:
            ticket = await Ticket.objects.get(channel=ctx.channel.id)
        except orm.NoMatch:
            return await ctx.respond(content="This is not a ticket channel.", ephemeral=True)
        if member.id == ticket.author:
            return await ctx.respond("No.", ephemeral=True)
        await ticket.guild.load()
        if not any(x.id in ticket.guild.supportRoles for x in ctx.author.roles):
            return await ctx.respond(content="You are not a support member.", ephemeral=True)
        if not ctx.channel.permissions_for(ctx.me).manage_permissions:
            return await ctx.respond(content="I don't have permission to remove members.", ephemeral=True)
        if member == ctx.user or not any(x.id in ticket.guild.supportRoles for x in member.roles):
            await ctx.channel.set_permissions(member, overwrite=no, reason=f"Removed.")
            return await ctx.respond(f"\N{outbox tray} {member.mention} left the ticket.")

        return await ctx.respond(
            "If you want someone to leave a ticket, please ask them to run this command themself.\n"
            "It is too hard to moderate staff removing each other, so to prevent abuse, this cannot happen at all.",
            ephemeral=True,
        )

    @tickets_group.command(name="close")
    async def close(self, ctx: discord.ApplicationContext, reason: str = "No reason provided."):
        """Closes this ticket. Support or author only."""
        try:
            ticket = await Ticket.objects.get(channel=ctx.channel.id)
        except orm.NoMatch:
            return await ctx.respond(content="This is not a ticket channel.", ephemeral=True)
        await ticket.guild.load()
        if not any(x.id in ticket.guild.supportRoles for x in ctx.author.roles) or ctx.author.id != ticket.author:
            return await ctx.respond(content="You are not a support member.", ephemeral=True)

        log_channel = self.log_channel(ticket.guild, ctx.guild)
        if log_channel:
            await log_channel.send(
                f"Ticket #{ticket.localID} closed by {ctx.author.mention}.",
                embed=discord.Embed(
                    description=f"Ticket was opened by: <@{ticket.author}> (`{ticket.author}`)\n" f"Reason: {reason}",
                    colour=discord.Colour.greyple(),
                    timestamp=discord.utils.utcnow(),
                ).set_author(name=str(ctx.author), icon_url=ctx.author.display_avatar.url),
            )
            await ctx.respond("Logged ticket. Closing now!")
        else:
            await ctx.respond("Closing now!")

        await ticket.delete()
        await ctx.channel.delete(reason="Closed by {!s}.".format(ctx.author))


def setup(bot):
    bot.add_cog(TicketCog(bot))
