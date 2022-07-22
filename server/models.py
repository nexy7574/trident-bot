import datetime

from pydantic import BaseModel


__all__ = (
    "User",
    "PartialGuild",
    "Guild",
    "RoleTags",
    "Role",
    "Emoji",
    "WelcomeScreenChannel",
    "WelcomeScreen",
    "Sticker",
    "Guild",
    "TicketQuestion",
    "GuildConfig",
)


class User(BaseModel):
    id: str
    username: str
    discriminator: str
    avatar: str | None
    bot: bool = False
    system: bool = False
    mfa_enabled: bool = False
    banner: str | None = None
    accent_color: str | None = None
    locale: str = None
    flags: int = None
    premium_type: int = None
    public_flags: int = None


class PartialGuild(BaseModel):
    id: str
    """Snowflake ID of the guild"""

    name: str
    """The name of the guild"""

    icon: str | None
    """The icon hash of the guild"""

    owner: bool
    """Whether the currently authenticated user owns this guild"""

    permissions: str
    """The permissions bits for this user"""

    features: list[str]
    """A list of features for the server"""


class RoleTags(BaseModel):
    bot_id: str | None = None
    integration_id: str | None = None
    premium_subscriber: None = None  # what


class Role(BaseModel):
    id: str
    name: str
    color: int
    hoist: bool
    icon: str | None = None
    unicode_emoji: str | None = None
    position: int
    permissions: str
    managed: bool
    mentionable: bool
    tags: RoleTags | None = None


class Emoji(BaseModel):
    id: str | None
    name: str | None
    roles: list[Role] | None = []
    user: User | None = None
    require_colons: bool | None = None
    managed: bool | None = None
    animated: bool | None = None
    available: bool | None = None


class WelcomeScreenChannel(BaseModel):
    channel_id: str
    description: str
    emoji_id: str | None
    emoji_name: str | None


class WelcomeScreen(BaseModel):
    description: str | None
    welcome_channels: list[WelcomeScreenChannel]


class Sticker(BaseModel):
    id: str
    pack_id: str | None = None
    name: str
    description: str | None
    tags: str
    asset: str | None = None
    type: int
    format_type: int
    available: bool | None = None
    guild_id: str | None = None
    user: User | None = None
    sort_value: int | None = None


class Guild(BaseModel):
    id: str
    name: str
    icon: str | None
    icon_hash: str | None = None
    splash: str | None
    discovery_splash: str | None
    owner: bool | None = None
    owner_id: str
    permissions: str | None = None
    region: str | None = None
    afk_channel_id: str | None
    afk_timeout: int
    widget_enabled: bool | None = None
    widget_channel_id: str | None = None
    verification_level: int
    default_message_notifications: int
    explicit_content_filter: int
    roles: list[Role]
    emojis: list[Emoji]
    features: list[str]
    mfa_level: int
    application_id: str | None
    system_channel_id: str | None
    system_channel_flags: int
    rules_channel_id: str | None
    max_presences: int | None = None
    max_members: int | None = None
    vanity_url_code: str | None
    description: str | None
    banner: str | None
    premium_tier: int
    premium_subscription_count: int | None = None
    preferred_locale: str
    public_updates_channel_id: str | None
    max_video_channel_users: int | None = None
    approximate_member_count: int | None = None
    approximate_presence_count: int | None = None
    welcome_screen: WelcomeScreen | None = None
    nsfw_level: int
    stickers: list[Sticker] | None = None
    premium_progress_bar_enabled: bool


class TicketQuestion(BaseModel):
    label: str
    placeholder: str
    min_length: int
    max_length: int
    required: bool


class GuildConfig(BaseModel):
    entry_id: int
    id: str
    ticketCounter: int
    ticketCategory: str | None
    logChannel: str | None
    supportRoles: list[str]
    pingSupportRoles: bool
    maxTickets: int
    supportEnabled: bool
    questions: list[TicketQuestion]


class Ticket(BaseModel):
    id: str
    localID: int
    guild: GuildConfig
    author: str
    channel: str
    subject: str | None
    openedAt: datetime.datetime
    locked: bool


class Tag(BaseModel):
    id: str
    name: str
    guild: GuildConfig
    content: str
    author: str
    owner: str
    uses: int
