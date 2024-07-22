import asyncio
import textwrap
from typing import Optional

import discord
from discord.ext import commands
from tortoise.transactions import in_transaction

from trident.models import Guild, Ticket
from trident.utils.views import QuestionsModal

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

    def log_channel(self, config) -> Optional[discord.TextChannel]:
        if not config.log_channel:
            return
        channel = self.bot.get_channel(config.log_channel)
        if not channel:
            return
        if not channel.can_send(discord.Embed()):
            return
        return channel

    async def send_log(self, ticket: Ticket, reason: str, closer: discord.Member) -> bool:
        log_channel = self.log_channel(ticket.guild)
        if log_channel:
            reason = textwrap.shorten(reason, width=1500, placeholder="...")
            await log_channel.send(
                f"Ticket #{ticket.number} closed by {closer.mention}.",
                embed=discord.Embed(
                    description=f"Ticket was opened by: <@{ticket.author}> (`{ticket.author}`)\nReason: {reason}",
                    colour=discord.Colour.greyple(),
                    timestamp=discord.utils.utcnow(),
                )
                .set_author(name=str(closer), icon_url=closer.display_avatar.url)
                .add_field(
                    name="Ticket info",
                    value=f"Author: <@{ticket.author}> (`{ticket.author}`)\n"
                    f"Opened: {discord.utils.format_dt(ticket.opened_at, 'R')}\n",
                    inline=False,
                ),
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return True
        else:
            return False

    @staticmethod
    def is_support(config: Guild, member: discord.Member) -> bool:
        support_role_ids = config.support_roles
        our_roles = [x.id for x in member.roles]
        return any(x in our_roles for x in support_role_ids)

    tickets_group = discord.SlashCommandGroup(
        "ticket",
        "Manage the current, or create a new ticket.",
        contexts={
            discord.InteractionContextType.guild
        }
    )

    @tickets_group.command()
    @discord.guild_only()
    @commands.max_concurrency(1, commands.BucketType.member, wait=False)
    async def new(self, ctx: discord.ApplicationContext):
        """Creates a new support ticket in the current server."""
        # First, we need to check to see if the guild has set the bot up. We see this by checking if the guild has an
        # entry in the Guilds table
        guild = await Guild.get_or_none(id=ctx.guild.id)
        if guild is None:
            return await ctx.respond(
                "This server has not yet set the bot up. Please ask an administrator to run `/setup`.", ephemeral=True
            )

        if guild.support_enabled is False:
            return await ctx.respond("This server is not currently accepting new tickets.", ephemeral=False)

        # Next, we need to check to see if the user has a ticket open, in this server.
        ticket = await Ticket.get_or_none(author=ctx.author.id, guild=guild)
        if ticket:
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
        category = self.bot.get_channel(guild.ticket_category)
        if category is None and guild.ticket_category is not None:
            guild.ticket_category = None
            await guild.save()
            return await ctx.respond("This server is not set up properly. Please ask an administrator to run `/setup`.")
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
            elif len(category.channels) >= guild.max_tickets:
                return await ctx.respond(
                    "The ticket category is full. Please wait for support to close some tickets.", ephemeral=True
                )
            else:
                if questions := await guild.questions.limit(5).all():
                    questions_modal = QuestionsModal(questions)
                    await ctx.send_modal(questions_modal)
                    try:
                        await asyncio.wait_for(questions_modal.wait(), timeout=600)
                    except asyncio.TimeoutError:
                        return
                    else:
                        answers = questions_modal.answers
                else:
                    answers = {}

                await ctx.respond("Creating ticket...", ephemeral=True)
                async with in_transaction() as tx:
                    support_roles = list(filter(lambda r: r is not None, map(ctx.guild.get_role, guild.support_roles)))
                    overwrites = {
                        ctx.guild.default_role: no,
                        ctx.user: yes,
                        ctx.me: yes,
                        **{r: yes for r in support_roles},
                    }
                    try:
                        channel: discord.TextChannel = await category.create_text_channel(
                            f"ticket-{guild.ticket_count}",
                            overwrites=overwrites,
                            position=0,
                            reason=f"Ticket created by {ctx.author.name}.",
                        )
                    except discord.HTTPException as e:
                        return await ctx.edit(content="Failed to create ticket - {!s}".format(e))
                    try:
                        ticket = await Ticket.create(
                            number=guild.ticket_count,
                            guild=guild,
                            channel=channel.id,
                            author=ctx.author.id,
                            opened_at=discord.utils.utcnow(),
                            using_db=tx
                        )
                    except Exception as e:
                        await channel.delete()
                        await ctx.edit(content="Failed to create ticket - {!s}".format(e), ephemeral=True)
                        raise
                    else:
                        guild.ticket_count += 1
                        if guild.ping_support_roles:
                            await channel.send(
                                ", ".join(x.mention for x in support_roles),
                            )

                        answer_embeds = [
                            discord.Embed(
                                title=question.label,
                                description=answer,
                                colour=discord.Colour.green()
                            )
                            for question, answer in answers.items()
                        ]
                        await channel.send(
                            ctx.author.mention,
                            embeds=[
                                discord.Embed(
                                    title="Ticket #{:,}".format(ticket.number),
                                    colour=discord.Colour.green(),
                                    timestamp=channel.created_at,
                                ).set_author(name=str(ctx.author), icon_url=ctx.author.display_avatar.url),
                                *answer_embeds,
                            ],
                        )
                        log_channel = self.log_channel(guild)
                        if log_channel is not None:
                            await log_channel.send(
                                embed=discord.Embed(
                                    title="Ticket #{:,} opened!".format(ticket.number),
                                    description="Subject: {}".format(ticket.subject),
                                    colour=discord.Colour.blurple(),
                                    timestamp=channel.created_at,
                                )
                                .set_author(name=str(ctx.author), icon_url=ctx.author.display_avatar.url)
                                .add_field(name="Jump to channel", value=channel.mention)
                            )
                        return await ctx.edit(content="Ticket created! {}".format(channel.mention))

    @tickets_group.command()
    async def info(self, ctx: discord.ApplicationContext):
        """Shows information about this ticket."""
        ticket = await Ticket.get_or_none(channel=ctx.channel.id)
        if not ticket:
            return await ctx.respond(content="This channel is not a ticket.", ephemeral=True)

        embed = discord.Embed(
            title=f"Ticket #{ticket.number}",
            description=f"**Global ID**: {ticket.entry_id}\n"
            f"**Ticket Number**: {ticket.number:,}\n"
            f"**Author**: <@{ticket.author}> (`{ticket.author}`)\n"
            f"**Ticket Channel**: {ctx.channel.mention}\n"
            f"**Ticket Opened**: {discord.utils.format_dt(ctx.channel.created_at, 'R')}\n"
            f"**Ticket Locked**? {'Yes' if ticket.locked else 'No'}",
            colour=discord.Colour.blurple(),
            timestamp=ctx.channel.created_at,
        )
        return await ctx.respond(embed=embed, ephemeral=True)

    @tickets_group.command(name="add-member")
    async def add_member(self, ctx: discord.ApplicationContext, member: discord.Member):
        """Adds a member to this ticket. Support only."""
        await ctx.defer()
        ticket = await Ticket.get_or_none(channel=ctx.channel.id)
        if not ticket:
            return await ctx.respond("This channel is not a ticket.", ephemeral=True)

        await ticket.fetch_related("guild")
        if not self.is_support(ticket.guild, ctx.author):
            return await ctx.respond("You are not a support member.", ephemeral=True)

        if ctx.channel.permissions_for(member).read_messages:
            return await ctx.respond("{} is already in this ticket.".format(member.mention), ephemeral=True)
        if not ctx.channel.permissions_for(ctx.me).manage_permissions:
            return await ctx.respond("I don't have permission to add members.", ephemeral=True)
        await ctx.channel.set_permissions(member, overwrite=yes, reason=f"Added by {ctx.author}")
        await ctx.respond("\N{INBOX TRAY} {} has been added to this ticket. Say hi!".format(member.mention))

    @tickets_group.command(name="remove-member")
    @discord.guild_only()
    async def remove_member(self, ctx: discord.ApplicationContext, member: discord.Member):
        """Removes a member from this ticket. Support only."""
        await ctx.defer(ephemeral=True)
        ticket = await Ticket.get_or_none(channel=ctx.channel.id)
        if not ticket:
            return await ctx.respond("This channel is not a ticket.", ephemeral=True)
        if member.id == ticket.author:
            return await ctx.respond("You do not have permission to do this.", ephemeral=True)

        await ticket.fetch_related("guild")

        if not self.is_support(ticket.guild, ctx.author) and member != ctx.author:
            return await ctx.respond("You are not a support member.", ephemeral=True)

        if not ctx.channel.permissions_for(ctx.me).manage_permissions:
            return await ctx.respond("I don't have permission to remove members.", ephemeral=True)

        if member == ctx.user:
            await ctx.channel.set_permissions(member, overwrite=no, reason="Left.")
            return await ctx.respond(f"\N{OUTBOX TRAY} {member.mention} left the ticket.")
        elif not self.is_support(ticket.guild, member):
            await ctx.channel.set_permissions(member, overwrite=no, reason="Removed.")
            return await ctx.respond(f"\N{OUTBOX TRAY} {member.mention} was removed from the ticket.")

        return await ctx.respond(
            "If you want someone to leave a ticket, please ask them to run this command themself.\n"
            "It is too hard to moderate staff removing each other, so to prevent abuse, this cannot happen at all.",
            ephemeral=True,
        )

    @commands.user_command(name="Remove from current ticket")
    async def remove_member_from_list(self, ctx: discord.ApplicationContext, member: discord.Member):
        await ctx.defer(ephemeral=True)
        ticket = await Ticket.get_or_none(channel=ctx.channel.id)
        if not ticket:
            return await ctx.respond("This channel is not a ticket.", ephemeral=True)
        if member.id == ticket.author:
            return await ctx.respond("You do not have permission to do this.", ephemeral=True)

        await ticket.guild.load()

        if not self.is_support(ticket.guild, ctx.author) and member != ctx.author:
            return await ctx.respond(content="You are not a support member.", ephemeral=True)

        if not ctx.channel.permissions_for(ctx.me).manage_permissions:
            return await ctx.respond(content="I don't have permission to remove members.", ephemeral=True)

        if member == ctx.user:
            await ctx.channel.set_permissions(member, overwrite=no, reason="Left.")
            return await ctx.respond(f"\N{OUTBOX TRAY} {member.mention} left the ticket.")
        elif not self.is_support(ticket.guild, member):
            await ctx.channel.set_permissions(member, overwrite=no, reason="Removed.")
            return await ctx.respond(f"\N{OUTBOX TRAY} {member.mention} was removed from the ticket.")

        return await ctx.respond(
            "If you want someone to leave a ticket, please ask them to run this command themself.\n"
            "It is too hard to moderate staff removing each other, so to prevent abuse, this cannot happen at all.",
            ephemeral=True,
        )

    @tickets_group.command(name="close")
    @discord.guild_only()
    @commands.max_concurrency(1, commands.BucketType.channel, wait=False)
    async def close(
        self,
        ctx: discord.ApplicationContext,
        reason: discord.Option(
            str,
            default="No reason provided.",
            description="The reason this ticket was closed.",
        ),
    ):
        """Closes this ticket. Support or author only."""
        ticket = await Ticket.get_or_none(channel=ctx.channel.id)
        if not ticket:
            return await ctx.respond("This channel is not a ticket.", ephemeral=True)
        await ticket.fetch_related("guild")
        if not self.is_support(ticket.guild, ctx.author):
            if ticket.author != ctx.author.id:
                return await ctx.respond(content="You are not a support member.", ephemeral=True)

        if ticket.locked and not ctx.author.guild_permissions.administrator:
            return await ctx.respond("This ticket is currently locked, and as such cannot be closed.", ephemeral=True)

        logged = await self.send_log(ticket, reason, ctx.author)
        if logged:
            await ctx.respond("Logged ticket. Closing now!")
        else:
            await ctx.respond("Closing now!")

        await ticket.delete()
        await ctx.channel.delete(reason="Closed by {!s}.".format(ctx.author))

    @tickets_group.command(name="lock")
    @discord.guild_only()
    @commands.max_concurrency(1, commands.BucketType.channel, wait=False)
    async def lock(self, ctx: discord.ApplicationContext):
        """Prevents the current ticket from being closed. Support only."""
        ticket = await Ticket.get_or_none(channel=ctx.channel.id)
        if not ticket:
            return await ctx.respond("This channel is not a ticket.", ephemeral=True)
        await ticket.fetch_related("guild")
        if not self.is_support(ticket.guild, ctx.author):
            return await ctx.respond(content="You are not a support member.", ephemeral=True)

        await ctx.defer()
        ticket.locked = not ticket.locked
        await ticket.save()
        if ticket.locked:
            if ctx.channel.permissions_for(ctx.me).manage_channels:
                if not ctx.channel.name.startswith("\N{LOCK}"):
                    await asyncio.wait_for(
                        ctx.channel.edit(
                            name="\N{LOCK}-ticket-{}".format(ticket.number),
                        ),
                        timeout=10,
                    )
            return await ctx.respond(
                "\N{LOCK} Ticket is now locked, so only administrators can close it. "
                "Run this command again to unlock it.",
                ephemeral=False,
            )
        else:
            if ctx.channel.permissions_for(ctx.me).manage_channels:
                if ctx.channel.name.startswith("\N{LOCK}"):
                    self.bot.loop.create_task(
                        ctx.channel.edit(
                            name="ticket-{}".format(ticket.number),
                        )
                    )
            return await ctx.respond(
                "\N{OPEN LOCK} Ticket is now unlocked, so anyone can close it. " "Run this command again to lock it.",
                ephemeral=False,
            )


def setup(bot):
    bot.add_cog(TicketCog(bot))
