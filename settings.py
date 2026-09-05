"""Application settings contract (P1.2).

:func:`load_settings` reads operator-supplied environment variables from an
explicit mapping and returns a frozen :class:`Settings` dataclass. Streamlit
secrets and query parameters are never consulted, which keeps settings usable
in tests and scripts. Missing secret values are kept as ``None`` and secret
fields are excluded from the dataclass repr.

Mode rules enforced here:

* ``public_demo`` requires ``AI_MODE=recorded`` and ``STORAGE_MODE=memory``
  and refuses startup when any Gemini/Snowflake credential (API key, account,
  user, private-key path, passphrase) is non-empty. The fixed Snowflake
  database/schema/warehouse/role names are not secrets and do not trigger that
  rejection. There is no UI or URL parameter that enables operator mode.
* ``operator`` supports live AI with Snowflake, live AI with explicitly
  selected memory storage, and recorded AI with memory storage. Recorded AI
  with Snowflake is rejected so demo replay can never be mistaken for live
  persisted work.
* Missing live credentials make that capability unavailable (see
  :attr:`Settings.gemini_credentials_complete` and
  :attr:`Settings.snowflake_credentials_complete`) with a clear warning in the
  UI; they never silently change ``ai_mode`` or ``storage_mode``.

Limits, schema/prompt versions, and Snowflake resource names are code
constants validated by settings, not browser-controlled options. Invalid enum
combinations and wrong fixed resource names are ``CONFIG_INVALID``
configuration errors.

``PROJECT_ROOT`` anchors all fixture, prompt, and configuration paths; it is
never the current working directory or browser input. All project text/JSON
files are UTF-8.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from errors import AppError

PROJECT_ROOT = Path(__file__).resolve().parent

APP_MODES = ("public_demo", "operator")
AI_MODES = ("recorded", "live")
STORAGE_MODES = ("memory", "snowflake")

DEFAULT_APP_BASE_URL = "https://grant-preflight.karotammela.fi"
FIXED_GEMINI_MODEL = "gemini-3.5-flash"
FIXED_SNOWFLAKE_DATABASE = "GRANT_PREFLIGHT"
FIXED_SNOWFLAKE_SCHEMA = "APP"
FIXED_SNOWFLAKE_WAREHOUSE = "GRANT_PREFLIGHT_WH"
FIXED_SNOWFLAKE_ROLE = "GRANT_PREFLIGHT_APP"

MAX_SOURCE_CHARS = 40000
MAX_RESPONSE_BYTES = 2097152
MAX_OUTPUT_TOKENS = 16384
SCHEMA_VERSION = 1
EXTRACTION_PROMPT_VERSION = "1"
DRAFT_PROMPT_VERSION = "1"


@dataclass(frozen=True)
class Settings:
    """Frozen application settings; attribute names are the environment
    variable names in lowercase snake_case."""

    app_mode: Literal["public_demo", "operator"] = "public_demo"
    ai_mode: Literal["recorded", "live"] = "recorded"
    storage_mode: Literal["memory", "snowflake"] = "memory"
    app_base_url: str = DEFAULT_APP_BASE_URL
    gemini_model: str = FIXED_GEMINI_MODEL
    gemini_api_key: str | None = field(default=None, repr=False)
    snowflake_account: str | None = field(default=None, repr=False)
    snowflake_user: str | None = field(default=None, repr=False)
    snowflake_private_key_file: str | None = field(default=None, repr=False)
    snowflake_private_key_passphrase: str | None = field(default=None, repr=False)
    snowflake_database: str = FIXED_SNOWFLAKE_DATABASE
    snowflake_schema: str = FIXED_SNOWFLAKE_SCHEMA
    snowflake_warehouse: str = FIXED_SNOWFLAKE_WAREHOUSE
    snowflake_role: str = FIXED_SNOWFLAKE_ROLE
    max_source_chars: int = MAX_SOURCE_CHARS
    max_response_bytes: int = MAX_RESPONSE_BYTES
    max_output_tokens: int = MAX_OUTPUT_TOKENS
    schema_version: int = SCHEMA_VERSION
    extraction_prompt_version: str = EXTRACTION_PROMPT_VERSION
    draft_prompt_version: str = DRAFT_PROMPT_VERSION

    @property
    def gemini_credentials_complete(self) -> bool:
        """True when a Gemini API key is present for live generation."""
        return self.gemini_api_key is not None

    @property
    def snowflake_credentials_complete(self) -> bool:
        """True when all four Snowflake login values are present.

        The private key is an encrypted PKCS#8 PEM file, so the passphrase is
        required together with account, user, and key path.
        """
        return all(
            value is not None
            for value in (
                self.snowflake_account,
                self.snowflake_user,
                self.snowflake_private_key_file,
                self.snowflake_private_key_passphrase,
            )
        )


def load_settings(environ: Mapping[str, str]) -> Settings:
    """Validate ``environ`` and build the frozen :class:`Settings`.

    Raises ``AppError`` with code ``CONFIG_INVALID`` for invalid enum values,
    invalid mode combinations, wrong fixed resource names, a non-absolute
    private-key path, or credentials present in public-demo mode. Error
    messages name environment variables only and never include their values.
    """
    app_mode = _enum_setting(environ, "APP_MODE", APP_MODES, "public_demo")
    ai_mode = _enum_setting(environ, "AI_MODE", AI_MODES, "recorded")
    storage_mode = _enum_setting(environ, "STORAGE_MODE", STORAGE_MODES, "memory")
    app_base_url = _base_url_setting(environ)
    gemini_model = _fixed_setting(environ, "GEMINI_MODEL", FIXED_GEMINI_MODEL)
    gemini_api_key = _secret_setting(environ, "GEMINI_API_KEY")
    snowflake_account = _secret_setting(environ, "SNOWFLAKE_ACCOUNT")
    snowflake_user = _secret_setting(environ, "SNOWFLAKE_USER")
    snowflake_private_key_file = _secret_setting(environ, "SNOWFLAKE_PRIVATE_KEY_FILE")
    snowflake_private_key_passphrase = _secret_setting(
        environ, "SNOWFLAKE_PRIVATE_KEY_PASSPHRASE"
    )
    snowflake_database = _fixed_setting(
        environ, "SNOWFLAKE_DATABASE", FIXED_SNOWFLAKE_DATABASE
    )
    snowflake_schema = _fixed_setting(environ, "SNOWFLAKE_SCHEMA", FIXED_SNOWFLAKE_SCHEMA)
    snowflake_warehouse = _fixed_setting(
        environ, "SNOWFLAKE_WAREHOUSE", FIXED_SNOWFLAKE_WAREHOUSE
    )
    snowflake_role = _fixed_setting(environ, "SNOWFLAKE_ROLE", FIXED_SNOWFLAKE_ROLE)

    if app_mode == "public_demo":
        if ai_mode != "recorded" or storage_mode != "memory":
            raise AppError(
                "CONFIG_INVALID",
                "APP_MODE=public_demo requires AI_MODE=recorded and STORAGE_MODE=memory",
            )
        present_credentials = [
            name
            for name, value in (
                ("GEMINI_API_KEY", gemini_api_key),
                ("SNOWFLAKE_ACCOUNT", snowflake_account),
                ("SNOWFLAKE_USER", snowflake_user),
                ("SNOWFLAKE_PRIVATE_KEY_FILE", snowflake_private_key_file),
                ("SNOWFLAKE_PRIVATE_KEY_PASSPHRASE", snowflake_private_key_passphrase),
            )
            if value is not None
        ]
        if present_credentials:
            raise AppError(
                "CONFIG_INVALID",
                "APP_MODE=public_demo refuses startup with non-empty credentials: "
                + ", ".join(present_credentials),
            )
    else:
        if ai_mode == "recorded" and storage_mode == "snowflake":
            raise AppError(
                "CONFIG_INVALID",
                "APP_MODE=operator rejects AI_MODE=recorded with STORAGE_MODE=snowflake; "
                "recorded demo replay must not be mistaken for live persisted work",
            )
        if snowflake_private_key_file is not None and not Path(
            snowflake_private_key_file
        ).is_absolute():
            raise AppError(
                "CONFIG_INVALID",
                "SNOWFLAKE_PRIVATE_KEY_FILE must be an absolute path outside the repository",
            )

    return Settings(
        app_mode=app_mode,
        ai_mode=ai_mode,
        storage_mode=storage_mode,
        app_base_url=app_base_url,
        gemini_model=gemini_model,
        gemini_api_key=gemini_api_key,
        snowflake_account=snowflake_account,
        snowflake_user=snowflake_user,
        snowflake_private_key_file=snowflake_private_key_file,
        snowflake_private_key_passphrase=snowflake_private_key_passphrase,
        snowflake_database=snowflake_database,
        snowflake_schema=snowflake_schema,
        snowflake_warehouse=snowflake_warehouse,
        snowflake_role=snowflake_role,
    )


def _enum_setting(
    environ: Mapping[str, str], name: str, allowed: tuple[str, ...], default: str
) -> str:
    value = environ.get(name, "") or default
    if value not in allowed:
        raise AppError(
            "CONFIG_INVALID",
            f"{name} must be one of {', '.join(allowed)}; got {value!r}",
        )
    return value


def _fixed_setting(environ: Mapping[str, str], name: str, fixed: str) -> str:
    value = environ.get(name, "") or fixed
    if value != fixed:
        raise AppError(
            "CONFIG_INVALID",
            f"{name} is fixed to {fixed!r} for this release; got {value!r}",
        )
    return value


def _base_url_setting(environ: Mapping[str, str]) -> str:
    value = environ.get("APP_BASE_URL", "") or DEFAULT_APP_BASE_URL
    if not value.startswith(("http://", "https://")):
        raise AppError(
            "CONFIG_INVALID",
            "APP_BASE_URL must be an absolute http(s) URL",
        )
    return value


def _secret_setting(environ: Mapping[str, str], name: str) -> str | None:
    return environ.get(name, "") or None
