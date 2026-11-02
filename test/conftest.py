"""Test-wide guards."""
import pytest

from app.services import discord_notify


@pytest.fixture(autouse=True)
def no_real_discord(monkeypatch):
    """config.toml may hold a real Discord webhook: no test may post to it.

    The send itself is blocked rather than the webhook blanked, because some
    web UI tests save the in-memory config back to config.toml. Tests that
    check notifications mock the service on top of this."""
    monkeypatch.setattr(discord_notify.DiscordNotifyService, "send", lambda self, content, embed=None: False)
