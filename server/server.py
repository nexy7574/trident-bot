import asyncio
import secrets
from typing import Union, Literal
from urllib.parse import quote_plus as quote

import discord
import httpx
import orm
from fastapi import FastAPI, Query, HTTPException, Depends, Form
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from database import Token, APIToken, Guild as DatabaseGuild, Ticket as DatabaseTicket
from .models import *
from . import utils
from cogs.ticket import TicketCog


async def locate_ticket(guild: DatabaseGuild, local_id: int = None, global_id: int = None) -> DatabaseTicket | None:
    values = {
        "localID": local_id,
        "id": global_id
    }
    for k, v in values.items():
        try:
            return await DatabaseTicket.objects.get(guild=guild, **{k: v})
        except orm.NoMatch:
            continue


def oauth_ready():
    if app.state.client_id is None:
        raise HTTPException(503, "Bot is not ready yet - unable to handle request.", {"Retry-After": "10"})
    if app.state.client_id is None or app.state.redirect_uri is None:
        raise HTTPException(
            501,
            "Insufficient configuration options - admin has disabled oauth requests. If you are the admin,"
            " please supply `server.client_secret` and `server.redirect_uri` in `config.json`.",
        )
    return True


app = FastAPI(
    dependencies=[
        Depends(oauth_ready)
    ]
)
bearer = HTTPBearer()
app.state.sessions = {}


@app.exception_handler(httpx.HTTPError)
async def exception_handler(_, exc: httpx.HTTPError):
    return JSONResponse(
        {
            "detail": "Backend request to '%s %s' failed: %s %s"
            % (exc.request.method, exc.request.url, exc.__class__.__name__, exc)
        },
        500,
    )


def has_state(state: str = Query(None)) -> str:
    if state is None:
        raise HTTPException(403, "No state-session. Please start oauth flow again.")
    if state not in app.state.sessions.keys():
        raise HTTPException(403, "No valid state-session. Please start oauth flow again.")
    return state


def has_token_new() -> Depends:
    def inner(token: HTTPAuthorizationCredentials = Depends(bearer)) -> str:
        bearer_token = token.credentials.strip("Bearer")
        if not bool(bearer_token):
            raise HTTPException(401, "Invalid bearer token.", {"WWW-Authenticate": "Bearer"})
        return bearer_token

    return Depends(inner)


async def get_user(token: str = has_token_new()) -> Token:
    try:
        t = await Token.objects.get(session=token)
    except orm.NoMatch:
        raise HTTPException(403, "Invalid session. Please clear your cookies and try again.")
    return t


async def get_account(authorisation: HTTPAuthorizationCredentials = Depends(bearer)) -> int:
    token = authorisation.credentials.lower().strip("bearer ")
    try:
        e = await APIToken.objects.get(token=token)
    except orm.NoMatch:
        raise HTTPException(401, "Invalid API token.", {"WWW-Authenticate": "Bearer"})
    return e.owner_id


def has_permissions(permissions: discord.Permissions, member: discord.Member):
    return member.guild_permissions.is_superset(permissions)


@app.get("/", include_in_schema=False)
def root():
    """This literally just redirects you to docs dw about it"""
    return RedirectResponse("/docs")


@app.get("/oauth/start", dependencies=[Depends(oauth_ready)], include_in_schema=False)
def start_oauth_flow(page: str = None):
    url = (
        "{}/oauth2/authorize?client_id={}&permissions=388176&redirect_uri={}&response_type=code&"
        "scope={}&state={}&prompt=none"
    )
    _s = secrets.token_urlsafe()
    url = url.format(
        app.state.api,
        app.state.client_id,
        quote(app.state.redirect_uri),
        r"+".join(("identify", "guilds", "guilds.members.read")),
        _s,
    )
    app.state.sessions[_s] = page
    return RedirectResponse(url)


@app.get("/oauth/callback", dependencies=[Depends(oauth_ready)], include_in_schema=False)
async def callback(code: str = Query(...), state: str = Depends(has_state)):
    response: httpx.Response = await app.state.bot.session.post(
        app.state.api + "/oauth2/token",
        data={
            "client_id": app.state.client_id,
            "client_secret": app.state.client_secret,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": app.state.redirect_uri,
        },
    )
    if response.status_code != 200:
        raise HTTPException(response.status_code, response.json())
    else:
        data = response.json()
        for scope in ("identify", "guilds", "guilds.members.read"):
            if scope not in data["scope"]:
                raise HTTPException(400, "Missing scope %r. Please re-start oauth flow." % scope)

    user = await app.state.bot.session.get(
        app.state.api + "/users/@me", headers={"Authorization": "Bearer " + data["access_token"]}
    )
    if user.status_code != 200:
        raise HTTPException(user.status_code, user.json())
    user_data = user.json()
    session = secrets.token_hex()
    await Token.objects.create(
        user_id=int(user_data["id"]),
        access_token=data["access_token"],
        refresh_token=data["refresh_token"],
        session=session,
        scope=data["scope"],
    )
    page = app.state.sessions[state]
    res = {
        type(None): JSONResponse({"status": "authorised", "user": user_data, "session": session}),
        str: RedirectResponse((page or "/oauth/callback") + "?token=" + session),
    }[type(page)]

    res.set_cookie(
        "token",
        session,
        data["expires_in"] + 86400,
    )
    return res


@app.get("/api/@me", response_model=User)
async def get_current_user(user: Token = Depends(get_user)):
    response = await app.state.bot.session.get(
        app.state.api + "/users/@me", headers={"Authorization": "Bearer " + user.access_token}
    )
    if response.status_code == 401:
        try:
            new_token = await utils.refresh_token(user.refresh_token, app)
        except httpx.HTTPStatusError:
            raise HTTPException(response.status_code, response.json()) from None
        else:
            await user.update(access_token=new_token["access_token"], refresh_token=new_token["refresh_token"])
            return RedirectResponse("/api/@me")

    return User(**response.json())


@app.get("/api/@me/guilds", response_model=list[PartialGuild])
async def get_user_guilds(user: Token = Depends(get_user), mutual: bool = True):
    """Fetches a list of the guilds the user is in.

    If `:mutual` is True, this will only fetch shared servers."""
    response = await app.state.bot.session.get(
        app.state.api + "/users/@me/guilds", headers={"Authorization": "Bearer " + user.access_token}
    )
    if response.status_code == 401:
        try:
            new_token = await utils.refresh_token(user.refresh_token, app)
        except httpx.HTTPStatusError:
            raise HTTPException(response.status_code, response.json()) from None
        else:
            await user.update(access_token=new_token["access_token"], refresh_token=new_token["refresh_token"])
            response = await app.state.bot.session.get(
                app.state.api + "/users/@me/guilds", headers={"Authorization": "Bearer " + user.access_token}
            )

    data = response.json()
    if response.status_code != 200:
        raise HTTPException(response.status_code, data)
    if mutual:
        return [PartialGuild(**x) for x in data if app.state.bot.get_guild(int(x["id"])) is not None]
    return [PartialGuild(**x) for x in data]


@app.get("/api/guilds/{guild_id}", response_model=Guild)
async def get_guild(guild_id: int, user: Token = Depends(get_user)):
    response = await app.state.bot.session.get(
        app.state.api + f"/guilds/{guild_id}", headers={"Authorization": "Bot " + app.state.bot.http.token}
    )
    if response.status_code == 401:
        try:
            new_token = await utils.refresh_token(user.refresh_token, app)
        except httpx.HTTPStatusError:
            raise HTTPException(response.status_code, response.json()) from None
        else:
            await user.update(access_token=new_token["access_token"], refresh_token=new_token["refresh_token"])
            response = await app.state.bot.session.get(
                app.state.api + "/api/guilds/%s" % guild_id, headers={"Authorization": "Bearer " + user.access_token}
            )
    if response.status_code != 200:
        raise HTTPException(response.status_code, response.json())

    data = response.json()

    response = await app.state.bot.session.get(
        app.state.api + f"/guilds/{guild_id}/channels", headers={"Authorization": "Bot " + app.state.bot.http.token}
    )
    if response.status_code == 200:
        data = {**data, "channels": response.json()}
    return Guild(**data)


@app.get("/api/guilds/{guild_id}/members/@me", response_model=Member)
async def get_our_guild_member(guild_id: int, user: Token = Depends(get_user)):
    """Fetches the member from the specified server."""
    response = await app.state.bot.session.get(
        app.state.api + f"/users/@me/guilds/{guild_id}/member", headers={"Authorization": "Bearer " + user.access_token}
    )
    if response.status_code == 401:
        try:
            new_token = await utils.refresh_token(user.refresh_token, app)
        except httpx.HTTPStatusError:
            raise HTTPException(response.status_code, response.json()) from None
        else:
            await user.update(access_token=new_token["access_token"], refresh_token=new_token["refresh_token"])
            return RedirectResponse("/api/@me")

    return Member(**response.json())


@app.get("/api/guilds/{guild_id}/members/{member_id}", response_model=Member, dependencies=[Depends(get_user)])
async def get_guild_member(guild_id: int, member_id: int):
    response = await app.state.bot.session.get(
        app.state.api + f"/guilds/{guild_id}/members/{member_id}", headers={
            "Authorization": "Bot " + app.state.bot.http.token
        }
    )
    if response.status_code != 200:
        return JSONResponse(
            response.status_code,
            response.json(),
            response.headers | {"X-Upstream": True}
        )

    return Member(**response.json())


@app.get("/api/guilds/{guild_id}/config", dependencies=[Depends(get_user)], response_model=GuildConfig)
async def get_guild_config(guild_id: int):
    try:
        guild: DatabaseGuild = await DatabaseGuild.objects.get(id=guild_id)
    except orm.NoMatch:
        raise HTTPException(404, "Unknown guild ID.")
    return GuildConfig(
        entry_id=guild.entry_id,
        id=str(guild.id),
        ticketCounter=guild.ticketCounter,
        ticketCategory=guild.ticketCategory,
        logChannel=guild.logChannel,
        supportRoles=list(map(str, guild.supportRoles)),
        pingSupportRoles=guild.pingSupportRoles,
        maxTickets=guild.maxTickets,
        supportEnabled=guild.supportEnabled,
        questions=list(map(lambda d: TicketQuestion(**d), guild.questions)),
    )


@app.get(
    "/api/guilds/{guild_id}/tickets", response_model=Union[list[Ticket], Ticket], dependencies=[Depends(oauth_ready)]
)
async def get_guild_tickets(
    guild_id: int, user: Token = Depends(get_user), local_id: int = None, global_id: int = None
):
    try:
        guild: DatabaseGuild = await DatabaseGuild.objects.get(id=guild_id)
    except orm.NoMatch:
        raise HTTPException(404, "Unknown guild ID.")

    d_guild: discord.Guild | None = app.state.bot.get_guild(guild_id)
    if not d_guild:
        raise HTTPException(404, "Unknown guild ID.")
    try:
        member = await d_guild.fetch_member(user.user_id)
    except discord.NotFound:
        raise HTTPException(403, "You are not in that server.")

    if not TicketCog.is_support(guild, member):
        raise HTTPException(403, "Insufficient permissions.")

    if local_id or global_id:
        ticket: DatabaseTicket = await locate_ticket(guild, local_id, global_id)
        if not ticket:
            raise HTTPException(404, "Unknown ticket")

        if not member.guild_permissions.administrator:
            if user.user_id != ticket.author:
                if not TicketCog.is_support(guild, member):
                    raise HTTPException(
                        403, "Insufficient permissions. You must be the author of a ticket or a " "member of support."
                    )
        t = ticket
        return Ticket(
            id=t.id,
            localID=t.localID,
            guild=convert_database_guild_to_JSON_model(guild),
            author=str(t.author),
            channel=str(t.channel),
            subject=t.subject,
            openedAt=t.openedAt,
            locked=t.locked,
        )

    tickets: list[DatabaseTicket] = await DatabaseTicket.objects.filter(guild__id=guild_id).all()
    return [
        Ticket(
            id=t.id,
            localID=t.localID,
            guild=convert_database_guild_to_JSON_model(guild),
            author=str(t.author),
            channel=str(t.channel),
            subject=t.subject,
            openedAt=t.openedAt,
            locked=t.locked,
        )
        for t in tickets
    ]


@app.patch("/api/guilds/{guild_id}/tickets/{ticket_id}", status_code=204)
async def lock_ticket(guild_id: int, ticket_id: int, body: TicketLockPayload, user: Token = Depends(get_user)):
    try:
        guild: DatabaseGuild = await DatabaseGuild.objects.get(id=guild_id)
    except orm.NoMatch:
        raise HTTPException(404, "Unknown guild ID.")

    d_guild: discord.Guild | None = app.state.bot.get_guild(guild_id)
    if not d_guild:
        raise HTTPException(404, "Unknown guild ID.")
    try:
        member = await d_guild.fetch_member(user.user_id)
    except discord.NotFound:
        raise HTTPException(403, "You are not in that server.")
    if not TicketCog.is_support(guild, member):
        raise HTTPException(403, "Insufficient permissions.")

    ticket: DatabaseTicket = await locate_ticket(guild, ticket_id, ticket_id)
    if not ticket:
        raise HTTPException(404, "Unknown ticket")

    channel = app.state.bot.get_channel(ticket.channel)
    if body.locked:
        d = "🔒 Ticket is now locked, so only administrators can close it. Run this command again to unlock it."
    else:
        d = "🔓 Ticket is now unlocked, so anyone can close it. Run this command again to lock it."
    embed = discord.Embed(
        description=d,
        colour=discord.Colour.blue()
    )
    embed.set_author(
        name=member,
        icon_url=member.display_avatar.url
    )
    embed.set_footer(text="Via web dashboard")
    await channel.send(embed=embed)
    await ticket.update(locked=body.locked)
    if ticket.locked:
        if channel.permissions_for(d_guild.me).manage_channels:
            if not channel.name.startswith("\N{lock}"):
                app.state.bot.loop.create_task(
                    channel.edit(
                        name="\N{lock}-ticket-{}".format(ticket.localID),
                    ),
                )
    else:
        if channel.permissions_for(d_guild.me).manage_channels:
            if channel.name.startswith("\N{lock}"):
                app.state.bot.loop.create_task(
                    channel.edit(
                        name="ticket-{}".format(ticket.localID),
                    )
                )


@app.delete("/api/guilds/{guild_id}/tickets/{ticket_id}")
async def delete_ticket(guild_id: int, ticket_id: int, reason: str = Query(None), user: Token = Depends(get_user)):
    try:
        guild: DatabaseGuild = await DatabaseGuild.objects.get(id=guild_id)
    except orm.NoMatch:
        raise HTTPException(404, "Unknown guild ID.")

    d_guild: discord.Guild | None = app.state.bot.get_guild(guild_id)
    if not d_guild:
        raise HTTPException(404, "Unknown guild ID.")
    try:
        member = await d_guild.fetch_member(user.user_id)
    except discord.NotFound:
        raise HTTPException(403, "You are not in that server.")
    if not TicketCog.is_support(guild, member):
        raise HTTPException(403, "Insufficient permissions.")

    ticket: DatabaseTicket = await locate_ticket(guild, ticket_id, ticket_id)
    if not ticket:
        raise HTTPException(404, "Unknown ticket")
    await ticket.guild.load()

    cog: TicketCog = app.state.bot.get_cog("TicketCog")
    logged = await cog.send_log(ticket, "(via web dashboard) %s" % (reason or 'No reason'), member)

    try:
        await app.state.bot.get_channel(ticket.channel).delete(reason="Closed by {!s}.".format(member))
    except (AttributeError, discord.HTTPException):
        pass
    finally:
        await ticket.delete()

    if logged:
        return JSONResponse({"status": "OK"})
    return JSONResponse({"status": "meh"})


def run(bot) -> app:
    app.state.bot = bot
    app.state.all_config = bot.config
    app.state.config = bot.config.get("server", {})
    app.state.api = "https://discord.com/api/v" + app.state.config.get("discord_api_version", "10")
    app.state.client_id = None
    if bot.user is None:
        task: asyncio.Task = bot.loop.create_task(bot.wait_until_ready())
        task.add_done_callback(lambda _: setattr(app.state, "client_id", str(bot.user.id)))
    app.state.client_secret = app.state.config.get("client_secret")
    app.state.redirect_uri = app.state.config.get("redirect_uri")
    return app
