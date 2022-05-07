from typing import List, Callable, Tuple, Optional

import discord
from discord.ext import commands, pages
from discord.ui import View, Select, button, Modal, InputText, Button


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
            await interaction.response.send_message(
                "Selected %s <#%s>." % (self.channel_type, self.values[0]), ephemeral=True, delete_after=0.1
            )
            self.view.chosen = self.values[0]
            self.view.stop()

    def __init__(self, channel_getter: Callable[[], List[discord.abc.GuildChannel]], channel_type: str = "category"):
        super().__init__()
        self.chosen = None
        self.channel_getter = channel_getter
        self.channel_type = channel_type
        self.add_item(self.Selector(self.channel_getter(), self.channel_type))

    @button(label="Refresh", emoji="\U0001f504")
    async def do_refresh(self, _, interaction: discord.Interaction):
        self.remove_item(self.children[1])
        self.add_item(self.Selector(self.channel_getter(), self.channel_type))
        await interaction.edit_original_message(view=self)
        await interaction.response.send_message("Refreshed options.", ephemeral=True, delete_after=0.1)


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
            await interaction.response.send_message(
                "Selected %d roles" % len(self.values), ephemeral=True, delete_after=0.1
            )
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

    @button(label="Refresh", emoji="\U0001f504")
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

    def __init__(self, confirm_label: str = "Yes", no_label: str = "No", cancel_label: str = "Cancel"):
        super().__init__()
        self.add_item(self.ChoiceButton(confirm_label, True))
        self.add_item(self.ChoiceButton(no_label, False))
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
