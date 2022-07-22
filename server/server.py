import asyncio
import os
from urllib.parse import quote_plus as quote

import discord
import httpx
import orm
from fastapi import FastAPI, Query, HTTPException, Depends, Cookie
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from database import Token, APIToken, Guild as DatabaseGuild
from .models import *
from . import utils
from ..cogs.ticket import TicketCog


app = FastAPI()
bearer = HTTPBearer()
app.state.sessions = {}


def oauth_ready():
    if app.state.client_id is None:
        raise HTTPException(503, "Bot is not ready yet - unable to handle oauth requests.", {"Retry-After": "10"})
    if app.state.client_id is None or app.state.redirect_uri is None:
        raise HTTPException(
            501,
            "Insufficient configuration options - admin has disabled oauth requests. If you are the admin,"
            " please supply `server.client_secret` and `server.redirect_uri` in `config.json`.",
        )
    return True


def has_state(state: str = Query(None)) -> str:
    if state is None:
        raise HTTPException(403, "No state-session. Please start oauth flow again.")
    if state not in app.state.sessions.keys():
        raise HTTPException(403, "No valid state-session. Please start oauth floq again.")
    return state


def has_token(token: str = Cookie(None)) -> str:
    if token is None:
        raise HTTPException(403, "No session. Please start oauth flow again.")
    return token


async def get_user(token: str = Depends(has_token)) -> Token:
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
def start_oauth_flow():
    _s = os.urandom(32).hex()
    url = (
        "{}/oauth2/authorize?client_id={}&permissions=388176&redirect_uri={}&response_type=code&"
        "scope=identify%20guilds%20bot%20applications.commands&state={}"
    )
    url = url.format(
        app.state.api,
        app.state.client_id,
        quote(app.state.redirect_uri),
        # app.state.redirect_uri,
        _s,
    )
    app.state.sessions[_s] = None
    return RedirectResponse(url)


@app.get("/oauth/callback", dependencies=[Depends(oauth_ready), Depends(has_state)], include_in_schema=False)
async def callback(code: str = Query(...)):
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

    user = await app.state.bot.session.get(
        app.state.api + "/users/@me", headers={"Authorization": "Bearer " + data["access_token"]}
    )
    if user.status_code != 200:
        raise HTTPException(user.status_code, user.json())
    user_data = user.json()
    session = os.urandom(64).hex()
    await Token.objects.create(
        user_id=int(user_data["id"]),
        access_token=data["access_token"],
        refresh_token=data["refresh_token"],
        session=session,
    )
    res = JSONResponse(
        {"status": "authorised", "user": user_data, "session": session},
        headers={"Cache-Control": "max-age=806400, min-fresh=" + str(data["expires_in"])},
    )
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


@app.get("/api/guilds", response_model=list[PartialGuild])
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
    return Guild(**data)


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


@app.get("/api/guilds/{guild_id}/tickets")
async def get_guild_tickets(guild_id: int, user: Token = Depends(get_user)):
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

    if not has_permissions(discord.Permissions(manage_guild=True, manage_channels=True), member):
        if not TicketCog.is_support(guild, member):
            raise HTTPException(403, "Insufficient permissions.")


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
