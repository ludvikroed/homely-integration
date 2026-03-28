"""Tests for config and options flows."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, PropertyMock, patch

import pytest

from homeassistant import config_entries
from homeassistant.config_entries import SOURCE_REAUTH, SOURCE_USER
from homeassistant.data_entry_flow import InvalidData
from homeassistant.data_entry_flow import FlowResultType

from homely import HomelyClient

from custom_components.homely.config_flow import (
    HomelyConfigFlow,
    HomelyOptionsFlow,
    LOCATION_SELECTION_ALL,
    _coerce_scan_interval,
    _entry_home_id,
    _fetch_locations_for_credentials,
    _find_location_by_id,
    _get_client,
    _location_label,
    _location_name,
    _location_options,
    _normalize_location_id,
    _redact,
    fetch_token_with_reason,
    get_data,
    get_location_id,
)
from custom_components.homely.const import (
    CONF_ENABLE_WEBSOCKET,
    CONF_HOME_ID,
    CONF_LOCATION_ID,
    CONF_PENDING_IMPORT_LOCATIONS,
    CONF_PASSWORD,
    CONF_POLL_WHEN_WEBSOCKET,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
    DEFAULT_ENABLE_WEBSOCKET,
    DEFAULT_POLL_WHEN_WEBSOCKET,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from tests.common import (
    LOCATION_ID,
    PASSWORD,
    SECOND_LOCATION_ID,
    USERNAME,
    build_config_entry,
)


def test_config_flow_helper_functions():
    """Helper utilities should normalize and redact predictably."""
    assert _redact(
        {
            CONF_USERNAME: USERNAME,
            CONF_PASSWORD: PASSWORD,
            "other": "value",
        }
    ) == {
        CONF_USERNAME: "***",
        CONF_PASSWORD: "***",
        "other": "value",
    }
    assert _normalize_location_id(123) == "123"
    assert _normalize_location_id(None) is None
    assert _entry_home_id(SimpleNamespace(options={CONF_HOME_ID: "bad"}, data={})) == 0


def test_location_helpers_format_names_and_duplicate_labels():
    """Location helpers should produce stable user-facing names."""
    locations = [
        {
            "locationId": LOCATION_ID,
            "name": "Hytta",
            "gatewayserial": "02000001000109FD",
        },
        {
            "locationId": SECOND_LOCATION_ID,
            "name": "Hytta",
            "gatewayserial": "02000001000123FD",
        },
    ]

    assert _location_name(locations[0]) == "Hytta"
    assert _location_options(locations) == [
        (LOCATION_ID, "Hytta (02000001000109FD)"),
        (SECOND_LOCATION_ID, "Hytta (02000001000123FD)"),
    ]


def test_location_helpers_cover_name_and_label_fallbacks():
    """Location helper fallbacks should stay stable for sparse payloads."""
    no_name = {"gatewayserial": "GW123"}
    no_name_or_gateway = {"locationId": LOCATION_ID}
    empty = {}
    duplicate_locations = [
        {"locationId": LOCATION_ID, "name": "Home"},
        {"locationId": SECOND_LOCATION_ID, "name": "Home"},
    ]

    assert _location_name(no_name) == "Homely GW123"
    assert _location_name(no_name_or_gateway) == f"Homely {LOCATION_ID[:8]}"
    assert _location_name(empty) == "Homely"
    assert (
        _location_label(duplicate_locations[0], duplicate_names={"Home"})
        == f"Home ({LOCATION_ID[:8]})"
    )
    assert _location_label({"name": "Home"}, duplicate_names={"Home"}) == "Home"
    assert _location_options([{"name": "Missing ID"}]) == []
    assert _find_location_by_id(duplicate_locations, None) is None
    assert _find_location_by_id(duplicate_locations, "missing") is None


def test_scan_interval_coercion_uses_safe_defaults():
    """Invalid stored scan intervals should fall back safely."""
    assert _coerce_scan_interval("30") == 30
    assert _coerce_scan_interval("bad") == DEFAULT_SCAN_INTERVAL
    assert _coerce_scan_interval(5) == 30


def test_get_client_builds_sdk_client_from_ha_session(hass):
    """Config flow should build a Homely SDK client from HA's shared session."""
    session = object()

    with patch(
        "custom_components.homely.config_flow.async_get_clientsession",
        return_value=session,
    ):
        client = _get_client(hass)

    assert isinstance(client, HomelyClient)
    assert client._session is session


async def test_fetch_locations_for_credentials_handles_missing_access_token(hass):
    """Auth responses without access token should surface invalid auth."""
    with patch(
        "custom_components.homely.config_flow.fetch_token_with_reason",
        AsyncMock(return_value=({"refresh_token": "only-refresh"}, None)),
    ):
        locations, access_token, reason = await _fetch_locations_for_credentials(
            hass,
            USERNAME,
            PASSWORD,
        )

    assert locations is None
    assert access_token is None
    assert reason == "invalid_auth"


async def test_fetch_locations_for_credentials_translates_location_errors(
    hass, token_response
):
    """Location fetch failures should map to user-friendly reasons."""
    with (
        patch(
            "custom_components.homely.config_flow.fetch_token_with_reason",
            AsyncMock(return_value=(token_response, None)),
        ),
        patch(
            "custom_components.homely.config_flow.get_location_id",
            AsyncMock(return_value=None),
        ),
    ):
        locations, access_token, reason = await _fetch_locations_for_credentials(
            hass,
            USERNAME,
            PASSWORD,
        )

    assert locations is None
    assert access_token is None
    assert reason == "cannot_connect"

    with (
        patch(
            "custom_components.homely.config_flow.fetch_token_with_reason",
            AsyncMock(return_value=(token_response, None)),
        ),
        patch(
            "custom_components.homely.config_flow.get_location_id",
            AsyncMock(return_value=[]),
        ),
    ):
        locations, access_token, reason = await _fetch_locations_for_credentials(
            hass,
            USERNAME,
            PASSWORD,
        )

    assert locations is None
    assert access_token == token_response["access_token"]
    assert reason == "no_homes"


async def test_config_flow_sdk_wrappers_delegate_through_client(hass):
    """Config flow helpers should delegate directly to the SDK client."""
    client = SimpleNamespace(
        fetch_token_with_reason=AsyncMock(
            return_value=({"access_token": "token"}, None)
        ),
        get_locations=AsyncMock(return_value=[{"locationId": LOCATION_ID}]),
        get_home_data=AsyncMock(return_value={"name": "JF23"}),
    )

    with patch("custom_components.homely.config_flow._get_client", return_value=client):
        token_response = await fetch_token_with_reason(hass, USERNAME, PASSWORD)
        locations = await get_location_id(hass, "token")
        location_data = await get_data(hass, "token", LOCATION_ID)

    assert token_response == ({"access_token": "token"}, None)
    assert locations == [{"locationId": LOCATION_ID}]
    assert location_data == {"name": "JF23"}
    client.fetch_token_with_reason.assert_awaited_once_with(USERNAME, PASSWORD)
    client.get_locations.assert_awaited_once_with("token")
    client.get_home_data.assert_awaited_once_with("token", LOCATION_ID)


async def test_user_flow_shows_initial_form(hass):
    """User flow should start with the credentials form."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"


async def test_user_flow_single_location_creates_entry_with_default_options(
    hass,
    token_response,
):
    """Single-location accounts should create an entry immediately."""
    with (
        patch(
            "custom_components.homely.config_flow.fetch_token_with_reason",
            AsyncMock(return_value=(token_response, None)),
        ),
        patch(
            "custom_components.homely.config_flow.get_location_id",
            AsyncMock(return_value=[{"locationId": LOCATION_ID, "name": "Kringsja"}]),
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_USER},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                CONF_USERNAME: USERNAME,
                CONF_PASSWORD: PASSWORD,
            },
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Kringsja"
    assert result["data"] == {
        CONF_USERNAME: USERNAME,
        CONF_PASSWORD: PASSWORD,
        CONF_LOCATION_ID: LOCATION_ID,
    }
    assert result["options"] == {
        CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
        CONF_ENABLE_WEBSOCKET: DEFAULT_ENABLE_WEBSOCKET,
        CONF_POLL_WHEN_WEBSOCKET: DEFAULT_POLL_WHEN_WEBSOCKET,
    }


async def test_user_flow_multiple_locations_requires_selection(
    hass,
    token_response,
    location_response,
):
    """Accounts with multiple locations should show one location dropdown."""
    with (
        patch(
            "custom_components.homely.config_flow.fetch_token_with_reason",
            AsyncMock(return_value=(token_response, None)),
        ),
        patch(
            "custom_components.homely.config_flow.get_location_id",
            AsyncMock(return_value=location_response),
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_USER},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                CONF_USERNAME: USERNAME,
                CONF_PASSWORD: PASSWORD,
            },
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "select_location"


async def test_select_location_step_creates_entry(
    hass,
    token_response,
    location_response,
):
    """Choosing a location should create an entry for that location."""
    with (
        patch(
            "custom_components.homely.config_flow.fetch_token_with_reason",
            AsyncMock(return_value=(token_response, None)),
        ),
        patch(
            "custom_components.homely.config_flow.get_location_id",
            AsyncMock(return_value=location_response),
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_USER},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                CONF_USERNAME: USERNAME,
                CONF_PASSWORD: PASSWORD,
            },
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_LOCATION_ID: SECOND_LOCATION_ID},
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Cabin"
    assert result["data"][CONF_LOCATION_ID] == SECOND_LOCATION_ID


async def test_select_location_step_can_add_all_locations(
    hass,
    token_response,
    location_response,
):
    """Choosing add-all from the dropdown should queue the remaining homes."""
    with (
        patch(
            "custom_components.homely.config_flow.fetch_token_with_reason",
            AsyncMock(return_value=(token_response, None)),
        ),
        patch(
            "custom_components.homely.config_flow.get_location_id",
            AsyncMock(return_value=location_response),
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_USER},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                CONF_USERNAME: USERNAME,
                CONF_PASSWORD: PASSWORD,
            },
        )
        assert result["step_id"] == "select_location"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_LOCATION_ID: LOCATION_SELECTION_ALL},
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "JF23"
    assert result["data"][CONF_LOCATION_ID] == LOCATION_ID
    assert result["data"][CONF_PENDING_IMPORT_LOCATIONS] == [
        {
            CONF_LOCATION_ID: SECOND_LOCATION_ID,
            "title": "Cabin",
        }
    ]


async def test_select_location_step_add_all_skips_already_configured_locations(
    hass,
    token_response,
    location_response,
):
    """The location picker should only expose homes that are not configured."""
    existing_entry = build_config_entry()
    existing_entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.homely.config_flow.fetch_token_with_reason",
            AsyncMock(return_value=(token_response, None)),
        ),
        patch(
            "custom_components.homely.config_flow.get_location_id",
            AsyncMock(return_value=location_response),
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_USER},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                CONF_USERNAME: USERNAME,
                CONF_PASSWORD: PASSWORD,
            },
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={CONF_LOCATION_ID: SECOND_LOCATION_ID},
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Cabin"
    assert result["data"][CONF_LOCATION_ID] == SECOND_LOCATION_ID
    assert CONF_PENDING_IMPORT_LOCATIONS not in result["data"]


async def test_select_location_step_add_all_aborts_when_everything_is_configured(
    hass,
    token_response,
    location_response,
):
    """Setup should abort immediately if every available location already exists."""
    build_config_entry().add_to_hass(hass)
    build_config_entry(
        data_overrides={CONF_LOCATION_ID: SECOND_LOCATION_ID},
        unique_id=SECOND_LOCATION_ID,
    ).add_to_hass(hass)

    with (
        patch(
            "custom_components.homely.config_flow.fetch_token_with_reason",
            AsyncMock(return_value=(token_response, None)),
        ),
        patch(
            "custom_components.homely.config_flow.get_location_id",
            AsyncMock(return_value=location_response),
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_USER},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                CONF_USERNAME: USERNAME,
                CONF_PASSWORD: PASSWORD,
            },
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_select_location_step_accepts_single_remaining_home_after_filtering(
    hass,
    token_response,
    location_response,
):
    """A multi-home account can still add the only remaining unconfigured home."""
    build_config_entry().add_to_hass(hass)

    with (
        patch(
            "custom_components.homely.config_flow.fetch_token_with_reason",
            AsyncMock(return_value=(token_response, None)),
        ),
        patch(
            "custom_components.homely.config_flow.get_location_id",
            AsyncMock(return_value=location_response),
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_USER},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                CONF_USERNAME: USERNAME,
                CONF_PASSWORD: PASSWORD,
            },
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "select_location"


async def test_select_location_step_rejects_invalid_location(
    hass,
    token_response,
    location_response,
):
    """Unknown location ids should keep the user on the select form."""
    flow = HomelyConfigFlow()
    flow.hass = hass
    flow._pending_username = USERNAME
    flow._pending_password = PASSWORD
    flow._pending_locations = location_response

    result = await flow.async_step_select_location(
        user_input={CONF_LOCATION_ID: "does-not-exist"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "select_location"
    assert result["errors"] == {CONF_LOCATION_ID: "invalid_location"}


async def test_select_location_step_aborts_when_pending_state_is_missing(hass):
    """Selecting a location without pending credentials should abort cleanly."""
    flow = HomelyConfigFlow()
    flow.hass = hass

    result = await flow.async_step_select_location()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "unknown"


async def test_create_entry_for_location_rejects_missing_location_id(hass):
    """Location creation should abort if the payload lacks locationId."""
    flow = HomelyConfigFlow()
    flow.hass = hass

    result = await flow._create_entry_for_location(
        username=USERNAME,
        password=PASSWORD,
        location={"name": "No id"},
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "invalid_location"


async def test_import_step_creates_entry_for_additional_location(hass):
    """Internal import step should create additional location entries."""
    flow = HomelyConfigFlow()
    flow.hass = hass
    flow.context = {"source": config_entries.SOURCE_IMPORT}

    result = await flow.async_step_import(
        {
            CONF_USERNAME: USERNAME,
            CONF_PASSWORD: PASSWORD,
            CONF_LOCATION_ID: SECOND_LOCATION_ID,
            "title": "Cabin",
        }
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Cabin"
    assert result["data"] == {
        CONF_USERNAME: USERNAME,
        CONF_PASSWORD: PASSWORD,
        CONF_LOCATION_ID: SECOND_LOCATION_ID,
    }


async def test_duplicate_location_helper_honors_ignore_entry_and_unique_id(hass):
    """Duplicate detection should respect ignored entries and unique ids."""
    entry = build_config_entry(unique_id=LOCATION_ID)
    entry.add_to_hass(hass)
    second_entry = build_config_entry(
        data_overrides={CONF_LOCATION_ID: SECOND_LOCATION_ID},
        unique_id=SECOND_LOCATION_ID,
    )
    second_entry.add_to_hass(hass)

    flow = HomelyConfigFlow()
    flow.hass = hass

    assert flow._is_duplicate_location(None) is False
    assert (
        flow._is_duplicate_location(LOCATION_ID, ignore_entry_id=entry.entry_id)
        is False
    )
    assert flow._is_duplicate_location(SECOND_LOCATION_ID) is True


async def test_duplicate_location_helper_detects_unique_id_match_without_data_match(
    hass,
):
    """Duplicate detection should also consider entry unique ids."""
    entry = build_config_entry(
        data_overrides={CONF_LOCATION_ID: "different-location"},
        unique_id=SECOND_LOCATION_ID,
    )
    entry.add_to_hass(hass)

    flow = HomelyConfigFlow()
    flow.hass = hass

    assert flow._is_duplicate_location(SECOND_LOCATION_ID) is True


async def test_user_flow_rejects_duplicate_location(
    hass,
    token_response,
):
    """Trying to add the same location twice should abort cleanly."""
    existing_entry = build_config_entry()
    existing_entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.homely.config_flow.fetch_token_with_reason",
            AsyncMock(return_value=(token_response, None)),
        ),
        patch(
            "custom_components.homely.config_flow.get_location_id",
            AsyncMock(return_value=[{"locationId": LOCATION_ID, "name": "JF23"}]),
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_USER},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                CONF_USERNAME: USERNAME,
                CONF_PASSWORD: PASSWORD,
            },
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_user_flow_surfaces_invalid_auth_errors(hass):
    """Authentication failures should stay in the form with a user-facing error."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
    )

    with patch(
        "custom_components.homely.config_flow.fetch_token_with_reason",
        AsyncMock(return_value=(None, "invalid_auth")),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                CONF_USERNAME: USERNAME,
                CONF_PASSWORD: PASSWORD,
            },
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_user_flow_surfaces_no_homes_error(hass, token_response):
    """Empty accounts should surface a no_homes error."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
    )

    with (
        patch(
            "custom_components.homely.config_flow.fetch_token_with_reason",
            AsyncMock(return_value=(token_response, None)),
        ),
        patch(
            "custom_components.homely.config_flow.get_location_id",
            AsyncMock(return_value=[]),
        ),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                CONF_USERNAME: USERNAME,
                CONF_PASSWORD: PASSWORD,
            },
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "no_homes"}


async def test_reauth_updates_credentials_and_reloads_entry(
    hass,
    token_response,
    location_response,
):
    """Reauth should validate credentials and update the entry."""
    entry = build_config_entry()
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_REAUTH, "entry_id": entry.entry_id},
        data=entry.data,
    )

    with (
        patch(
            "custom_components.homely.config_flow.fetch_token_with_reason",
            AsyncMock(return_value=(token_response, None)),
        ),
        patch(
            "custom_components.homely.config_flow.get_location_id",
            AsyncMock(return_value=location_response),
        ),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                CONF_USERNAME: "new@example.com",
                CONF_PASSWORD: "new-secret",
            },
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_USERNAME] == "new@example.com"
    assert entry.data[CONF_PASSWORD] == "new-secret"


async def test_reauth_requires_current_location_to_still_exist(
    hass,
    token_response,
):
    """Reauth should fail if the account no longer exposes the configured location."""
    entry = build_config_entry()
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_REAUTH, "entry_id": entry.entry_id},
        data=entry.data,
    )

    with (
        patch(
            "custom_components.homely.config_flow.fetch_token_with_reason",
            AsyncMock(return_value=(token_response, None)),
        ),
        patch(
            "custom_components.homely.config_flow.get_location_id",
            AsyncMock(
                return_value=[{"locationId": SECOND_LOCATION_ID, "name": "Cabin"}]
            ),
        ),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={
                CONF_USERNAME: USERNAME,
                CONF_PASSWORD: PASSWORD,
            },
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_location"}


async def test_reauth_aborts_when_entry_is_missing(hass):
    """Reauth confirm should abort if the entry is no longer available."""
    flow = HomelyConfigFlow()
    flow.hass = hass
    flow._reauth_entry = None

    result = await flow.async_step_reauth_confirm()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "unknown"


async def test_reauth_surfaces_invalid_auth_errors(hass):
    """Reauth should stay on the form when new credentials are invalid."""
    entry = build_config_entry()
    entry.add_to_hass(hass)

    flow = HomelyConfigFlow()
    flow.hass = hass
    flow._reauth_entry = entry

    with patch(
        "custom_components.homely.config_flow.fetch_token_with_reason",
        AsyncMock(return_value=(None, "invalid_auth")),
    ):
        result = await flow.async_step_reauth_confirm(
            {CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_options_flow_updates_advanced_settings(hass):
    """Options flow should only manage runtime-tuning settings."""
    entry = build_config_entry()
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_SCAN_INTERVAL: 30,
            CONF_ENABLE_WEBSOCKET: True,
            CONF_POLL_WHEN_WEBSOCKET: False,
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        CONF_SCAN_INTERVAL: 30,
        CONF_ENABLE_WEBSOCKET: True,
        CONF_POLL_WHEN_WEBSOCKET: False,
    }


async def test_options_flow_rejects_invalid_scan_interval(hass):
    """Options flow schema should reject invalid scan intervals early."""
    entry = build_config_entry()
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    with pytest.raises(InvalidData):
        await hass.config_entries.options.async_configure(
            result["flow_id"],
            user_input={
                CONF_SCAN_INTERVAL: 5,
                CONF_ENABLE_WEBSOCKET: True,
                CONF_POLL_WHEN_WEBSOCKET: True,
            },
        )


async def test_options_flow_manual_step_shows_errors_and_coerces_defaults(hass):
    """Direct options step handling should return a form on invalid values."""
    entry = build_config_entry(
        options={CONF_SCAN_INTERVAL: "bad"},
    )
    entry.add_to_hass(hass)

    flow = HomelyOptionsFlow()
    flow.hass = hass

    with patch.object(
        HomelyOptionsFlow, "config_entry", new_callable=PropertyMock, return_value=entry
    ):
        result = await flow.async_step_init(
            {
                CONF_SCAN_INTERVAL: 5,
                CONF_ENABLE_WEBSOCKET: True,
                CONF_POLL_WHEN_WEBSOCKET: False,
            }
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_SCAN_INTERVAL: "invalid_scan_interval"}


def test_config_flow_does_not_expose_reconfigure_step():
    """Location changes should not be supported through reconfigure."""
    assert not hasattr(HomelyConfigFlow, "async_step_reconfigure")
