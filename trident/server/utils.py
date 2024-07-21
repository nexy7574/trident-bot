__all__ = ("refresh_token",)


async def refresh_token(token: str, app) -> dict:
    data = {
        "client_id": app.state.client_id,
        "client_secret": app.state.client_secret,
        "grant_type": "refresh_token",
        "refresh_token": token,
    }
    response = await app.state.bot.session.post(app.state.api + "/oauth2/token", data=data)
    response.raise_for_status()
    return response.json()
