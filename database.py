import datetime
import uuid
import secrets
from functools import partial
from typing import TYPE_CHECKING, Optional, List

import databases
import discord.utils
import orm

registry = orm.ModelRegistry(databases.Database("sqlite:///main.db"))


if TYPE_CHECKING:

    class Question(dict):
        label: str
        placeholder: Optional[str]
        min_length: Optional[int]
        max_length: Optional[int]
        required: bool

else:

    class Question(dict):
        ...


class Guild(orm.Model):
    tablename = "guilds"
    registry = registry
    fields = {
        "entry_id": orm.Integer(primary_key=True),
        "id": orm.BigInteger(unique=True),
        "ticketCounter": orm.BigInteger(default=1),
        "ticketCategory": orm.BigInteger(default=None),
        "logChannel": orm.BigInteger(default=None, unique=True),
        "supportRoles": orm.JSON(default=[]),  # list of role IDs
        "pingSupportRoles": orm.Boolean(default=True),
        "maxTickets": orm.Integer(default=50),
        "supportEnabled": orm.Boolean(default=True),
        "questions": orm.JSON(
            default=[
                {
                    "label": "Why are you opening this ticket?",
                    "placeholder": "thing X is supposed to do Y, but it does Z instead.",
                    "min_length": 2,
                    "max_length": 600,
                    "required": True,
                }
            ]
        ),
    }

    if TYPE_CHECKING:

        entry_id: int
        id: int
        ticketCounter: int
        ticketCategory: Optional[int]
        logChannel: Optional[int]
        supportRoles: List[int]
        pingSupportRoles: bool
        maxTickets: int
        supportEnabled: bool
        questions: List[Question]


class Ticket(orm.Model):
    tablename = "tickets"
    registry = registry
    fields = {
        "id": orm.BigInteger(primary_key=True, default=discord.utils.generate_snowflake),
        "localID": orm.Integer(),
        "guild": orm.ForeignKey(Guild, on_delete="CASCADE"),
        "author": orm.BigInteger(),
        "channel": orm.BigInteger(unique=True),
        "subject": orm.Text(default=None),
        "openedAt": orm.DateTime(),
        "locked": orm.Boolean(default=False),
    }

    if TYPE_CHECKING:
        id: int
        localID: int
        guild: Guild
        author: int
        channel: int
        subject: Optional[str]
        openedAt: datetime.datetime
        locked: bool


class Tag(orm.Model):
    tablename = "tags"
    registry = registry
    fields = {
        "id": orm.BigInteger(primary_key=True, default=discord.utils.generate_snowflake),
        "name": orm.Text(),
        "guild": orm.ForeignKey(Guild, on_delete="CASCADE"),
        "content": orm.Text(),
        "author": orm.BigInteger(),
        "owner": orm.BigInteger(),
        "uses": orm.Integer(default=0),
    }

    if TYPE_CHECKING:
        id: int
        name: str
        guild: Guild
        content: str
        author: int
        owner: int
        uses: int


class Token(orm.Model):
    tablename = "tokens"
    registry = registry
    fields = {
        "entry_id": orm.UUID(primary_key=True, default=uuid.uuid4),
        "user_id": orm.BigInteger(),
        "access_token": orm.Text(default=None, allow_null=True),
        "refresh_token": orm.Text(default=None, allow_null=True),
        "session": orm.Text(default=None, allow_null=True),
        "scope": orm.Text(default=None, allow_null=True),
    }

    if TYPE_CHECKING:
        entry_id: uuid.UUID
        user_id: int
        access_token: Optional[str]
        refresh_token: Optional[str]
        session: Optional[str]
        scope: Optional[str]


class APIToken(orm.Model):
    tablename = "apitokens"
    registry = registry
    fields = {
        "token": orm.Text(primary_key=True, default=partial(secrets.token_hex, 128)),
        "owner": orm.BigInteger(unique=True),
        "enabled": orm.Boolean(default=True),
    }
    if TYPE_CHECKING:
        token: str
        owner: int
        enabled: bool
