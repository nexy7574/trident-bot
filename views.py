import asyncio
import json
import os
import re
import textwrap
from typing import List, Callable, Tuple, Optional

import discord
from discord.ext import commands, pages
from discord.ui import View as BaseView, Select, button, Modal, InputText, Button

from database import Question, Guild


class View(BaseView):
    async def on_timeout(self) -> None:
        message = None
        self.disable_all_items()

        if hasattr(self, "message"):
            if self.message is not None:
                message = self.message
        if message is None and hasattr(self, "ctx"):
            self.ctx: discord.ApplicationContext
            try:
                message = self.ctx.message or await self.ctx.interaction.original_message()
            except discord.HTTPException:
                pass

        if message is not None:
            try:
                await message.edit(view=self)
            except discord.HTTPException:
                pass

    async def on_error(self, error: Exception, item: discord.ui.Item, interaction: discord.Interaction) -> None:
        try:
            await interaction.followup.send(f"Error while processing interaction: {error}", ephemeral=True)
        except discord.HTTPException:
            pass
        finally:
            await super().on_error(error, item, interaction)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if hasattr(self, "ctx"):
            return interaction.user == self.ctx.user


class ModalSelect(discord.ui.Select):
    def refresh_state(self, data) -> None:
        data: ComponentInteractionData = data  # type: ignore
        self._selected_values = data.get("values", [])


class QuestionsModal(Modal):
    def __init__(self, questions: List[Question]):
        super().__init__(title="Just a few questions first...")
        for q in questions:
            self.add_item(
                InputText(
                    style=discord.InputTextStyle.long if q["max_length"] > 50 else discord.InputTextStyle.short, **q
                )
            )
        self.answers = []

    async def callback(self, interaction: discord.Interaction):
        self.answers = [x.value or "" for x in self.children]
        await interaction.response.defer()
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
        if self.search_term is not None:
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

    @button(label="Cancel", emoji="\N{black square for stop}", style=discord.ButtonStyle.red)
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

    @button(label="Cancel", emoji="\N{black square for stop}", style=discord.ButtonStyle.red)
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
    def __init__(self, ctx: discord.ApplicationContext, config: Guild, *role_ids: int):
        super().__init__(timeout=15 * 60)
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

    @button(label="Manage new ticket questions", emoji="\U000023ec")
    async def modify_ticket_questions(self, _, interaction: discord.Interaction):
        await interaction.response.defer()
        view = TicketQuestionManagerView(self.ctx, self.config)
        await interaction.edit_original_message(view=view)
        await view.wait()
        await interaction.edit_original_message(view=self)


class TicketQuestionManagerView(View):
    children: List[discord.ui.Button]

    def __init__(self, ctx: discord.ApplicationContext, config: Guild):
        self.ctx = ctx
        self.config = config
        super().__init__()

    async def on_error(self, error: Exception, item: discord.ui.Item, interaction: discord.Interaction) -> None:
        fmt = json.dumps(self.to_components(), indent=4)
        paginator = commands.Paginator("```json")
        for line in fmt.splitlines():
            paginator.add_line(line)

        for page in paginator.pages:
            await self.ctx.send(page)

        fmt = json.dumps(item.to_component_dict(), indent=4)
        paginator = commands.Paginator("```json\n// Item specific")
        for line in fmt.splitlines():
            paginator.add_line(line)

        for page in paginator.pages:
            await self.ctx.send(page)

        await super().on_error(error, item, interaction)

    @button(label="Create question", emoji="\N{heavy plus sign}", style=discord.ButtonStyle.green)
    async def create_new_question(self, btn: discord.ui.Button, interaction: discord.Interaction):
        if len(self.config.questions) == 5:
            btn.disabled = True
            await interaction.edit_original_message(view=self)
            return await interaction.response.send_message(
                "\N{cross mark} You already have 5 questions, which is the maximum number of questions we can put in a"
                " popup. Please remove a question, or edit one."
            )
        modal = CreateNewQuestionModal()
        question = await modal.run(interaction)
        new_questions = self.config.questions
        new_questions.append(question)
        await self.config.update(questions=new_questions)
        await interaction.edit_original_message(
            content=f"\N{white heavy check mark} {os.urandom(3).hex()} | Added new question!"
        )

    @button(label="Preview questions", emoji="\U0001f50d")
    async def preview_questions(self, _, interaction: discord.Interaction):
        if len(self.config.questions) == 0:
            self.disable_all_items(exclusions=[discord.utils.get(self.children, emoji="\N{heavy plus sign}")])
            await interaction.edit_original_message(view=self)
            return await interaction.response.send_message(
                "\N{cross mark} You do not have any questions set. Please create one."
            )
        modal = QuestionsModal(self.config.questions)
        await interaction.response.send_modal(modal)
        try:
            await asyncio.wait_for(modal.wait(), timeout=600)
        except asyncio.TimeoutError:
            pass
        else:
            await interaction.followup.send(
                embed=discord.Embed(
                    description="Your answers to your questions:",
                    colour=discord.Colour.blurple(),
                    fields=[
                        discord.EmbedField(
                            name=self.config.questions[n]["label"][:256],
                            value=modal.answers[n][:1024] or "empty",
                            inline=False,
                        )
                        for n in range(len(modal.answers))
                    ],
                ),
                ephemeral=True,
            )

    @button(label="Edit question", emoji="\N{pencil}")
    async def edit_existing_question(self, _, interaction: discord.Interaction):
        await interaction.response.defer()
        if len(self.config.questions) == 0:
            self.disable_all_items(exclusions=[discord.utils.get(self.children, emoji="\N{heavy plus sign}")])
            await interaction.edit_original_message(view=self)
            return await interaction.response.send_message(
                "\N{cross mark} You do not have any questions set. Please create one."
            )
        view = EditQuestionView(self.ctx, self.config)
        _m = await interaction.followup.send(view=view)
        await view.wait()
        await _m.delete(delay=0.1)

    @button(label="Remove question", emoji="\N{heavy minus sign}", style=discord.ButtonStyle.red)
    async def remove_existing_question(self, _, interaction: discord.Interaction):
        await interaction.response.defer()
        if len(self.config.questions) == 0:
            self.disable_all_items(exclusions=[discord.utils.get(self.children, emoji="\N{heavy plus sign}")])
            await interaction.edit_original_message(view=self)
            return await interaction.response.send_message(
                "\N{cross mark} You do not have any questions set. Please create one."
            )
        view = RemoveQuestionView(self.ctx, self.config)
        _m = await interaction.followup.send(view=view)
        await view.wait()
        if len(self.config.questions) > 0:
            self.enable_all_items()
            await interaction.edit_original_message(view=self)
        await _m.delete(delay=0.1)

    @button(label="Finish", style=discord.ButtonStyle.primary, emoji="\U000023f9")
    async def finish(self, _, interaction: discord.Interaction):
        await interaction.response.defer()
        self.stop()


class CreateNewQuestionModal(Modal):
    def __init__(self, *, data: Question = None):
        data = data or {}
        # noinspection PyTypeChecker
        super().__init__(
            discord.ui.InputText(
                label="The question:",
                custom_id="label",
                placeholder="e.g: Why are you requesting support?",
                min_length=2,
                max_length=45,
                required=True,
                value=data.get("label"),
            ),
            discord.ui.InputText(
                label="Placeholder text:",
                custom_id="placeholder",
                placeholder="This is the text that looks like this",
                required=False,
                max_length=100,
                value=data.get("placeholder"),
            ),
            discord.ui.InputText(
                label="Minimum answer length:",
                custom_id="min_length",
                placeholder="Blank if no minimum length or not required",
                max_length=4,
                required=False,
                value=(lambda v: str(v) if v is not None else None)(data.get("min_length")),
            ),
            discord.ui.InputText(
                label="Maximum answer length:",
                custom_id="max_length",
                placeholder="Maximum is 1024",
                min_length=1,
                max_length=4,
                required=True,
                value=(lambda v: str(v) if v is not None else None)(data.get("min_length", 1024)),
            ),
            ModalSelect(
                custom_id="required",
                options=[
                    discord.SelectOption(
                        label="Answer required",
                        value="True",
                        description="This question requires an answer",
                        emoji="\N{white heavy check mark}",
                        default=True,
                    ),
                    discord.SelectOption(
                        label="Answer not required",
                        value="False",
                        description="This question does not require an answer",
                        emoji="\N{cross mark}",
                    ),
                ],
            ),
            title=f"{'Create' if bool(len(data)) is False else 'Edit'} a question:",
        )
        self._unprocessed = data or {"label": "", "placeholder": "", "min_length": "", "max_length": "", "required": ""}
        # For some reason, the dropdown is causing issues when editing or removing.
        if bool(len(data)) is not False:
            self.remove_item(self.children[-1])

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(invisible=True)
        for child in self.children:
            if hasattr(child, "values"):
                self._unprocessed[child.custom_id] = child.values[0]
            else:
                self._unprocessed[child.custom_id] = child.value
        self.stop()

    async def run(self, interaction: discord.Interaction) -> Question:
        def try_int(value: str) -> Optional[int]:
            try:
                return max(1, int(value))
            except ValueError:
                return

        await interaction.response.send_modal(self)
        await self.wait()
        processed = Question(
            **{
                "label": self._unprocessed["label"],
                "placeholder": self._unprocessed["placeholder"] or None,
                "required": self._unprocessed["required"] == "True",
                "min_length": try_int(self._unprocessed["min_length"]),
                "max_length": try_int(self._unprocessed["max_length"]),
            }
        )
        if processed["max_length"] and processed["max_length"] > 1024:
            processed["max_length"] = 1024
        if processed["min_length"] and processed["min_length"] > (processed["max_length"] or 1024):
            processed["min_length"] = None if not processed["max_length"] else processed["mxn_length"] - 2
        return processed


class EditQuestionView(View):
    def __init__(self, ctx: discord.ApplicationContext, config: Guild):
        self.ctx = ctx
        self.config = config
        super().__init__(timeout=600)
        self.add_item(
            discord.ui.Select(
                custom_id="selector",
                placeholder="Choose a question",
                options=[
                    discord.SelectOption(
                        label=f"Question {n+1} "
                        f"({textwrap.shorten(self.config.questions[n]['label'], 87, placeholder='...')})",
                        value=str(n),
                        emoji=str(n + 1) + "\N{variation selector-16}\N{combining enclosing keycap}",
                    )
                    for n in range(len(self.config.questions))
                ],
            )
        )
        discord.utils.get(self.children, custom_id="selector").callback = self.__select_callback()

    def __select_callback(self) -> Callable:
        # noinspection PyTypeChecker
        select: discord.ui.Select = discord.utils.get(self.children, custom_id="selector")
        assert select is not None

        async def callback(interaction: discord.Interaction):
            index = int(select.values[0])
            modal = CreateNewQuestionModal(data=self.config.questions[index])
            new_data = await modal.run(interaction)
            questions = self.config.questions
            questions.pop(index)
            questions.insert(index, new_data)
            await self.config.update(questions=questions)
            await interaction.followup.send(f"Edited question #{index+1}.")
            await interaction.delete_original_message(delay=0.1)
            self.stop()

        return callback

    @button(label="Cancel", style=discord.ButtonStyle.red, emoji="\U000023f9")
    async def cancel(self, _, interaction: discord.Interaction):
        await interaction.response.defer()
        self.stop()


class RemoveQuestionView(View):
    def __init__(self, ctx: discord.ApplicationContext, config: Guild):
        self.ctx = ctx
        self.config = config
        super().__init__(timeout=600)
        self.add_item(
            discord.ui.Select(
                custom_id="selector",
                placeholder="Choose a question",
                options=[
                    discord.SelectOption(
                        label=f"Question {n + 1} "
                        f"({textwrap.shorten(self.config.questions[n]['label'], 87, placeholder='...')})",
                        value=str(n),
                        emoji=str(n + 1) + "\N{variation selector-16}\N{combining enclosing keycap}",
                    )
                    for n in range(len(self.config.questions))
                ],
            )
        )
        discord.utils.get(self.children, custom_id="selector").callback = self.__select_callback()

    def __select_callback(self) -> Callable:
        # noinspection PyTypeChecker
        select: discord.ui.Select = discord.utils.get(self.children, custom_id="selector")
        assert select is not None

        async def callback(interaction: discord.Interaction):
            await interaction.response.defer()
            index = int(select.values[0])
            questions = self.config.questions
            questions.pop(index)
            await self.config.update(questions=questions)
            await interaction.followup.send(f"Deleted question #{index+1}.")
            await interaction.delete_original_message(delay=0.01)
            self.stop()

        return callback

    @button(label="Cancel", style=discord.ButtonStyle.red, emoji="\U000023f9")
    async def cancel(self, _, interaction: discord.Interaction):
        await interaction.response.defer()
        self.stop()
