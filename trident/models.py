import datetime
import uuid

from tortoise import Model, fields


class Guild(Model):
    class Meta:
        table = "guilds"

    entry_id: uuid.UUID = fields.UUIDField(pk=True)
    id: int = fields.BigIntField(unique=True)
    ticket_count: int = fields.BigIntField(default=1)
    ticket_category: int | None = fields.BigIntField(null=True)
    log_channel: int | None = fields.BigIntField(null=True, unique=True)
    support_roles: list[int] = fields.JSONField(default=[])
    ping_support_roles: bool = fields.BooleanField(default=True)
    max_tickets: int = fields.IntField(default=50)
    support_enabled: bool = fields.BooleanField(default=True)

    questions: fields.ReverseRelation["TicketQuestion"]
    tickets: fields.ReverseRelation["Ticket"]
    tags: fields.ReverseRelation["Tag"]


class TicketQuestion(Model):
    class Meta:
        table = "ticket_questions"

    entry_id: uuid.UUID = fields.UUIDField(pk=True)
    guild: fields.ForeignKeyRelation[Guild] = fields.ForeignKeyField(
        "models.Guild", related_name="questions", on_delete=fields.CASCADE
    )
    label: str = fields.CharField(max_length=100)
    placeholder: str = fields.CharField(max_length=100)
    min_length: int = fields.IntField(default=2)
    max_length: int = fields.IntField(default=4000)
    required: bool = fields.BooleanField(default=True)
    default_value: str | None = fields.CharField(max_length=100, null=True)


class Ticket(Model):
    class Meta:
        table = "tickets"

    entry_id: uuid.UUID = fields.UUIDField(pk=True)
    number: int = fields.IntField()
    guild: fields.ForeignKeyRelation[Guild] = fields.ForeignKeyField(
        "models.Guild", related_name="tickets", on_delete=fields.CASCADE
    )
    author: int = fields.BigIntField()
    channel: int = fields.BigIntField(unique=True)
    subject: str | None = fields.CharField(max_length=1024, null=True)
    opened_at: datetime.datetime = fields.DatetimeField(auto_now_add=True)
    locked: bool = fields.BooleanField(default=False)


class Tag(Model):
    class Meta:
        table = "tags"

    entry_id: uuid.UUID = fields.UUIDField(pk=True)
    guild: fields.ForeignKeyRelation[Guild] = fields.ForeignKeyField(
        "models.Guild", related_name="tags", on_delete=fields.CASCADE
    )
    created_at: datetime.datetime = fields.DatetimeField(auto_now_add=True)
    name: str = fields.CharField(max_length=100)
    content: str = fields.CharField(max_length=4000)
    author: int = fields.BigIntField()
    owner: int = fields.BigIntField()
    uses: int = fields.IntField(default=0)
