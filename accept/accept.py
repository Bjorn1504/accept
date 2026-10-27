from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import List, Optional, TYPE_CHECKING

import discord
from discord.ext import commands

from core import checks
from core.models import PermissionLevel, getLogger

if TYPE_CHECKING:
    from bot import ModmailBot


logger = getLogger(__name__)


# =============================================================================
#  CONFIG CLASSES  (you don't need to edit this part)
# =============================================================================

DEFAULT_CHANNEL_MESSAGE = "{user} has been given {option} roles by {moderator}.\n{time}"


@dataclass
class DMConfig:
    """The embed that gets DM'd to the accepted user."""

    title: Optional[str] = None
    color: str = "#a68937"
    thumbnail_url: Optional[str] = None
    entry: Optional[str] = None  # the main body text of the embed
    footer: Optional[str] = None

    def __post_init__(self) -> None:
        # Fail loudly when the plugin loads instead of halfway through an accept.
        try:
            discord.Color.from_str(self.color)
        except ValueError:
            raise ValueError(f"Invalid DM embed color: {self.color!r}. Use a format like '#a68937'.")

    def build_embed(self) -> Optional[discord.Embed]:
        # Discord rejects completely empty embeds, so skip the DM if nothing is set.
        if not (self.title or self.entry or self.thumbnail_url or self.footer):
            return None
        embed = discord.Embed(
            title=self.title,
            description=self.entry,
            color=discord.Color.from_str(self.color),
        )
        if self.thumbnail_url:
            embed.set_thumbnail(url=self.thumbnail_url)
        if self.footer:
            embed.set_footer(text=self.footer)
        return embed


@dataclass
class AcceptOption:
    """One button on the .accept panel."""

    label: str  # text on the button, also used as {option} in the channel message
    add_roles: List[int]  # role IDs to give
    remove_roles: List[int] = field(default_factory=list)  # role IDs to take away
    style: discord.ButtonStyle = discord.ButtonStyle.blurple
    channel_id: Optional[int] = None  # where to announce. None = the channel .accept was used in
    channel_message: str = DEFAULT_CHANNEL_MESSAGE
    dm: DMConfig = field(default_factory=DMConfig)


# =============================================================================
#  CONFIGURATION  (edit this part)
# =============================================================================

# Who may use .accept: REGULAR, SUPPORTER, MODERATOR, ADMINISTRATOR or OWNER
REQUIRED_PERMISSION = PermissionLevel.MODERATOR

PROMPT_TIMEOUT = 300  # seconds the button panel waits for a click
NAME_TIMEOUT = 120  # seconds the bot waits for you to type the new nickname

# Channel message placeholders:
#   {user}       mention of the accepted user
#   {option}     the button's label
#   {moderator}  mention of whoever ran the command
#   {time}       date and time (shown in each reader's own timezone)
#   {nickname}   the nickname that was set
#
# Add one AcceptOption(...) per button (max 25). Copy a block to add another.
# To find a role ID: Discord Settings > Advanced > Developer Mode, then
# right-click the role in Server Settings > Roles > Copy Role ID.
OPTIONS: List[AcceptOption] = [
    AcceptOption(
        label="Hangaround",
        style=discord.ButtonStyle.green,
        add_roles=[1506363634861998181, 1506363674032476261],  # <- REPLACE with your role IDs
        remove_roles=[1506363671637393449],  # <- REPLACE (or use [] to remove nothing)
        channel_id=[1506363845382246470],  # None = same channel the command was used in
        channel_message="{user} has been given {option} roles by {moderator}.\n{time}",
        dm=DMConfig(
            title="Welcome!",
            color="#a68937",
            thumbnail_url=None,
            entry="You have been accepted as a hangaround. Watch and learn.",
            footer="Club Officer",
        ),
    ),
    AcceptOption(
        label="Prospect",
        style=discord.ButtonStyle.green,
        add_roles=[1506363625273823463],  # <- REPLACE with your role IDs
        remove_roles=[1506363671637393449],  # <- REPLACE (or use [] to remove nothing)
        channel_id=[1506363845382246470],  # None = same channel the command was used in
        channel_message="{user} has been given {option} roles by {moderator}.\n{time}",
        dm=DMConfig(
            title="Welcome!",
            color="#a68937",
            thumbnail_url=None,
            entry="Congratulations on becoming a prospect. This is the last nice thing you will be told. Your whole job as a prospect is to do whatever a patched member tells you to do. You need to read our bylaws in <#1506363869595959477>. Ignorance is not acceptable. Also if you know nothing about the Motorcycle Club Community, ASK. Last but never least, **Never miss a chance to shut the fuck up.** You will sign this now. https://forms.gle/x8q5ajUmn6AwiKfr7 Your sponsor is {moderator}.",
            footer="Club Officer",
        ),
    ),
    AcceptOption(
            label="Visitor",
            style=discord.ButtonStyle.green,
            add_roles=[1506363635738611722, 1506363674032476261],  # <- REPLACE with your role IDs
            remove_roles=[1506363671637393449],  # <- REPLACE (or use [] to remove nothing)
            channel_id=[1506363845382246470],  # None = same channel the command was used in
            channel_message="{user} has been given {option} roles by {moderator}.\n{time}",
            dm=DMConfig(
                title="Welcome!",
                color="#a68937",
                thumbnail_url=None,
                entry="You have been given access to limited access. Enjoy what you can.",
                footer="Club Officer",
            ),
        ),
    AcceptOption(
            label="Club Friend",
            style=discord.ButtonStyle.green,
            add_roles=[1506363635738611722, 1506363631460290620],  # <- REPLACE with your role IDs
            remove_roles=[1506363671637393449],  # <- REPLACE (or use [] to remove nothing)
            channel_id=[1506363845382246470],  # None = same channel the command was used in
            channel_message="{user} has been given {option} roles by {moderator}.\n{time}",
            dm=DMConfig(
                title="Welcome!",
                color="#a68937",
                thumbnail_url=None,
                entry="You have been given access to server. ",
                footer="Club Officer",
            ),
        ),
    AcceptOption(
            label="Allied Club",
            style=discord.ButtonStyle.green,
            add_roles=[1506363629992284263, 1506363635738611722],  # <- REPLACE with your role IDs
            remove_roles=[1506363671637393449],  # <- REPLACE (or use [] to remove nothing)
            channel_id=[1506363845382246470],  # None = same channel the command was used in
            channel_message="{user} has been given {option} roles by {moderator}.\n{time}",
            dm=DMConfig(
                title="Welcome!",
                color="#a68937",
                thumbnail_url=None,
                entry="You have been accepted as a Member. Enjoy your stay!",
                footer="Club Officer",
            ),
        ),
]


# =============================================================================
#  BUTTON PANEL
# =============================================================================


class OptionButton(discord.ui.Button["AcceptView"]):
    def __init__(self, option: AcceptOption):
        super().__init__(label=option.label, style=option.style)
        self.option = option

    async def callback(self, interaction: discord.Interaction) -> None:
        assert self.view is not None
        await interaction.response.defer()
        self.view.selected = self.option
        self.view.stop()


class AcceptView(discord.ui.View):
    def __init__(self, ctx: commands.Context, options: List[AcceptOption], *, timeout: float):
        super().__init__(timeout=timeout)
        self.ctx = ctx
        self.selected: Optional[AcceptOption] = None
        for option in options:
            self.add_item(OptionButton(option))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.ctx.author.id:
            return True
        await interaction.response.send_message("This panel cannot be controlled by you!", ephemeral=True)
        return False


# =============================================================================
#  COG
# =============================================================================


def _fill(template: str, **values: str) -> str:
    """Replace {placeholders} without choking on any other braces in the text."""
    for key, value in values.items():
        template = template.replace("{" + key + "}", value)
    return template


class Accept(commands.Cog):
    """Accept a user: give/remove roles, DM them, rename them and announce it."""

    def __init__(self, bot: ModmailBot):
        self.bot: ModmailBot = bot

    @commands.command()
    @checks.has_permissions(REQUIRED_PERMISSION)
    @commands.guild_only()
    async def accept(self, ctx: commands.Context, member: discord.Member):
        """
        Accept a user by picking an option, which gives/removes roles and DMs them.

        After picking, you will be asked what the user should be nicknamed.
        The panel, the command, and the nickname prompt are all cleaned up afterwards.

        `member` may be a user ID, mention, or name.
        """
        if not OPTIONS:
            return await self._warn(ctx, "No accept options are configured in the plugin script.")

        # 1. Ask which option to use
        view = AcceptView(ctx, OPTIONS, timeout=PROMPT_TIMEOUT)
        prompt = await ctx.send(
            f"What are you accepting {member.mention} to?",
            view=view,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        await view.wait()

        option = view.selected
        if option is None:  # nobody clicked in time
            await self._delete(prompt, ctx.message)
            await ctx.send(
                f"Accepting {member.mention} timed out.",
                delete_after=10,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return

        # 2. Roles + DM, then clear the panel and the command
        await self._apply_roles(ctx, member, option)
        await self._send_dm(ctx, member, option)
        await self._delete(prompt, ctx.message)

        # 3. Ask for a nickname, apply it, clear those messages
        nickname = await self._ask_and_set_nickname(ctx, member)

        # 4. Announce
        await self._announce(ctx, member, option, nickname)

    # ------------------------------------------------------------------ helpers

    async def _warn(self, ctx: commands.Context, text: str) -> None:
        logger.warning(text)
        embed = discord.Embed(description=text, color=self.bot.error_color)
        await ctx.send(embed=embed, delete_after=20)

    @staticmethod
    async def _delete(*messages: discord.Message) -> None:
        for message in messages:
            try:
                await message.delete()
            except discord.HTTPException as exc:
                logger.warning(f"Could not delete message {message.id}: {exc}")

    async def _apply_roles(self, ctx: commands.Context, member: discord.Member, option: AcceptOption) -> None:
        guild = ctx.guild
        to_add, to_remove, missing = [], [], []

        for role_id in option.add_roles:
            role = guild.get_role(role_id)
            if role is None:
                missing.append(role_id)
            elif role not in member.roles:
                to_add.append(role)

        for role_id in option.remove_roles:
            role = guild.get_role(role_id)
            if role is None:
                missing.append(role_id)
            elif role in member.roles:
                to_remove.append(role)

        reason = f"Accepted to {option.label} by {ctx.author} ({ctx.author.id})"
        try:
            if to_add:
                await member.add_roles(*to_add, reason=reason)
            if to_remove:
                await member.remove_roles(*to_remove, reason=reason)
        except discord.Forbidden:
            await self._warn(
                ctx,
                "I couldn't change the roles. I need the `Manage Roles` permission, "
                "and my top role must be above the roles I'm giving/removing.",
            )
        except discord.HTTPException as exc:
            await self._warn(ctx, f"Failed to update roles: {exc}")

        if missing:
            ids = ", ".join(f"`{i}`" for i in missing)
            await self._warn(ctx, f"These role IDs were not found in this server: {ids}")

    async def _send_dm(self, ctx: commands.Context, member: discord.Member, option: AcceptOption) -> None:
        embed = option.dm.build_embed()
        if embed is None:
            return
        try:
            await member.send(embed=embed)
        except discord.Forbidden:
            await self._warn(ctx, f"I couldn't DM {member.mention} (their DMs are closed).")
        except discord.HTTPException as exc:
            await self._warn(ctx, f"Failed to DM {member.mention}: {exc}")

    async def _ask_and_set_nickname(self, ctx: commands.Context, member: discord.Member) -> Optional[str]:
        prompt = await ctx.send(
            f"What will {member.mention} be named?",
            allowed_mentions=discord.AllowedMentions.none(),
        )
        cleanup: List[discord.Message] = [prompt]

        def check(message: discord.Message) -> bool:
            return message.author.id == ctx.author.id and message.channel.id == ctx.channel.id

        nickname: Optional[str] = None
        try:
            while nickname is None:
                reply = await self.bot.wait_for("message", check=check, timeout=NAME_TIMEOUT)
                cleanup.append(reply)
                name = reply.content.strip()
                if not name:
                    continue
                if len(name) > 32:
                    cleanup.append(
                        await ctx.send(f"Nicknames can be at most 32 characters ({len(name)} given). Try again.")
                    )
                    continue
                nickname = name
        except asyncio.TimeoutError:
            await self._warn(ctx, "No name was given in time, so the nickname was left unchanged.")

        if nickname:
            try:
                await member.edit(nick=nickname, reason=f"Accepted by {ctx.author} ({ctx.author.id})")
            except discord.Forbidden:
                await self._warn(
                    ctx,
                    f"I couldn't rename {member.mention}. I need the `Manage Nicknames` permission, "
                    "and my top role must be above theirs (I also can't rename the server owner).",
                )
                nickname = None
            except discord.HTTPException as exc:
                await self._warn(ctx, f"Failed to rename {member.mention}: {exc}")
                nickname = None

        await self._delete(*cleanup)
        return nickname

    async def _announce(
        self,
        ctx: commands.Context,
        member: discord.Member,
        option: AcceptOption,
        nickname: Optional[str],
    ) -> None:
        channel = ctx.guild.get_channel(option.channel_id) if option.channel_id else None
        if not isinstance(channel, discord.abc.Messageable):
            channel = ctx.channel

        text = _fill(
            option.channel_message,
            user=member.mention,
            option=option.label,
            moderator=ctx.author.mention,
            time=discord.utils.format_dt(discord.utils.utcnow(), style="F"),
            nickname=nickname or member.display_name,
        )
        try:
            # Only the accepted user gets pinged, not the moderator.
            await channel.send(text, allowed_mentions=discord.AllowedMentions(users=[member]))
        except discord.HTTPException as exc:
            await self._warn(ctx, f"I couldn't send the announcement: {exc}")


async def setup(bot: ModmailBot) -> None:
    if len(OPTIONS) > 25:
        raise ValueError("Discord only allows 25 buttons on a message; reduce OPTIONS to 25 or fewer.")
    await bot.add_cog(Accept(bot))
