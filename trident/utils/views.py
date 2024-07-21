import asyncio
import json
import os
import re
import textwrap
from typing import Callable, List, Optional, TypeVar

import discord
from discord.ext import commands, pages
from discord.ui import Button, InputText, Modal, Select
from discord.ui import View as BaseView
from discord.ui import button, channel_select, role_select

from ..models import TicketQuestion, Guild

T = TypeVar("T")


class CustomView(BaseView):
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
    def __init__(self, questions: list[TicketQuestion]):
        super().__init__(title="Just a few questions first...")
        self._qr = {}
        self._qs = {}
        for q in questions:
            item = self.add_item(
                InputText(
                    style=discord.InputTextStyle.long if q.max_length > 50 else discord.InputTextStyle.short,
                    custom_id=str(q.entry_id),
                    label=q.label,
                    placeholder=q.placeholder,
                    min_length=q.min_length,
                    max_length=q.max_length,
                    required=q.required,
                )
            )
            self._qr[str(q.entry_id)] = item
            self._qs[str(q.entry_id)] = q
        self.answers: dict[TicketQuestion, str] = {}

    def __getitem__(self, item: str | TicketQuestion) -> InputText:
        if isinstance(item, TicketQuestion):
            return self._qr[str(item.entry_id)]
        return self._qr[item]

    async def callback(self, interaction: discord.Interaction):
        for key, value in self._qr:
            self.answers[self._qs[key]] = value.value
        await interaction.response.defer()
        self.stop()


class ChannelSelectorCustomView(CustomView):
    def __init__(
        self,
        ctx: discord.ApplicationContext,
        channel_types: list[discord.ChannelType],
        minimum: int = 1,
        maximum: int = 1,
    ):
        super().__init__(disable_on_timeout=True)
        self.ctx = ctx
        self.chosen: discord.abc.GuildChannel | None = None
        self.get_item("channel").channel_types = channel_types
        self.get_item("channel").min_values = minimum
        self.get_item("channel").max_values = maximum

    @channel_select(placeholder="Pick a channel", custom_id="channel")
    async def channel_picker(self, select: Select, interaction: discord.Interaction):
        self.disable_all_items()
        await interaction.response.edit_message(view=self)
        self.chosen = select.values[0]
        self.stop()

    @button(label="Cancel", emoji="\N{BLACK SQUARE FOR STOP}", style=discord.ButtonStyle.red)
    async def do_cancel(self, _, interaction: discord.Interaction):
        self.disable_all_items()
        await interaction.response.edit_message(view=self)
        self.stop()


class RoleSelectorCustomView(CustomView):
    def __init__(self, ctx: discord.ApplicationContext, minimum: int = 1, maximum: int = 1):
        super().__init__(disable_on_timeout=True)
        self.ctx = ctx
        self.roles: list[discord.Role] = []

        self.get_item("role").min_values = minimum
        self.get_item("role").max_values = maximum

    @role_select(custom_id="role", placeholder="Pick a role")
    async def role_picker(self, select: Select, interaction: discord.Interaction):
        self.disable_all_items()
        await interaction.response.edit_message(view=self)
        self.roles = select.values
        self.stop()

    @button(label="Cancel", emoji="\N{BLACK SQUARE FOR STOP}", style=discord.ButtonStyle.red)
    async def do_cancel(self, _, __):
        self.stop()


class ConfirmCustomView(CustomView):
    chosen: Optional[bool] = None

    class ChoiceButton(Button):
        def __init__(self, label: str, positive: Optional[bool]):
            emojis = {False: "\N{CROSS MARK}", True: "\N{WHITE HEAVY CHECK MARK}", None: "\U0001f6d1"}
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
class ServerConfigCustomView(CustomView):
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

    @button(label="View support roles", emoji="\N{BOOKS}", style=discord.ButtonStyle.blurple)
    async def do_view_roles(self, _, interaction: discord.Interaction):
        await self.paginator.respond(interaction, ephemeral=True)

    @button(label="Turn support ping on", emoji="\N{INBOX TRAY}")
    async def toggle_support_ping(self, _, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        old = self.config.pingSupportRoles
        await self.config.update(pingSupportRoles=not self.config.pingSupportRoles)
        self.modify_button(1)
        # noinspection PyTypeChecker
        await interaction.followup.edit(view=self)
        if old:
            return await interaction.followup.send("Support ping roles have been turned off.", ephemeral=True)
        else:
            return await interaction.followup.send("Support ping roles have been turned on.", ephemeral=True)

    @button(label="Turn ticket creation on", emoji="\N{TICKET}")
    async def toggle_ticket_creation(self, _, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        old = self.config.supportEnabled
        await self.config.update(supportEnabled=not self.config.supportEnabled)
        self.modify_button(2)
        # noinspection PyTypeChecker
        await interaction.followup.edit(view=self)
        if old:
            return await interaction.followup.send("Ticket creation has been turned off.", ephemeral=True)
        else:
            return await interaction.followup.send("Ticket creation has been turned on.", ephemeral=True)

    @button(label="Manage new ticket questions", emoji="\U000023ec")
    async def modify_ticket_questions(self, _, interaction: discord.Interaction):
        await interaction.response.defer()
        view = TicketQuestionManagerCustomView(self.ctx, self.config)
        await interaction.edit_original_message(view=view)
        await view.wait()
        await interaction.edit_original_message(view=self)


class TicketQuestionManagerCustomView(CustomView):
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

    @button(label="Create question", emoji="\N{HEAVY PLUS SIGN}", style=discord.ButtonStyle.green)
    async def create_new_question(self, btn: discord.ui.Button, interaction: discord.Interaction):
        await self.config.fetch_related("questions")
        if len(self.config.questions) >= 5:
            btn.disabled = True
            await interaction.edit_original_message(view=self)
            return await interaction.response.send_message(
                "\N{CROSS MARK} You already have 5 questions, which is the maximum number of questions we can put in a"
                " form. Please remove a question, or edit one."
            )
        modal = CreateNewQuestionModal()
        question = await modal.run(interaction)
        await TicketQuestion.create(
            guild=self.config,
            **question
        )
        await interaction.edit_original_message(
            content=f"\N{WHITE HEAVY CHECK MARK} {os.urandom(3).hex()} | Added new question!"
        )

    @button(label="Preview questions", emoji="\U0001f50d")
    async def preview_questions(self, _, interaction: discord.Interaction):
        if len(self.config.questions) == 0:
            self.disable_all_items(exclusions=[discord.utils.get(self.children, emoji="\N{HEAVY PLUS SIGN}")])
            await interaction.edit_original_message(view=self)
            return await interaction.response.send_message(
                "\N{CROSS MARK} You do not have any questions set. Please create one."
            )
        modal = QuestionsModal(await self.config.questions.all())
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
                            name=question.label,
                            value=answer,
                        )
                        for question, answer in modal.answers.items()
                    ],
                ),
                ephemeral=True,
            )

    @button(label="Edit question", emoji="\N{PENCIL}", disabled=True)
    async def edit_existing_question(self, _, interaction: discord.Interaction):
        await interaction.response.defer()
        if len(self.config.questions) == 0:
            self.disable_all_items(exclusions=[discord.utils.get(self.children, emoji="\N{HEAVY PLUS SIGN}")])
            await interaction.edit_original_message(view=self)
            return await interaction.response.send_message(
                "\N{CROSS MARK} You do not have any questions set. Please create one."
            )
        view = EditQuestionCustomView(self.ctx, self.config)
        _m = await interaction.followup.send(view=view)
        await view.wait()
        await _m.delete(delay=0.1)

    @button(label="Remove question", emoji="\N{HEAVY MINUS SIGN}", style=discord.ButtonStyle.red, disabled=True)
    async def remove_existing_question(self, _, interaction: discord.Interaction):
        await interaction.response.defer()
        if len(self.config.questions) == 0:
            self.disable_all_items(exclusions=[discord.utils.get(self.children, emoji="\N{HEAVY PLUS SIGN}")])
            await interaction.edit_original_message(view=self)
            return await interaction.response.send_message(
                "\N{CROSS MARK} You do not have any questions set. Please create one."
            )
        view = RemoveQuestionCustomView(self.ctx, self.config)
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
    def __init__(self, *, data: TicketQuestion = None):
        # noinspection PyTypeChecker
        super().__init__(
            discord.ui.InputText(
                label="The question:",
                custom_id="label",
                placeholder="e.g: Why are you requesting support?",
                min_length=2,
                max_length=45,
                required=True,
                value=data.label if data else None,
            ),
            discord.ui.InputText(
                label="Placeholder text:",
                custom_id="placeholder",
                placeholder="This is the text that looks like this",
                required=False,
                max_length=100,
                value=data.placeholder if data else None,
            ),
            discord.ui.InputText(
                label="Minimum answer length:",
                custom_id="min_length",
                placeholder="Blank if no minimum length or not required",
                max_length=4,
                required=False,
                value=str(data.min_length) if data else None,
            ),
            discord.ui.InputText(
                label="Maximum answer length:",
                custom_id="max_length",
                placeholder="Maximum is 1024",
                min_length=1,
                max_length=4,
                required=True,
                value=str(data.max_length) if data else None,
            ),
            title=f"{'Create' if bool(len(data)) is False else 'Edit'} a question:",
        )
        self._unprocessed = data or {"label": "", "placeholder": "", "min_length": "", "max_length": "", "required": ""}

    async def callback(self, interaction: discord.Interaction):
        for child in self.children:
            if hasattr(child, "values"):
                self._unprocessed[child.custom_id] = child.values[0]
            else:
                self._unprocessed[child.custom_id] = child.value
        self.stop()

    async def run(self, interaction: discord.Interaction) -> dict[str, str | int | bool | None]:
        def try_int(value: str) -> Optional[int]:
            try:
                return max(1, int(value))
            except ValueError:
                return

        await interaction.response.send_modal(self)
        await self.wait()
        processed = {
            "label": self._unprocessed["label"],
            "placeholder": self._unprocessed["placeholder"] or None,
            "required": self._unprocessed["required"] == "True",
            "min_length": try_int(self._unprocessed["min_length"]),
            "max_length": try_int(self._unprocessed["max_length"]),
        }
        if processed["max_length"] and processed["max_length"] > 1024:
            processed["max_length"] = 1024
        if processed["min_length"] and processed["min_length"] > (processed["max_length"] or 1024):
            processed["min_length"] = None if not processed["max_length"] else processed["mxn_length"] - 2
        return processed


class EditQuestionCustomView(CustomView):
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
                        emoji=str(n + 1) + "\N{VARIATION SELECTOR-16}\N{COMBINING ENCLOSING KEYCAP}",
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


class RemoveQuestionCustomView(CustomView):
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
                        emoji=str(n + 1) + "\N{VARIATION SELECTOR-16}\N{COMBINING ENCLOSING KEYCAP}",
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
