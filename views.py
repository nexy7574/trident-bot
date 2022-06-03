import re
from typing import List, Callable, Tuple, Optional

import discord
from discord.ext import commands, pages
from discord.ui import View as BaseView, Select, button, Modal, InputText, Button


class View(BaseView):
    async def on_timeout(self) -> None:
        self.disable_all_items()
        if hasattr(self, "message"):
            if self.message is not None:
                try:
                    await self.message.edit(view=self)
                except discord.HTTPException:
                    pass

    async def on_error(self, error: Exception, item: discord.ui.Item, interaction: discord.Interaction) -> None:
        try:
            await interaction.followup.send(f"Error while processing interaction: {error}", ephemeral=True)
        except discord.HTTPException:
            pass
        finally:
            await super().on_error(error, item, interaction)

class TopicModal(Modal):
    def __init__(self):
        super().__init__(title="Enter a topic for your ticket")
        self.add_item(
            InputText(
                label="Why are you opening this ticket?",
                placeholder="This thing does that when it shouldn't.......",
                min_length=2,
                max_length=600,
                required=False,
            )
        )
        self.topic = None

    async def callback(self, interaction: discord.Interaction):
        self.topic = self.children[0].value
        await interaction.response.defer(invisible=True)
        self.stop()


class ChannelSelectorView(View):
    class Selector(Select):
        def __init__(self, channels: List[discord.abc.GuildChannel], channel_type: str, is_filtered: bool = False):
            super().__init__(placeholder="Select a %s%s" % (channel_type, (" (filtered)" if is_filtered else "")))
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
            await interaction.response.defer(invisible=True)
            self.view.stop()

    class SearchChannels(Modal):
        def __init__(self):
            super().__init__(title="Enter a search term (empty to clear)")
            self.add_item(
                InputText(
                    label="Search term:",
                    placeholder="e.g. 'gen' will display all channels with 'gen' in their name",
                    min_length=1,
                    max_length=100,
                    required=False,
                )
            )
            self.term = None

        async def callback(self, interaction: discord.Interaction):
            self.term = self.children[0].value
            await interaction.response.defer(invisible=True)
            self.stop()

    def __init__(self, channel_getter: Callable[[], List[discord.abc.GuildChannel]], channel_type: str = "category"):
        super().__init__()
        self.chosen = None
        self._channel_getter = channel_getter
        self.channel_type = channel_type
        self.search_term = None
        self.add_item(self.create_selector())

    def channel_getter(self) -> List[discord.abc.GuildChannel]:
        original = self._channel_getter()
        assert original is not None, "Channel getter returned None"
        if self.search_term is not None:
            found = [c for c in original if self.search_term.lower().strip() in c.name.lower().strip()]
            return [c for c in original if self.search_term.lower().strip() in c.name.lower().strip()]
        return original

    def create_selector(self):
        return self.Selector(self.channel_getter(), self.channel_type, self.search_term is not None)

    @button(label="Refresh", emoji="\U0001f504", style=discord.ButtonStyle.blurple)
    async def do_refresh(self, _, interaction: discord.Interaction):
        for child in self.children:
            if isinstance(child, discord.ui.Select):
                self.remove_item(child)
        self.add_item(self.create_selector())
        await interaction.response.defer(invisible=True)
        await interaction.edit_original_message(view=self)

    @button(label="Search", emoji="\U0001f50d")
    async def do_select_via_name(self, _, interaction: discord.Interaction):
        modal = self.SearchChannels()
        await interaction.response.send_modal(modal)
        await modal.wait()
        self.search_term = modal.term
        if len(self.channel_getter()) == 0:
            self.search_term = None
            await interaction.followup.send(
                "No channels match the criteria %r. Try again." % modal.term, ephemeral=True
            )
            return
        for child in self.children:
            if isinstance(child, discord.ui.Select):
                self.remove_item(child)
                break
        new = self.create_selector()
        self.add_item(new)
        await interaction.edit_original_message(view=self)

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
            await interaction.response.defer(invisible=True)
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
            await interaction.response.defer(invisible=True)
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
        await interaction.response.defer(invisible=True)
        await interaction.edit_original_message(view=self)

    @button(label="Search", emoji="\U0001f50d")
    async def do_select_via_name(self, _, interaction: discord.Interaction):
        modal = self.SearchRoles()
        await interaction.response.send_modal(modal)
        await modal.wait()
        if len(self.get_roles()) == 0:
            await interaction.followup.send("No roles match that criteria. Try again.", ephemeral=True)
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
            await interaction.response.defer(invisible=True)
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
        self.modify_button(1, manual=self.config.pingSupportRoles is False)
        self.modify_button(2, manual=self.config.supportEnabled is False)

    # noinspection PyTypeChecker
    def modify_button(self, index: int, *, manual: bool = None):
        styles = {
            True: discord.ButtonStyle.red,
            False: discord.ButtonStyle.green,
        }

        def replace(btn: Button, before: str = "on", after: str = "off"):
            return re.sub(r"\s%s$" % re.escape(before), " " + after, btn.label)

        if manual in [True, False]:
            # manual = False - option will be changed to enable
            # manual = True - option will be changed to disable
            # manual = None - option will be changed to the opposite of what it is now
            order = ("on", "off") if manual is False else ("off", "on")
            self.children[index].label = replace(self.children[index], *order)
            self.children[index].style = styles[not manual]
        else:
            order = ("on", "off") if self.children[index].label.endswith("on") else ("off", "on")
            self.children[index].label = replace(self.children[index], *order)
            self.children[index].style = styles[order[0] == "on"]

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user == self.ctx.user and await super().interaction_check(interaction)

    @button(label="View support roles", emoji="\N{books}", style=discord.ButtonStyle.blurple)
    async def do_view_roles(self, _, interaction: discord.Interaction):
        await self.paginator.respond(interaction, ephemeral=True)

    @button(label="Turn support ping on", emoji="\N{inbox tray}")
    async def toggle_support_ping(self, _, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        old = self.config.pingSupportRoles
        await self.config.update(pingSupportRoles=not self.config.pingSupportRoles)
        self.modify_button(1)
        # noinspection PyTypeChecker
        self.ctx.bot.loop.create_task(self.ctx.edit(view=self))
        if old:
            return await interaction.followup.send("Support ping roles have been turned off.", ephemeral=True)
        else:
            return await interaction.followup.send("Support ping roles have been turned on.", ephemeral=True)

    @button(label="Turn ticket creation on", emoji="\N{ticket}")
    async def toggle_ticket_creation(self, _, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        old = self.config.supportEnabled
        await self.config.update(supportEnabled=not self.config.supportEnabled)
        self.modify_button(2)
        # noinspection PyTypeChecker
        self.ctx.bot.loop.create_task(self.ctx.edit(view=self))
        if old:
            return await interaction.followup.send("Ticket creation has been turned off.", ephemeral=True)
        else:
            return await interaction.followup.send("Ticket creation has been turned on.", ephemeral=True)
