from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Awaitable, Dict, List, Optional, Union, TYPE_CHECKING

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
DEFAULT_CONFIRMATION_MESSAGE = "You have accepted {user} as a {option}."


def _fill(template: Optional[str], **values: str) -> Optional[str]:
    """Replace {placeholders} without choking on any other braces in the text."""
    if not template:
        return template
    for key, value in values.items():
        template = template.replace("{" + key + "}", value)
    return template


def _id_list(value, what: str) -> List[int]:
    """Accept None, a single ID, or a list of IDs, and always return a list of ints."""
    if value is None:
        return []
    if isinstance(value, (int, str)):
        value = [value]
    try:
        return [int(item) for item in value]
    except (TypeError, ValueError):
        raise ValueError(f"{what} must be an ID or a list of IDs like [123, 456], got {value!r}")


def _join_lines(value: Union[str, List[str], None]) -> Optional[str]:
    """Let text be written as one string or as a list of lines (joined with line breaks)."""
    if isinstance(value, (list, tuple)):
        return "\n".join(str(line) for line in value)
    return value


@dataclass
class DMConfig:
    """The embed that gets DM'd to the accepted user."""

    title: Optional[str] = None
    color: str = "#a68937"
    thumbnail_url: Optional[str] = None
    entry: Union[str, List[str], None] = None  # main body text. A list = one line per item
    footer: Optional[str] = None

    def __post_init__(self) -> None:
        self.entry = _join_lines(self.entry)
        # Fail loudly when the plugin loads instead of halfway through an accept.
        try:
            discord.Color.from_str(self.color)
        except ValueError:
            raise ValueError(f"Invalid DM embed color: {self.color!r}. Use a format like '#a68937'.")

    def build_embed(self, values: Dict[str, str]) -> Optional[discord.Embed]:
        title = _fill(self.title, **values)
        entry = _fill(self.entry, **values)
        footer = _fill(self.footer, **values)

        # Discord rejects completely empty embeds, so skip the DM if nothing is set.
        if not (title or entry or self.thumbnail_url or footer):
            return None

        embed = discord.Embed(title=title, description=entry, color=discord.Color.from_str(self.color))
        if self.thumbnail_url:
            embed.set_thumbnail(url=self.thumbnail_url)
        if footer:
            embed.set_footer(text=footer)
        return embed


@dataclass
class AcceptOption:
    """One button on the .accept panel."""

    label: str  # text on the button, also used as {option} in messages
    add_roles: List[int]  # role IDs to give
    remove_roles: List[int] = field(default_factory=list)  # role IDs to take away
    # Members with ANY of these roles may use this option. Empty = anyone who can run .accept
    allowed_roles: List[int] = field(default_factory=list)
    style: discord.ButtonStyle = discord.ButtonStyle.blurple
    # Where to announce: one channel ID, a list of IDs, or None for the channel .accept was used in
    channel_id: Union[int, List[int], None] = None
    channel_message: Union[str, List[str]] = DEFAULT_CHANNEL_MESSAGE  # a list = one line per item
    # Sent in the channel .accept was used in. A list = one line per item
    confirmation_message: Union[str, List[str]] = DEFAULT_CONFIRMATION_MESSAGE
    dm: DMConfig = field(default_factory=DMConfig)

    announce_channels: List[int] = field(init=False, repr=False, default_factory=list)

    def __post_init__(self) -> None:
        self.add_roles = _id_list(self.add_roles, f"'{self.label}' add_roles")
        self.remove_roles = _id_list(self.remove_roles, f"'{self.label}' remove_roles")
        self.allowed_roles = _id_list(self.allowed_roles, f"'{self.label}' allowed_roles")
        self.announce_channels = _id_list(self.channel_id, f"'{self.label}' channel_id")
        self.channel_message = _join_lines(self.channel_message)
        self.confirmation_message = _join_lines(self.confirmation_message)

    def can_use(self, member: discord.Member) -> bool:
        """Whether this member's roles let them use this option."""
        if not self.allowed_roles:
            return True
        return any(role.id in self.allowed_roles for role in member.roles)


# =============================================================================
#  CONFIGURATION  (edit this part)
# =============================================================================

# Who may use .accept: REGULAR, SUPPORTER, MODERATOR, ADMINISTRATOR or OWNER
REQUIRED_PERMISSION = PermissionLevel.MODERATOR

PROMPT_TIMEOUT = 300  # seconds the button panel waits for a click
NAME_TIMEOUT = 120  # seconds the bot waits for you to type the new nickname

# Placeholders you can use in channel_message, confirmation_message, and in the
# DM's title / entry / footer:
#   {user}       the accepted user
#   {option}     the button's label
#   {moderator}  whoever ran the command
#   {time}       date and time
#
# In channel_message and confirmation_message, {user} and {moderator} are mentions
# and {time} is shown in each reader's own timezone. In the DM they are plain text
# (names, and {time} in UTC) because embed titles and footers can't show mentions.
#
# MULTI-LINE TEXT
# entry, channel_message and confirmation_message can be a normal string or a
# list with one item per line (use "" for a blank line):
#     entry=["First line", "", "Third line"],
# A plain "..." string can't be split across lines in Python (pressing Enter inside
# the quotes is a syntax error). To break a line inside a single string, write \n.
# Discord formatting works in the entry, e.g. **bold**, *italic*, > quotes.
#
# PERMISSIONS
# allowed_roles: members with ANY of the listed roles may use that option, and it
# only shows up on the panel for them. Use [] to let everyone who can run .accept
# use it. This is strict: server owners and admins are not exempt unless they have
# one of the listed roles.
#
# Add one AcceptOption(...) per button (max 24, one slot is kept for Cancel).
# Copy a block to add another.
# To find a role ID: Discord Settings > Advanced > Developer Mode, then
# right-click the role in Server Settings > Roles > Copy Role ID.
OPTIONS: List[AcceptOption] = [
    AcceptOption(
        label="Hangaround",
        style=discord.ButtonStyle.green,
        allowed_roles=[1506363617082343424, 1506363618223198228],  # <- REPLACE. Who can use this option 
        add_roles=[1506363634861998181, 1506363674032476261],  # <- REPLACE with your role IDs
        remove_roles=[1506363671637393449],  # <- REPLACE (or use [] to remove nothing)
        channel_id=[1506363845382246470],  # None = same channel the command was used in
        channel_message="{user} has been given {option} roles by {moderator}.\n{time}",
        confirmation_message="You have accepted {user} as a {option}.",
        dm=DMConfig(
            title="Welcome!",
            color="#a68937",
            thumbnail_url="https://cdn.discordapp.com/attachments/1506363914550771742/1556464154146242642/2.png",
            entry="You have been accepted as a hangaround. Watch and learn.",
            footer="Accepted by {moderator} on {time}",
        ),
    ),
    AcceptOption(
        label="Prospect",
        style=discord.ButtonStyle.green,
        allowed_roles=[1506363617082343424, 1506363618223198228],  # <- REPLACE. Who can use this option
        add_roles=[1506363625273823463],  # <- REPLACE with your role IDs
        remove_roles=[1506363634861998181],  # <- REPLACE (or use [] to remove nothing)
        channel_id=[1506363845382246470],  # None = same channel the command was used in
        channel_message="{user} has been given {option} roles by {moderator}.\n{time}",
        confirmation_message="You have accepted {user} as a {option}.",
        dm=DMConfig(
            title="Welcome!",
            color="#a68937",
            thumbnail_url="https://cdn.discordapp.com/attachments/1506363914550771742/1556464154146242642/2.png",
            entry=["Congratulations on becoming a prospect. This is the last nice thing you will be told.", 
            "Your whole job as a prospect is to do whatever a patched member tells you to do.",
            "You need to read our bylaws in <#1506363869595959477>.",
            "Ignorance is not acceptable.",
            "Also if you know nothing about the Motorcycle Club Community, ASK.",
            "Last but never least, **Never miss a chance to shut the fuck up.**",
            "You will sign this now. https://forms.gle/x8q5ajUmn6AwiKfr7",
            "Your sponsor is {moderator}.",
            ],
            footer="Accepted by {moderator} on {time}",
        ),
    ),
    AcceptOption(
            label="Visitor",
            style=discord.ButtonStyle.green,
            allowed_roles=[1506363617082343424, 1506363618223198228],  # <- REPLACE. Who can use this option
            add_roles=[1506363635738611722, 1506363674032476261],  # <- REPLACE with your role IDs
            remove_roles=[1506363671637393449],  # <- REPLACE (or use [] to remove nothing)
            channel_id=[1506363845382246470],  # None = same channel the command was used in
            channel_message="{user} has been given {option} roles by {moderator}.\n{time}",
            confirmation_message="You have accepted {user} as a {option}.",
            dm=DMConfig(
                title="Welcome!",
                color="#a68937",
                thumbnail_url="https://cdn.discordapp.com/attachments/1506363914550771742/1556464154146242642/2.png",
                entry="You have been given access to limited access. Enjoy what you can.",
                footer="Accepted by {moderator} on {time}",
            ),
        ),
    AcceptOption(
            label="Club Friend",
            style=discord.ButtonStyle.green,
            allowed_roles=[1506363617082343424, 1506363618223198228],  # <- REPLACE. Who can use this option            
            add_roles=[1506363635738611722, 1506363631460290620],  # <- REPLACE with your role IDs
            remove_roles=[1506363671637393449],  # <- REPLACE (or use [] to remove nothing)
            channel_id=[1506363845382246470],  # None = same channel the command was used in
            channel_message="{user} has been given {option} roles by {moderator}.\n{time}",
            confirmation_message="You have accepted {user} as a {option}.",
            dm=DMConfig(
                title="Welcome!",
                color="#a68937",
                thumbnail_url="https://cdn.discordapp.com/attachments/1506363914550771742/1556464154146242642/2.png",
                entry="You have been given access to server. ",
                footer="Accepted by {moderator} on {time}",
            ),
        ),
    AcceptOption(
            label="Allied Club",
            style=discord.ButtonStyle.green,
            allowed_roles=[1506363617082343424],  # <- REPLACE. Who can use this option 
            add_roles=[1506363629992284263, 1506363635738611722],  # <- REPLACE with your role IDs
            remove_roles=[1506363671637393449],  # <- REPLACE (or use [] to remove nothing)
            channel_id=[1506363845382246470],  # None = same channel the command was used in
            channel_message="{user} has been given {option} roles by {moderator}.\n{time}",
            confirmation_message="You have accepted {user} as a {option}.",
            dm=DMConfig(
                title="Welcome!",
                color="#a68937",
                thumbnail_url="https://cdn.discordapp.com/attachments/1506363914550771742/1556464154146242642/2.png",
                entry="You have been accepted as a Member. Enjoy your stay!",
                footer="Accepted by {moderator} on {time}",
            ),
        ),
]


# =============================================================================
#  BUTTON PANELS
# =============================================================================


class PanelView(discord.ui.View):
    """Base view: only the person who ran the command may use it."""

    def __init__(self, ctx: commands.Context, *, timeout: Optional[float]):
        super().__init__(timeout=timeout)
        self.ctx = ctx
        self.cancelled: bool = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.ctx.author.id:
            return True
        await interaction.response.send_message("This panel cannot be controlled by you!", ephemeral=True)
        return False


class CancelButton(discord.ui.Button["PanelView"]):
    def __init__(self):
        super().__init__(label="Cancel", style=discord.ButtonStyle.red)

    async def callback(self, interaction: discord.Interaction) -> None:
        assert self.view is not None
        await interaction.response.defer()
        self.view.cancelled = True
        self.view.stop()


class OptionButton(discord.ui.Button["AcceptView"]):
    def __init__(self, option: AcceptOption):
        super().__init__(label=option.label, style=option.style)
        self.option = option

    async def callback(self, interaction: discord.Interaction) -> None:
        assert self.view is not None
        await interaction.response.defer()
        self.view.selected = self.option
        self.view.stop()


class AcceptView(PanelView):
    def __init__(self, ctx: commands.Context, options: List[AcceptOption], *, timeout: float):
        super().__init__(ctx, timeout=timeout)
        self.selected: Optional[AcceptOption] = None
        for option in options:
            self.add_item(OptionButton(option))
        self.add_item(CancelButton())


# =============================================================================
#  COG
# =============================================================================


class Accept(commands.Cog):
    """Accept a user: give/remove roles, DM them, announce it and rename them."""

    def __init__(self, bot: ModmailBot):
        self.bot: ModmailBot = bot

    @commands.command()
    @checks.has_permissions(REQUIRED_PERMISSION)
    @commands.guild_only()
    async def accept(self, ctx: commands.Context, member: discord.Member):
        """
        Accept a user by picking an option, which gives/removes roles, DMs them and announces it.

        Which options you are offered depends on your roles.
        After picking, you will be asked what the user should be nicknamed.
        The panel, the command, and the nickname prompt are all cleaned up afterwards,
        and a confirmation is posted in the channel you used the command in.

        If any step fails, a message listing exactly what went wrong stays in the channel.

        `member` may be a user ID, mention, or name.
        """
        if not OPTIONS:
            embed = discord.Embed(
                description="No accept options are configured in the plugin script.",
                color=self.bot.error_color,
            )
            return await ctx.send(embed=embed)

        # Only offer the options this person's roles allow
        options = [option for option in OPTIONS if option.can_use(ctx.author)]
        if not options:
            embed = discord.Embed(
                description="You don't have the roles required to accept anyone to any option.",
                color=self.bot.error_color,
            )
            return await ctx.send(embed=embed, delete_after=15)

        # 1. Ask which option to use
        view = AcceptView(ctx, options, timeout=PROMPT_TIMEOUT)
        prompt = await ctx.send(
            f"What are you accepting {member.mention} to?",
            view=view,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        await view.wait()

        option = view.selected
        if option is None:  # cancelled, or nobody clicked in time
            await self._delete(prompt, ctx.message)
            outcome = "cancelled" if view.cancelled else "timed out"
            await ctx.send(
                f"Accepting {member.mention} {outcome}.",
                delete_after=10,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return

        now = discord.utils.utcnow()
        rich = {  # for normal messages: real mentions and a timestamp that adapts to the reader
            "user": member.mention,
            "option": option.label,
            "moderator": ctx.author.mention,
            "time": discord.utils.format_dt(now, style="F"),
        }
        plain = {  # for embed titles/footers, which can't render mentions or timestamps
            "user": member.display_name,
            "option": option.label,
            "moderator": ctx.author.display_name,
            "time": now.strftime("%d %b %Y, %H:%M UTC"),
        }

        # 2. Roles, DM and channel announcement. Each step runs on its own, so
        #    one failing can never stop the others.
        problems: List[str] = []
        await self._run(problems, "Changing roles", self._apply_roles(ctx, member, option, problems))
        await self._run(problems, "Sending the DM", self._send_dm(member, option, plain, problems))
        await self._run(problems, "Posting the announcement", self._announce(ctx, member, option, rich, problems))

        # 3. Clear the panel and the command, and show anything that went wrong
        await self._delete(prompt, ctx.message)
        await self._report(ctx, problems)

        # 4. Ask for a nickname and apply it
        await self._run(problems, "Renaming", self._ask_and_set_nickname(ctx, member, problems))

        # 5. Confirmation in the channel the command was used in
        await self._run(problems, "Sending the confirmation", self._confirm(ctx, option, rich))
        await self._report(ctx, problems)

    # ------------------------------------------------------------------ helpers

    async def _run(self, problems: List[str], name: str, step: Awaitable[None]) -> None:
        """Run one step. If it blows up, log it and record it instead of aborting the command."""
        try:
            await step
        except Exception as exc:
            logger.exception(f"Accept: step '{name}' failed")
            problems.append(f"**{name}** failed: `{type(exc).__name__}: {exc}`")

    async def _report(self, ctx: commands.Context, problems: List[str]) -> None:
        if not problems:
            return
        embed = discord.Embed(
            title="Something didn't go as planned",
            description="\n".join(f"- {problem}" for problem in problems),
            color=self.bot.error_color,
        )
        problems.clear()
        await ctx.send(embed=embed)

    @staticmethod
    async def _delete(*messages: discord.Message) -> None:
        for message in messages:
            try:
                await message.delete()
            except discord.HTTPException as exc:
                logger.warning(f"Could not delete message {message.id}: {exc}")

    async def _apply_roles(
        self,
        ctx: commands.Context,
        member: discord.Member,
        option: AcceptOption,
        problems: List[str],
    ) -> None:
        guild = ctx.guild

        def resolve(role_ids: List[int]) -> List[discord.Role]:
            roles = []
            for role_id in role_ids:
                role = guild.get_role(role_id)
                if role is None:
                    problems.append(f"Role ID `{role_id}` doesn't exist in this server.")
                else:
                    roles.append(role)
            return roles

        to_add = resolve(option.add_roles)
        to_remove = resolve(option.remove_roles)

        if (to_add or to_remove) and not guild.me.guild_permissions.manage_roles:
            problems.append("I don't have the **Manage Roles** permission, so no roles were changed.")
            return

        reason = f"Accepted to {option.label} by {ctx.author} ({ctx.author.id})"

        # Every role is handled on its own so one bad role can't block the rest.
        for role in to_add:
            await self._change_role(member, role, add=True, reason=reason, problems=problems)
        for role in to_remove:
            await self._change_role(member, role, add=False, reason=reason, problems=problems)

    @staticmethod
    async def _change_role(
        member: discord.Member,
        role: discord.Role,
        *,
        add: bool,
        reason: str,
        problems: List[str],
    ) -> None:
        verb = "give" if add else "remove"
        top_role = member.guild.me.top_role

        if role.managed:
            problems.append(f"Can't {verb} {role.mention}: it is managed by an integration or bot.")
            return
        if role >= top_role:
            problems.append(
                f"Can't {verb} {role.mention}: it is at or above my highest role ({top_role.mention}). "
                "Move my role above it in Server Settings > Roles."
            )
            return

        # Not filtered against member.roles on purpose: the cache can be stale, and
        # removing a role the member doesn't have is harmless.
        try:
            if add:
                await member.add_roles(role, reason=reason)
            else:
                await member.remove_roles(role, reason=reason)
        except discord.HTTPException as exc:
            problems.append(f"Couldn't {verb} {role.mention}: {exc}")
            return
        logger.info(f"Accept: {verb} {role.name} ({role.id}) for {member} ({member.id})")

    async def _send_dm(
        self,
        member: discord.Member,
        option: AcceptOption,
        values: Dict[str, str],
        problems: List[str],
    ) -> None:
        embed = option.dm.build_embed(values)
        if embed is None:
            return
        try:
            await member.send(embed=embed)
        except discord.Forbidden:
            problems.append(f"Couldn't DM {member.mention}: their DMs are closed (or they blocked the bot).")
        except discord.HTTPException as exc:
            problems.append(f"Couldn't DM {member.mention}: {exc}")

    async def _announce(
        self,
        ctx: commands.Context,
        member: discord.Member,
        option: AcceptOption,
        values: Dict[str, str],
        problems: List[str],
    ) -> None:
        text = _fill(option.channel_message, **values)
        if not text:
            return

        channels = []
        for channel_id in option.announce_channels:
            channel = ctx.guild.get_channel_or_thread(channel_id)
            if isinstance(channel, discord.abc.Messageable):
                channels.append(channel)
            else:
                problems.append(f"Channel ID `{channel_id}` wasn't found or isn't a text channel.")
        if not channels:  # nothing configured (or nothing valid): use the current channel
            channels = [ctx.channel]

        for channel in channels:
            try:
                # Only the accepted user gets pinged, not the moderator.
                await channel.send(text, allowed_mentions=discord.AllowedMentions(users=[member]))
            except discord.HTTPException as exc:
                problems.append(f"Couldn't send the announcement in {channel.mention}: {exc}")

    async def _confirm(self, ctx: commands.Context, option: AcceptOption, values: Dict[str, str]) -> None:
        text = _fill(option.confirmation_message, **values)
        if text:
            await ctx.send(text, allowed_mentions=discord.AllowedMentions.none())

    async def _ask_and_set_nickname(
        self,
        ctx: commands.Context,
        member: discord.Member,
        problems: List[str],
    ) -> None:
        view = PanelView(ctx, timeout=None)  # we handle the timeout ourselves below
        view.add_item(CancelButton())
        prompt = await ctx.send(
            f"What will {member.mention} be named?",
            view=view,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        cleanup: List[discord.Message] = [prompt]

        def check(message: discord.Message) -> bool:
            return message.author.id == ctx.author.id and message.channel.id == ctx.channel.id

        nickname: Optional[str] = None
        cancel_task = asyncio.ensure_future(view.wait())
        reply_task: Optional[asyncio.Future] = None
        try:
            while nickname is None:
                # Wait for either a typed reply or a click on Cancel, whichever comes first.
                reply_task = asyncio.ensure_future(self.bot.wait_for("message", check=check))
                done, _ = await asyncio.wait(
                    {reply_task, cancel_task},
                    timeout=NAME_TIMEOUT,
                    return_when=asyncio.FIRST_COMPLETED,
                )

                reply = reply_task.result() if reply_task in done else None
                if reply is not None:
                    cleanup.append(reply)

                if view.cancelled:
                    break
                if reply is None:
                    problems.append("No name was given in time, so the nickname was left unchanged.")
                    break

                name = reply.content.strip()
                if not name:
                    continue
                if len(name) > 32:
                    cleanup.append(
                        await ctx.send(f"Nicknames can be at most 32 characters ({len(name)} given). Try again.")
                    )
                    continue
                nickname = name
        finally:
            if reply_task is not None and not reply_task.done():
                reply_task.cancel()
            cancel_task.cancel()
            view.stop()

        if nickname:
            try:
                await member.edit(nick=nickname, reason=f"Accepted by {ctx.author} ({ctx.author.id})")
            except discord.HTTPException as exc:
                problems.append(
                    f"Couldn't rename {member.mention}: {exc} "
                    "(I need **Manage Nicknames**, and my top role must be above theirs. "
                    "I can't rename the server owner.)"
                )

        await self._delete(*cleanup)


async def setup(bot: ModmailBot) -> None:
    if len(OPTIONS) > 24:
        raise ValueError("Discord allows 25 buttons per message and one is used for Cancel; use 24 options or fewer.")
    await bot.add_cog(Accept(bot))
