from typing import List, Callable, Tuple, Optional

import discord
import orm
from discord.ext import commands, pages
from discord.ui import View, Select, button, Modal, InputText, Button


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
        self.topic = None

    async def callback(self, interaction: discord.Interaction):
        self.topic = self.children[0].value
        await interaction.response.send_message("Input successful. You can dismiss this message.", ephemeral=True)
        self.stop()


class ChannelSelectorView(View):
    class Selector(Select):
        def __init__(self, channels: List[discord.abc.GuildChannel], channel_type: str):
            super().__init__(placeholder="Select a category")
            self.channel_type = channel_type
            for category in list(sorted(channels, key=lambda x: x.position))[:25]:
                emojis = {
                    discord.TextChannel: "<:text_channel:923666787038531635>",
                    discord.VoiceChannel: "<:voice_channel:923666789798379550>",
                    discord.CategoryChannel: "<:category:924001844290781255>",
                    discord.StageChannel: "<:stage_channel:923666792705032253>",
                }
                # noinspection PyTypeChecker
                self.add_option(label=category.name, emoji=emojis.get(type(category), ""), value=str(category.id))

        async def callback(self, interaction: discord.Interaction):
            self.view.chosen = self.values[0]
            self.view.stop()

    def __init__(self, channel_getter: Callable[[], List[discord.abc.GuildChannel]], channel_type: str = "category"):
        super().__init__()
        self.chosen = None
        self.channel_getter = channel_getter
        self.channel_type = channel_type
        self.add_item(self.Selector(self.channel_getter(), self.channel_type))

    @button(label="Refresh", emoji="\U0001f504", style=discord.ButtonStyle.blurple)
    async def do_refresh(self, _, interaction: discord.Interaction):
        self.remove_item(self.children[1])
        self.add_item(self.Selector(self.channel_getter(), self.channel_type))
        await interaction.edit_original_message(view=self)
        await interaction.response.send_message("Refreshed options.", ephemeral=True, delete_after=0.1)

    @button(label="Cancel", emoji="\N{black square for stop}\U0000fe0f", style=discord.ButtonStyle.red)
    async def do_cancel(self, _, __):
        self.stop()


class RoleSelectorView(View):
    roles: List[int]

    class Selector(Select):
        def __init__(self, roles: List[discord.Role], ranges: Tuple[int, int] = (1, 1), filtered: bool = False):
            super().__init__(
                placeholder="Select a role{}".format(" (filtered)" if filtered else ""),
                min_values=ranges[0],
                max_values=ranges[1],
            )
            for role in list(sorted(roles, key=lambda r: r.position, reverse=True))[:25]:
                self.add_option(
                    label=("@" + role.name)[:25],
                    value=str(role.id),
                    description=f"@{role.name}" if len("@" + role.name) > 25 else None,
                )

            if self.max_values > len(self.options):
                self.max_values = len(self.options)

        async def callback(self, interaction: discord.Interaction):
            self.view.roles = list(map(int, self.values))
            self.view.stop()

    class SearchRoles(Modal):
        def __init__(self):
            super().__init__(title="Put a search term (empty to clear)")
            self.add_item(
                InputText(
                    label="Search term:",
                    placeholder="e.g. 'admin' will display all roles with 'admin' in their name",
                    min_length=1,
                    max_length=100,
                    required=False,
                )
            )
            self.term = None

        async def callback(self, interaction: discord.Interaction):
            self.term = self.children[0].value
            await interaction.response.send_message(
                "Set search term to {!r}".format(self.term or "<none>"), ephemeral=True
            )
            self.stop()

    def __init__(self, roles_getter: Callable[[], List[discord.Role]], ranges: Tuple[int, int] = (1, 1)):
        super().__init__()
        self.roles_getter = roles_getter
        self.search_term = None
        self.ranges = ranges
        self.roles = []
        self.add_item(self.create_selector())

    def create_selector(self) -> "Selector":
        return self.Selector(self.get_roles(), self.ranges, self.search_term is not None)

    def get_roles(self) -> List[discord.Role]:
        fetched = self.roles_getter()
        if self.search_term is not None:
            fetched = [role for role in fetched if self.search_term.lower().strip() in role.name.lower().strip()]
        return fetched

    @button(label="Refresh", emoji="\U0001f504", style=discord.ButtonStyle.blurple)
    async def do_refresh(self, _, interaction: discord.Interaction):
        self.remove_item(self.children[2])
        new = self.create_selector()
        self.add_item(new)
        await interaction.edit_original_message(view=self)
        await interaction.response.send_message("Refreshed options.", ephemeral=True, delete_after=0.1)

    @button(label="Search", emoji="\U0001f50d")
    async def do_select_via_name(self, _, interaction: discord.Interaction):
        modal = self.SearchRoles()
        await interaction.response.send_modal(modal)
        await modal.wait()
        if len(self.get_roles()) == 0:
            await interaction.response.send_message("No roles match that criteria. Try again.", ephemeral=True)
            return
        self.search_term = modal.term
        self.remove_item(self.children[2])
        new = self.create_selector()
        self.add_item(new)
        await interaction.edit_original_message(view=self)

    @button(label="Cancel", emoji="\N{black square for stop}\U0000fe0f", style=discord.ButtonStyle.red)
    async def do_cancel(self, _, __):
        self.stop()


class ConfirmView(View):
    chosen: Optional[bool] = None

    class ChoiceButton(Button):
        def __init__(self, label: str, positive: Optional[bool]):
            emojis = {False: "\N{cross mark}", True: "\N{white heavy check mark}", None: "\U0001f6d1"}
            super().__init__(label=label, emoji=emojis[positive])
            self.positive = positive

        async def callback(self, interaction: discord.Interaction):
            await interaction.response.defer()
            self.view.chosen = self.positive
            self.view.stop()

    def __init__(
        self,
        confirm_label: str = "Yes",
        no_label: str = "No",
        cancel_label: str = "Cancel",
        show_cancel_button: bool = True,
    ):
        super().__init__()
        self.add_item(self.ChoiceButton(confirm_label, True))
        self.add_item(self.ChoiceButton(no_label, False))
        if show_cancel_button:
            self.add_item(self.ChoiceButton(cancel_label, None))


# noinspection PyUnresolvedReferences
class ServerConfigView(View):
    def __init__(self, ctx: discord.ApplicationContext, config, *role_ids: int):
        super().__init__()
        self.ctx = ctx
        self.config = config
        self.role_ids = role_ids
        self.roles = list(filter(lambda r: r is not None, map(self.ctx.guild.get_role, self.role_ids)))

        paginator = commands.Paginator(prefix="", suffix="", max_size=4069)
        for role in self.roles:
            paginator.add_line(f"{role.mention} - {role.name} - `{role.id}`")

        self.paginator = pages.Paginator([discord.Embed(description=page) for page in paginator.pages])
        self.modify_support_ping_button()

    def modify_support_ping_button(self):
        if self.config.pingSupportRoles:
            self.children[1].label = self.children[1].label.replace("on", "off")
            self.children[1].style = discord.ButtonStyle.red
        else:
            self.children[1].label = self.children[1].label.replace("off", "on")
            self.children[1].style = discord.ButtonStyle.green

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user == self.ctx.user and await super().interaction_check(interaction)

    @button(label="View support roles")
    async def do_view_roles(self, _, interaction: discord.Interaction):
        await self.paginator.respond(interaction, ephemeral=True)

    @button(label="Turn support ping on")
    async def toggle_support_ping(self, _, interaction: discord.Interaction):
        old = self.config.pingSupportRoles
        await self.config.update(pingSupportRoles=not self.config.pingSupportRoles)
        self.modify_support_ping_button()
        await interaction.edit_original_message(view=self)
        if old:
            return await interaction.response.send_message("Support ping roles have been turned off.", ephemeral=True)
        else:
            return await interaction.response.send_message("Support ping roles have been turned on.", ephemeral=True)


class PersistentCreateTicketButtonView(View):
    def __init__(self, bot, db_instance):
        super().__init__(timeout=None)
        self.db = db_instance
        self.bot = bot

    def log_channel(self, config) -> Optional[discord.TextChannel]:
        if not config.logChannel:
            return
        channel = self.bot.get_channel(config.logChannel)
        if not channel:
            return
        if not channel.can_send(discord.Embed()):
            return
        return channel

    @button(label="Create ticket", style=discord.ButtonStyle.blurple, emoji="\N{inbox tray}")
    async def do_create_ticket(self, _, interaction: discord.Interaction):
        from database import Ticket, Guild
        from cogs.ticket import yes, no

        modal = TopicModal()

        try:
            ticket = await Ticket.objects.get(author=interaction.user.id, guild__id=interaction.guild)
        except orm.NoMatch:
            try:
                guild = await Guild.objects.get(id=interaction.guild.id)
            except orm.NoMatch:
                await interaction.edit_original_message(view=None)
                await interaction.response.send_message("You are not in a guild with a ticket system.", ephemeral=True)
                await self.db.delete()
                return self.stop()

            await interaction.response.send_modal(modal)
            await modal.wait()
        else:
            channel = self.bot.get_channel(ticket.channel)
            if not channel:
                await ticket.delete()
                return await interaction.response.send_message(
                    "Your previous ticket was not closed correctly. It has now been deleted, please try again.",
                    ephemeral=True,
                )
            return await interaction.response.send_message(
                f"You already have a ticket open. <#{ticket.channel}>", ephemeral=True
            )

        sender = (
            interaction.response.send_message if interaction.response.is_done() is False else interaction.followup.send
        )

        if guild.supportEnabled is False:
            return await sender("The guild has disabled new tickets.", ephemeral=True)
        category = self.bot.get_channel(guild.ticketCategory)
        if category is None and guild.ticketCategory is not None:
            await guild.update(ticketCategory=None)
            return await sender(
                "This server is not set up properly. Please ask an administrator to run `/setup`.", ephemeral=True
            )

        if not category.permissions_for(interaction.guild.me).manage_channels:
            return await sender(
                "I do not have permission to manage channels in the ticket category. Please ask an administrator to"
                f" give me the `Manage Channels` permission in the category {category.name!r}",
                ephemeral=True,
            )
        elif len(category.channels) == 50:
            return await sender(
                "The ticket category is full. Please wait for support to close some tickets.", ephemeral=True
            )
        elif len(category.channels) >= guild.maxTickets:
            return await sender(
                "The ticket category is full. Please wait for support to close some tickets.", ephemeral=True
            )
        else:
            await sender("Creating ticket...", ephemeral=True)
            support_roles = list(filter(lambda r: r is not None, map(interaction.guild.get_role, guild.supportRoles)))
            overwrites = {
                interaction.guild.default_role: no,
                interaction.user: yes,
                interaction.guild.me: yes,
                **{r: yes for r in support_roles},
            }
            try:
                channel = await category.create_text_channel(
                    f"ticket-{guild.ticketCounter}",
                    overwrites=overwrites,
                    position=0,
                    reason=f"Ticket created by {interaction.user.name}.",
                )
                await channel.edit(topic=modal.topic)
            except discord.HTTPException as e:
                return await interaction.edit_original_message(content="Failed to create ticket - {!s}".format(e))
            try:
                ticket = await Ticket.objects.create(
                    localID=guild.ticketCounter,
                    guild=guild,
                    channel=channel.id,
                    author=interaction.user.id,
                    openedAt=discord.utils.utcnow(),
                    subject=modal.topic,
                )
            except Exception as e:
                await channel.delete()
                await sender(content="Failed to create ticket - {!s}".format(e), ephemeral=True)
                raise
            else:
                await guild.update(ticketCounter=guild.ticketCounter + 1)
                if guild.pingSupportRoles:
                    paginator = commands.Paginator(prefix="", suffix="", max_size=2000)
                    for role in support_roles:
                        paginator.add_line(f"{role.mention}")
                    _pages = [" ".join(page.splitlines()) for page in paginator.pages]
                    for page in _pages:
                        await channel.send(page, allowed_mentions=discord.AllowedMentions(roles=True))

                await channel.send(
                    interaction.user.mention,
                    embed=discord.Embed(
                        title="Ticket #{:,}".format(ticket.localID),
                        description="Subject: {}".format(modal.topic),
                        colour=discord.Colour.green(),
                        timestamp=channel.created_at,
                    ).set_author(name=str(interaction.user), icon_url=interaction.user.display_avatar.url),
                )
                log_channel = self.log_channel(guild)
                if log_channel is not None:
                    await log_channel.send(
                        embed=discord.Embed(
                            title="Ticket #{:,} opened!".format(ticket.localID),
                            description="Subject: {}".format(modal.topic),
                            colour=discord.Colour.blurple(),
                            timestamp=channel.created_at,
                        )
                        .set_author(name=str(interaction.user), icon_url=interaction.user.display_avatar.url)
                        .add_field(name="Jump to channel", value=channel.mention)
                    )
                return await sender(content="Ticket created! {}".format(channel.mention), ephemeral=True)
