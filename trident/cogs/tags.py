import copy
import textwrap
from typing import Annotated

import discord
from discord.ext import commands, pages
from discord.ui import Modal

from trident.models import Guild, Tag
from trident.utils.views import ConfirmCustomView


class TagsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @staticmethod
    async def tag_autocomplete_internal(ctx: discord.AutocompleteContext):
        assert ctx.interaction.guild is not None
        all_tags = (
            await Tag.filter(guild__id=ctx.interaction.guild.id, name__icontains=ctx.options["tag"].lower())
            .limit(25)
            .all()
        )
        return [tag.name.lower().strip() for tag in all_tags]

    tag_autocomplete = discord.utils.basic_autocomplete(tag_autocomplete_internal)

    tag_group = discord.SlashCommandGroup(
        name="tag", description="Manage tags", contexts={discord.InteractionContextType.guild}
    )

    @tag_group.command(name="view")
    @discord.guild_only()
    async def tag_view(
        self, ctx: discord.ApplicationContext, tag: Annotated[str, discord.Option(str, autocomplete=tag_autocomplete)]
    ):
        """View a tag"""
        tag = await Tag.get_or_none(name=tag.lower().strip(), guild__id=ctx.guild.id)
        if not tag:
            return await ctx.respond("Tag not found.")

        if len(tag.content) > 2000:
            user = await self.bot.get_or_fetch_user(tag.author)
            embed = discord.Embed(description=tag.content, colour=ctx.author.colour)
            embed.set_author(name=user.display_name, icon_url=user.display_avatar.url)
            content = None
        else:
            embed = None
            content = tag.content

        await ctx.respond(content=content, embed=embed, allowed_mentions=discord.AllowedMentions.none())
        tag.uses += 1
        await tag.save()

    @tag_group.command(name="create")
    @discord.guild_only()
    @discord.default_permissions(manage_messages=True)
    async def tag_create(self, ctx: discord.ApplicationContext):
        """Create a tag."""
        guild = await Guild.get_or_none(id=ctx.guild.id)
        if guild is None:
            return await ctx.respond("This server has not yet been configured. Please use /setup.", ephemeral=True)

        class InputModal(Modal):
            def __init__(self):
                super().__init__(title="Create a tag.")
                self.add_item(
                    discord.ui.InputText(
                        label="Tag name:", placeholder="super cool tag name here", min_length=1, max_length=64
                    )
                )
                self.add_item(
                    discord.ui.InputText(
                        style=discord.InputTextStyle.long,
                        label="Tag content:",
                        placeholder="super cool tag content here",
                        min_length=1,
                        max_length=4000,
                    )
                )

            async def callback(self, interaction: discord.Interaction):
                await interaction.response.defer(ephemeral=True)
                tag_name = self.children[0].value.lower().strip()
                tag_content = self.children[1].value

                _existing_tag = await Tag.get_or_none(name__iexact=tag_name, guild__id=ctx.guild.id)
                if _existing_tag:
                    return await interaction.followup.send_message(
                        "A tag with that name already exists.", ephemeral=True
                    )
                await Tag.create(
                    name=tag_name.lower().strip(),
                    guild=guild,
                    content=tag_content,
                    author=ctx.author.id,
                    owner=ctx.author.id,
                )
                await interaction.followup.send(
                    "Successfully created a tag with the name `{}`!.".format(tag_name.replace("`", "\\`")),
                    ephemeral=True,
                )

        return await ctx.send_modal(InputModal())

    @tag_group.command(name="list")
    async def tag_list(self, ctx: discord.ApplicationContext, search: str = None):
        """Shows a list of every tag"""
        await ctx.defer(ephemeral=True)
        _pages = []
        if search is None:
            all_tags = await Tag.filter(guild__id=ctx.guild.id).order_by("-uses").all()
        else:
            all_tags = await Tag.filter(guild__id=ctx.guild.id, name__icontains=search).order_by("-uses").all()
        for page_number, tag_chunk in enumerate(discord.utils.as_chunks(iter(all_tags), 10), start=1):
            page = discord.Embed(
                title="Tags, page {:,}".format(page_number), description="", color=discord.Color.blurple()
            )
            for tag in tag_chunk:
                page.description += "`{}` - {} uses\n".format(tag.name, tag.uses)
            page.description = page.description[:-1]
            _pages.append(page)

        if len(_pages) == 0:
            if search:
                return await ctx.respond(content="No tags matching that criteria found.", ephemeral=True)
            else:
                return await ctx.respond(content="This server has no tags.", ephemeral=True)

        paginator = pages.Paginator(_pages, timeout=180)
        return await paginator.respond(ctx.interaction, ephemeral=True)

    @tag_group.command(name="delete")
    async def tag_delete(
        self, ctx: discord.ApplicationContext, tag: Annotated[str, discord.Option(str, autocomplete=tag_autocomplete)]
    ):
        """Deletes a tag"""
        tag = await Tag.get_or_none(name=tag.lower().strip(), guild__id=ctx.guild.id)
        if not tag:
            return await ctx.respond("Tag not found.")

        if not ctx.author.guild_permissions.administrator:
            if tag.owner != ctx.author.id:
                return await ctx.respond("You do not have permission to delete this tag.", ephemeral=True)

        confirm = ConfirmCustomView(show_cancel_button=False)
        confirm.ctx = ctx
        await ctx.respond("Are you sure you want to delete this tag? This cannot be undone!", view=confirm)
        await confirm.wait()
        if confirm.chosen is not True:
            return await ctx.edit(content="Tag was not deleted.", view=None)
        else:
            await tag.delete()
            return await ctx.edit(content="Tag was successfully deleted.", view=None)

    @tag_group.command(name="edit")
    async def tag_edit(
        self, ctx: discord.ApplicationContext, tag: Annotated[str, discord.Option(str, autocomplete=tag_autocomplete)]
    ):
        """Edits a tag. You must be an administrator or own the tag."""
        tag = await Tag.get_or_none(name=tag.lower().strip(), guild__id=ctx.guild.id)
        if not tag:
            return await ctx.respond("Tag not found.")

        if not ctx.author.guild_permissions.administrator:
            if tag.owner != ctx.author.id:
                return await ctx.respond("You do not have permission to edit this tag.", ephemeral=True)

        class InputModal(Modal):
            def __init__(self):
                super().__init__(title=f"Edit tag: {tag.name!r}")
                self.tag_copy = copy.copy(tag)
                self.add_item(
                    discord.ui.InputText(
                        label="Tag name:", placeholder=tag.name, min_length=1, max_length=64, required=False
                    )
                )
                self.add_item(
                    discord.ui.InputText(
                        style=discord.InputTextStyle.long,
                        label="Tag content:",
                        placeholder=textwrap.shorten(tag.content, width=512, placeholder="..."),
                        min_length=1,
                        max_length=4000,
                        required=False,
                    )
                )

            async def callback(self, interaction: discord.Interaction):
                tag_name = self.children[0].value
                tag_content = self.children[1].value

                kwargs = {}

                if tag_name:
                    tag_name = tag_name.lower().strip()
                    _existing_tag = await Tag.get_or_none(name__iexact=tag_name, guild__id=ctx.guild.id)
                    if _existing_tag:
                        return await interaction.followup.send_message(
                            "A tag with that name already exists.", ephemeral=True
                        )
                    kwargs["name"] = tag_name

                if tag_content:
                    kwargs["content"] = tag_content

                if bool(kwargs) is False:
                    return await interaction.response.send_message("No changes were made.", ephemeral=True)

                await interaction.response.defer(ephemeral=True)
                await tag.update_from_dict(kwargs)
                await interaction.followup.send(
                    f"Successfully edited tag {tag.name!r}.",
                    ephemeral=True,
                )

        return await ctx.send_modal(InputModal())

    @tag_group.command(name="transfer")
    @discord.guild_only()
    async def tag_transfer(
        self,
        ctx: discord.ApplicationContext,
        tag: discord.Option(str, autocomplete=tag_autocomplete),
        to: discord.Member,
    ):
        """Transfers ownership of a tag to someone else."""
        tag = await Tag.get_or_none(name=tag.lower().strip(), guild__id=ctx.guild.id)
        if not tag:
            return await ctx.respond("Tag not found.")

        if not ctx.author.guild_permissions.administrator:
            if tag.owner != ctx.author.id:
                return await ctx.respond("You do not have permission to transfer this tag.", ephemeral=True)

        confirm = ConfirmCustomView()
        await ctx.respond(
            f"Are you sure you want to give ownership of {tag.name!r} to {to.mention}? "
            f"You will no-longer be able to modify this tag.",
            view=confirm,
            ephemeral=True,
        )
        await confirm.wait()
        if confirm.chosen is None:
            return await ctx.respond("Transfer cancelled.", ephemeral=True)
        if confirm.chosen is False:
            return await ctx.respond("Did not transfer tag.", ephemeral=True)
        tag.owner = to.id
        await tag.save()
        await ctx.edit(content=f"Successfully transferred tag {tag.name!r} to {to.mention}.", view=None)

    @tag_group.command(name="info")
    @discord.guild_only()
    async def tag_info(self, ctx: discord.ApplicationContext, tag: discord.Option(str, autocomplete=tag_autocomplete)):
        """Shows information about a tag."""

        class ClaimTagView(discord.ui.View):
            @discord.ui.button(label="Claim tag", style=discord.ButtonStyle.green)
            async def steal_tag(self, _, interaction: discord.Interaction):
                await tag.update(owner=ctx.author.id)
                self.disable_all_items()
                await interaction.edit_original_message(view=self)
                await interaction.response.send_message("\N{WHITE HEAVY CHECK MARK} You now own this ticket!")

        tag = await Tag.get_or_none(name=tag.lower().strip(), guild__id=ctx.guild.id)
        if not tag:
            return await ctx.respond("Tag not found.")

        created_at = tag.created_at
        author = await self.bot.get_or_fetch_user(tag.author)
        owner = await self.bot.get_or_fetch_user(tag.owner)
        try:
            await ctx.guild.fetch_member(tag.owner)
            in_guild = True
        except discord.HTTPException:
            in_guild = False

        embed = discord.Embed(
            title=f"{tag.name!r}:",
            description=f"**ID**: {tag.entry_id}\n"
            f"**Content**: {len(tag.content):,} characters\n"
            f"**Created**: {discord.utils.format_dt(created_at, 'R')}\n"
            f"**Author**: {author.mention if author else tag.author}\n"
            f"**Owner**: {owner.mention if owner else tag.owner}\n"
            f"**Uses**: {tag.uses:,}",
            colour=discord.Colour.blurple(),
        )
        if not in_guild:
            view = ClaimTagView()
            await ctx.respond(embed=embed, view=view)
            await view.wait()
        else:
            await ctx.respond(embed=embed)


def setup(bot):
    bot.add_cog(TagsCog(bot))
