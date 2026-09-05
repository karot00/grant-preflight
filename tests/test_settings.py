"""Tests for the P1.2 configuration contract (settings.py), the P1.3 error
contract (errors.py), and self-tests for the P1.5 outbound-call guard
installed by conftest.py.

These tests are pure: they build environment mappings in memory and never
touch the network, the filesystem beyond import, or real credentials.
"""

import dataclasses
import importlib
import os
import socket
from pathlib import Path

import pytest
import requests
import snowflake.connector
from conftest import CREDENTIAL_ENV_NAMES as GUARD_CREDENTIAL_ENV_NAMES
from conftest import MODE_ENV_NAMES
from conftest import OutboundCallBlocked
from google import genai

import settings as settings_module
from errors import ERROR_CODES, AppError
from settings import Settings, load_settings

CREDENTIAL_ENV_NAMES = (
    "GEMINI_API_KEY",
    "SNOWFLAKE_ACCOUNT",
    "SNOWFLAKE_USER",
    "SNOWFLAKE_PRIVATE_KEY_FILE",
    "SNOWFLAKE_PRIVATE_KEY_PASSPHRASE",
)

OPERATOR_LIVE_SNOWFLAKE_ENV = {
    "APP_MODE": "operator",
    "AI_MODE": "live",
    "STORAGE_MODE": "snowflake",
    "GEMINI_API_KEY": "sentinel-gemini-key",
    "SNOWFLAKE_ACCOUNT": "sentinel-org-account",
    "SNOWFLAKE_USER": "GRANT_PREFLIGHT_SERVICE",
    "SNOWFLAKE_PRIVATE_KEY_FILE": "/sentinel/secrets/snowflake_key.p8",
    "SNOWFLAKE_PRIVATE_KEY_PASSPHRASE": "sentinel-passphrase",
}


# --- P1.3 error contract -------------------------------------------------


def test_error_codes_allowlist_is_exact():
    assert ERROR_CODES == frozenset({
        "CONFIG_INVALID",
        "INPUT_INVALID",
        "URL_REJECTED",
        "FETCH_FAILED",
        "FETCH_TOO_LARGE",
        "UNSUPPORTED_CONTENT",
        "AI_UNAVAILABLE",
        "AI_REFUSED",
        "AI_INVALID",
        "AI_LIMIT",
        "STORAGE_UNAVAILABLE",
        "STORAGE_CONFLICT",
        "DRAFT_BLOCKED",
        "FIXTURE_MISMATCH",
    })


def test_apperror_holds_code_message_and_default_retryable():
    error = AppError("FETCH_FAILED", "safe message")
    assert isinstance(error, Exception)
    assert error.code == "FETCH_FAILED"
    assert error.message == "safe message"
    assert error.retryable is False
    assert str(error) == "safe message"


def test_apperror_accepts_retryable_flag():
    error = AppError("STORAGE_UNAVAILABLE", "database unreachable", retryable=True)
    assert error.retryable is True


def test_apperror_rejects_unknown_code():
    with pytest.raises(ValueError):
        AppError("NOT_A_CODE", "message")


# --- P1.2 defaults and constants -----------------------------------------


def test_defaults_are_public_recorded_memory():
    loaded = load_settings({})
    assert loaded.app_mode == "public_demo"
    assert loaded.ai_mode == "recorded"
    assert loaded.storage_mode == "memory"
    assert loaded.app_base_url == "https://grant-preflight.karotammela.fi"
    assert loaded.gemini_model == "gemini-3.5-flash"
    assert loaded.snowflake_database == "GRANT_PREFLIGHT"
    assert loaded.snowflake_schema == "APP"
    assert loaded.snowflake_warehouse == "GRANT_PREFLIGHT_WH"
    assert loaded.snowflake_role == "GRANT_PREFLIGHT_APP"
    for name in CREDENTIAL_ENV_NAMES:
        assert getattr(loaded, name.lower()) is None


def test_limits_and_versions_are_code_constants():
    loaded = load_settings({})
    assert loaded.max_source_chars == 40000
    assert loaded.max_response_bytes == 2097152
    assert loaded.max_output_tokens == 16384
    assert loaded.schema_version == 1
    assert loaded.extraction_prompt_version == "1"
    assert loaded.draft_prompt_version == "1"


def test_constants_ignore_environment_overrides(monkeypatch):
    monkeypatch.setenv("MAX_SOURCE_CHARS", "10")
    monkeypatch.setenv("MAX_OUTPUT_TOKENS", "999999")
    monkeypatch.setenv("SCHEMA_VERSION", "2")
    loaded = load_settings({})
    assert loaded.max_source_chars == 40000
    assert loaded.max_output_tokens == 16384
    assert loaded.schema_version == 1


def test_empty_environment_values_fall_back_to_defaults():
    loaded = load_settings({"APP_MODE": "", "AI_MODE": "", "STORAGE_MODE": ""})
    assert loaded.app_mode == "public_demo"
    assert loaded.ai_mode == "recorded"
    assert loaded.storage_mode == "memory"


def test_project_root_is_the_package_directory():
    assert settings_module.PROJECT_ROOT.is_absolute()
    assert settings_module.PROJECT_ROOT == Path(
        settings_module.__file__
    ).resolve().parent
    assert (settings_module.PROJECT_ROOT / "implementation_plan.md").is_file()


def test_settings_is_frozen():
    loaded = load_settings({})
    with pytest.raises(dataclasses.FrozenInstanceError):
        loaded.app_mode = "operator"


def test_load_settings_reads_only_the_supplied_mapping(monkeypatch):
    monkeypatch.setenv("APP_MODE", "operator")
    monkeypatch.setenv("GEMINI_API_KEY", "host-environment-key")
    loaded = load_settings({})
    assert loaded.app_mode == "public_demo"
    assert loaded.gemini_api_key is None


# --- P1.2 public-demo mode rules -----------------------------------------


@pytest.mark.parametrize(
    "override",
    [
        {"AI_MODE": "live"},
        {"STORAGE_MODE": "snowflake"},
        {"AI_MODE": "live", "STORAGE_MODE": "snowflake"},
    ],
)
def test_public_mode_requires_recorded_ai_and_memory_storage(override):
    with pytest.raises(AppError) as excinfo:
        load_settings(override)
    assert excinfo.value.code == "CONFIG_INVALID"


@pytest.mark.parametrize("name", CREDENTIAL_ENV_NAMES)
def test_public_mode_rejects_each_nonempty_credential(name):
    with pytest.raises(AppError) as excinfo:
        load_settings({name: "sentinel-secret-value"})
    error = excinfo.value
    assert error.code == "CONFIG_INVALID"
    assert name in error.message
    assert "sentinel-secret-value" not in error.message


def test_public_mode_allows_fixed_snowflake_resource_names():
    loaded = load_settings({
        "SNOWFLAKE_DATABASE": "GRANT_PREFLIGHT",
        "SNOWFLAKE_SCHEMA": "APP",
        "SNOWFLAKE_WAREHOUSE": "GRANT_PREFLIGHT_WH",
        "SNOWFLAKE_ROLE": "GRANT_PREFLIGHT_APP",
    })
    assert loaded.app_mode == "public_demo"


@pytest.mark.parametrize(
    ("name", "wrong_value"),
    [
        ("SNOWFLAKE_DATABASE", "OTHER_DB"),
        ("SNOWFLAKE_SCHEMA", "PUBLIC"),
        ("SNOWFLAKE_WAREHOUSE", "COMPUTE_WH"),
        ("SNOWFLAKE_ROLE", "ACCOUNTADMIN"),
    ],
)
def test_wrong_fixed_snowflake_names_are_configuration_errors(name, wrong_value):
    with pytest.raises(AppError) as excinfo:
        load_settings({name: wrong_value})
    assert excinfo.value.code == "CONFIG_INVALID"
    assert name in excinfo.value.message


# --- P1.2 operator mode rules --------------------------------------------


@pytest.mark.parametrize(
    "env",
    [
        {"APP_MODE": "operator", "AI_MODE": "live", "STORAGE_MODE": "snowflake"},
        {"APP_MODE": "operator", "AI_MODE": "live", "STORAGE_MODE": "memory"},
        {"APP_MODE": "operator", "AI_MODE": "recorded", "STORAGE_MODE": "memory"},
    ],
)
def test_operator_mode_allows_prescribed_combinations(env):
    loaded = load_settings(env)
    assert loaded.app_mode == "operator"
    assert loaded.ai_mode == env["AI_MODE"]
    assert loaded.storage_mode == env["STORAGE_MODE"]


def test_operator_mode_rejects_recorded_ai_with_snowflake():
    with pytest.raises(AppError) as excinfo:
        load_settings({
            "APP_MODE": "operator",
            "AI_MODE": "recorded",
            "STORAGE_MODE": "snowflake",
        })
    assert excinfo.value.code == "CONFIG_INVALID"


def test_operator_missing_credentials_do_not_change_modes():
    loaded = load_settings({
        "APP_MODE": "operator",
        "AI_MODE": "live",
        "STORAGE_MODE": "snowflake",
    })
    assert loaded.ai_mode == "live"
    assert loaded.storage_mode == "snowflake"
    assert loaded.gemini_credentials_complete is False
    assert loaded.snowflake_credentials_complete is False


def test_operator_live_snowflake_environment_is_complete():
    loaded = load_settings(OPERATOR_LIVE_SNOWFLAKE_ENV)
    assert loaded.gemini_credentials_complete is True
    assert loaded.snowflake_credentials_complete is True


@pytest.mark.parametrize("removed_name", [
    "SNOWFLAKE_ACCOUNT",
    "SNOWFLAKE_USER",
    "SNOWFLAKE_PRIVATE_KEY_FILE",
    "SNOWFLAKE_PRIVATE_KEY_PASSPHRASE",
])
def test_snowflake_flag_requires_all_four_values(removed_name):
    env = dict(OPERATOR_LIVE_SNOWFLAKE_ENV)
    del env[removed_name]
    loaded = load_settings(env)
    assert loaded.snowflake_credentials_complete is False


def test_relative_private_key_path_is_rejected():
    env = dict(OPERATOR_LIVE_SNOWFLAKE_ENV)
    env["SNOWFLAKE_PRIVATE_KEY_FILE"] = "relative/snowflake_key.p8"
    with pytest.raises(AppError) as excinfo:
        load_settings(env)
    assert excinfo.value.code == "CONFIG_INVALID"
    assert "SNOWFLAKE_PRIVATE_KEY_FILE" in excinfo.value.message


# --- P1.2 enum, model, and URL validation --------------------------------


@pytest.mark.parametrize(
    ("name", "invalid_value"),
    [
        ("APP_MODE", "staging"),
        ("APP_MODE", "Operator"),
        ("AI_MODE", "fast"),
        ("STORAGE_MODE", "sqlite"),
    ],
)
def test_invalid_enum_values_are_configuration_errors(name, invalid_value):
    with pytest.raises(AppError) as excinfo:
        load_settings({name: invalid_value})
    assert excinfo.value.code == "CONFIG_INVALID"
    assert name in excinfo.value.message


@pytest.mark.parametrize(
    "invalid_model",
    ["gemini-3.5-flash-latest", "gemini-2.5-flash", "gemini-3.5-pro"],
)
def test_any_other_gemini_model_is_a_configuration_error(invalid_model):
    with pytest.raises(AppError) as excinfo:
        load_settings({"GEMINI_MODEL": invalid_model})
    assert excinfo.value.code == "CONFIG_INVALID"


def test_exact_gemini_model_is_accepted():
    loaded = load_settings({"GEMINI_MODEL": "gemini-3.5-flash"})
    assert loaded.gemini_model == "gemini-3.5-flash"


def test_custom_https_base_url_is_accepted():
    loaded = load_settings({"APP_BASE_URL": "https://example.test"})
    assert loaded.app_base_url == "https://example.test"


@pytest.mark.parametrize(
    "invalid_url",
    ["grant-preflight.karotammela.fi", "ftp://example.test", "//example.test"],
)
def test_non_http_url_base_url_is_rejected(invalid_url):
    with pytest.raises(AppError) as excinfo:
        load_settings({"APP_BASE_URL": invalid_url})
    assert excinfo.value.code == "CONFIG_INVALID"


# --- P1.2 secret handling --------------------------------------------------


def test_empty_secret_values_become_none():
    loaded = load_settings({name: "" for name in CREDENTIAL_ENV_NAMES})
    for name in CREDENTIAL_ENV_NAMES:
        assert getattr(loaded, name.lower()) is None


def test_repr_never_contains_secret_values():
    loaded = load_settings(OPERATOR_LIVE_SNOWFLAKE_ENV)
    rendered = repr(loaded)
    for secret in (
        "sentinel-gemini-key",
        "sentinel-org-account",
        "GRANT_PREFLIGHT_SERVICE",
        "sentinel-passphrase",
        "/sentinel/secrets/snowflake_key.p8",
    ):
        assert secret not in rendered
    assert "operator" in rendered


def test_settings_defaults_equal_public_demo_settings():
    assert Settings() == load_settings({})


# --- P1.5 outbound-call guard self-tests -----------------------------------


def test_guard_blocks_requests_network_access():
    with pytest.raises(OutboundCallBlocked):
        requests.get("https://avustukset.hel.fi/", timeout=1)
    with pytest.raises(OutboundCallBlocked):
        requests.sessions.Session().get("https://example.test/", timeout=1)


def test_guard_blocks_dns_lookups():
    with pytest.raises(OutboundCallBlocked):
        socket.getaddrinfo("avustukset.hel.fi", 443)
    with pytest.raises(OutboundCallBlocked):
        socket.gethostbyname("avustukset.hel.fi")
    with pytest.raises(OutboundCallBlocked):
        socket.gethostbyname_ex("avustukset.hel.fi")


def test_guard_blocks_gemini_client_construction():
    with pytest.raises(OutboundCallBlocked):
        genai.Client(api_key="sentinel-not-a-real-key")


def test_guard_blocks_snowflake_connection_creation():
    with pytest.raises(OutboundCallBlocked):
        snowflake.connector.connect(account="sentinel-account")
    with pytest.raises(OutboundCallBlocked):
        snowflake.connector.SnowflakeConnection(account="sentinel-account")


@pytest.mark.parametrize("name", GUARD_CREDENTIAL_ENV_NAMES + MODE_ENV_NAMES)
def test_guard_clears_inherited_environment_variables(monkeypatch, name):
    # The guard's autouse fixture already ran; a value set here by a test's
    # own monkeypatch is visible, proving the guard does not fight explicit
    # per-test injection, while the inherited host value was removed first.
    assert name not in os.environ or os.environ[name] == ""
    monkeypatch.setenv(name, "sentinel-injected-by-test")
    assert os.environ[name] == "sentinel-injected-by-test"


def test_guard_credential_names_match_settings_contract():
    assert GUARD_CREDENTIAL_ENV_NAMES == CREDENTIAL_ENV_NAMES


def test_default_settings_fixture_is_public_recorded_memory(default_settings):
    assert default_settings.app_mode == "public_demo"
    assert default_settings.ai_mode == "recorded"
    assert default_settings.storage_mode == "memory"
    assert default_settings.gemini_api_key is None
    assert default_settings.snowflake_account is None


def test_importing_implemented_modules_performs_no_outbound_calls():
    # Importing the implemented application modules under the active guard
    # proves the imports themselves trigger no blocked network, DNS, Gemini,
    # or Snowflake call; a violation would raise OutboundCallBlocked.
    import errors  # noqa: F401
    import models  # noqa: F401
    import services.evidence  # noqa: F401
    import settings  # noqa: F401


@pytest.mark.parametrize(
    "module_name",
    [
        "app",
        "services.assessment",
        "services.db_service",
        "services.demo_service",
        "services.export",
        "services.gemini_service",
        "services.salesforce_service",
        "services.scraper_service",
    ],
)
def test_unimplemented_stub_modules_fail_honestly_without_outbound_calls(module_name):
    # Phase 1 stubs must raise NotImplementedError (never OutboundCallBlocked
    # and never silent success) until their phase implements them.
    with pytest.raises(NotImplementedError):
        importlib.import_module(module_name)
