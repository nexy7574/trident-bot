import databases
import discord.utils
import orm

registry = orm.ModelRegistry(databases.Database("sqlite:///main.db"))


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
    }


class Ticket(orm.Model):
    tablename = "tickets"
    registry = registry
    fields = {
        "id": orm.BigInteger(primary_key=True, default=discord.utils.generate_snowflake),
        "localID": orm.BigInteger(),
        "guild": orm.ForeignKey(Guild, on_delete="CASCADE"),
        "author": orm.BigInteger(),
        "channel": orm.BigInteger(unique=True),
        "subject": orm.Text(default=None),
        "openedAt": orm.DateTime(),
        "locked": orm.Boolean(default=False),
    }


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
