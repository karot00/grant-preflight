"""Pytest fixtures and the P1.5 outbound-call guard.

The guard is installed before any service tests exist. For every test it:

* defaults the application to public/recorded/memory settings and clears
  inherited credential and mode environment variables, so no test can pick up
  developer credentials from the host environment;
* blocks Requests network operations (``Session.send``), real DNS lookups
  (``socket.getaddrinfo``/``gethostbyname*``), Gemini client construction
  (``google.genai.Client.__init__``), and Snowflake connection creation
  (``snowflake.connector.connect``/``SnowflakeConnection.__init__``).

Any blocked call raises :class:`OutboundCallBlocked`. Individual tests that
need fakes inject them explicitly with their own ``monkeypatch`` calls after
this guard is installed; overriding a patched attribute again replaces the
guard for that single test only.
"""

import socket

import pytest
import requests.sessions
import snowflake.connector
from google import genai

from settings import load_settings

CREDENTIAL_ENV_NAMES = (
    "GEMINI_API_KEY",
    "SNOWFLAKE_ACCOUNT",
    "SNOWFLAKE_USER",
    "SNOWFLAKE_PRIVATE_KEY_FILE",
    "SNOWFLAKE_PRIVATE_KEY_PASSPHRASE",
)

MODE_ENV_NAMES = ("APP_MODE", "AI_MODE", "STORAGE_MODE")


class OutboundCallBlocked(RuntimeError):
    """Raised when a test triggers a blocked outbound call."""


def _blocked(operation: str):
    def _raise(*args, **kwargs):
        raise OutboundCallBlocked(
            f"{operation} is blocked during tests; inject an explicit fake instead"
        )

    return _raise


@pytest.fixture(autouse=True)
def outbound_call_guard(monkeypatch):
    """Block network, DNS, Gemini, and Snowflake access for every test."""
    monkeypatch.setattr(
        requests.sessions.Session, "send", _blocked("Requests network access")
    )
    monkeypatch.setattr(socket, "getaddrinfo", _blocked("DNS resolution"))
    monkeypatch.setattr(socket, "gethostbyname", _blocked("DNS resolution"))
    monkeypatch.setattr(socket, "gethostbyname_ex", _blocked("DNS resolution"))
    monkeypatch.setattr(genai.Client, "__init__", _blocked("Gemini client construction"))
    monkeypatch.setattr(
        snowflake.connector, "connect", _blocked("Snowflake connection creation")
    )
    monkeypatch.setattr(
        snowflake.connector.SnowflakeConnection,
        "__init__",
        _blocked("Snowflake connection creation"),
    )
    for name in CREDENTIAL_ENV_NAMES + MODE_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture()
def default_settings():
    """Public/recorded/memory settings built from an empty environment."""
    return load_settings({})
