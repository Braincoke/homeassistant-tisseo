"""Tests for time-window handling in the single-step options form."""

import pytest

from custom_components.tisseo.config_flow import (
    TisseoOptionsFlowHandler,
)
from custom_components.tisseo.const import (
    CONF_ACTIVE_WINDOWS,
    CONF_DEBUG,
    CONF_IMMINENT_THRESHOLD,
    CONF_MESSAGES_REFRESH_INTERVAL,
    CONF_OUTAGES_REFRESH_INTERVAL,
    CONF_SCHEDULE_ENABLED,
    CONF_STATIC_INTERVAL,
    CONF_STOP_ID,
    CONF_UPDATE_STRATEGY,
    CONF_WINDOW_DAYS,
    CONF_WINDOW_END,
    CONF_WINDOW_NAME,
    CONF_WINDOW_START,
    DEFAULT_IMMINENT_THRESHOLD,
    DEFAULT_STATIC_INTERVAL,
    UPDATE_STRATEGY_SMART,
    UPDATE_STRATEGY_TIME_WINDOW,
)


class _DummyConfigEntry:
    """Minimal config entry stub for options flow tests."""

    def __init__(self, *, data: dict | None = None, options: dict | None = None) -> None:
        self.data = data or {}
        self.options = options or {}


@pytest.mark.asyncio
async def test_init_non_window_mode_clears_schedule() -> None:
    """Switching away from time windows should disable schedule fields."""
    handler = TisseoOptionsFlowHandler(
        _DummyConfigEntry(
            options={
                CONF_UPDATE_STRATEGY: UPDATE_STRATEGY_TIME_WINDOW,
                CONF_ACTIVE_WINDOWS: [
                    {
                        CONF_WINDOW_DAYS: ["mon"],
                        CONF_WINDOW_START: "06:00:00",
                        CONF_WINDOW_END: "09:00:00",
                    }
                ],
            }
        )
    )
    handler._strategy_override = UPDATE_STRATEGY_SMART
    handler.async_create_entry = lambda title, data: {
        "type": "create_entry",
        "title": title,
        "data": data,
    }

    result = await handler.async_step_init(
        {
            CONF_STATIC_INTERVAL: DEFAULT_STATIC_INTERVAL,
            CONF_DEBUG: False,
            CONF_MESSAGES_REFRESH_INTERVAL: 600,
            CONF_OUTAGES_REFRESH_INTERVAL: 900,
        }
    )

    assert result["type"] == "create_entry"
    assert result["data"][CONF_SCHEDULE_ENABLED] is False
    assert result["data"][CONF_ACTIVE_WINDOWS] == []
    assert result["data"][CONF_MESSAGES_REFRESH_INTERVAL] == 600
    assert result["data"][CONF_OUTAGES_REFRESH_INTERVAL] == 900


@pytest.mark.asyncio
async def test_init_time_window_saves_multiple_windows() -> None:
    """Submitting time-window mode should normalize and store all windows."""
    handler = TisseoOptionsFlowHandler(_DummyConfigEntry())
    handler._strategy_override = UPDATE_STRATEGY_TIME_WINDOW
    handler.async_create_entry = lambda title, data: {
        "type": "create_entry",
        "title": title,
        "data": data,
    }

    result = await handler.async_step_init(
        {
            CONF_STATIC_INTERVAL: DEFAULT_STATIC_INTERVAL,
            CONF_DEBUG: False,
            CONF_MESSAGES_REFRESH_INTERVAL: 420,
            CONF_OUTAGES_REFRESH_INTERVAL: 840,
            CONF_ACTIVE_WINDOWS: [
                {
                    CONF_WINDOW_NAME: " Morning commute ",
                    CONF_WINDOW_DAYS: ["mon", "thu", "fri"],
                    CONF_WINDOW_START: "06:00:00",
                    CONF_WINDOW_END: "09:30:00",
                },
                {
                    CONF_WINDOW_DAYS: ["sat"],
                    CONF_WINDOW_START: "10:00",
                    CONF_WINDOW_END: "12:00",
                },
            ],
        }
    )

    assert result["type"] == "create_entry"
    assert result["data"][CONF_SCHEDULE_ENABLED] is True
    assert result["data"][CONF_MESSAGES_REFRESH_INTERVAL] == 420
    assert result["data"][CONF_OUTAGES_REFRESH_INTERVAL] == 840
    assert result["data"][CONF_ACTIVE_WINDOWS] == [
        {
            CONF_WINDOW_NAME: "Morning commute",
            CONF_WINDOW_DAYS: ["mon", "thu", "fri"],
            CONF_WINDOW_START: "06:00",
            CONF_WINDOW_END: "09:30",
        },
        {
            CONF_WINDOW_DAYS: ["sat"],
            CONF_WINDOW_START: "10:00",
            CONF_WINDOW_END: "12:00",
        },
    ]


@pytest.mark.asyncio
async def test_init_time_window_requires_at_least_one_window() -> None:
    """Submitting time-window mode without windows should fail validation."""
    handler = TisseoOptionsFlowHandler(_DummyConfigEntry())
    handler._strategy_override = UPDATE_STRATEGY_TIME_WINDOW
    handler.async_show_form = lambda **kwargs: kwargs

    result = await handler.async_step_init(
        {
            CONF_STATIC_INTERVAL: DEFAULT_STATIC_INTERVAL,
            CONF_DEBUG: False,
            CONF_ACTIVE_WINDOWS: [],
        }
    )

    assert result["step_id"] == "init"
    assert result["errors"]["base"] == "no_windows_configured"


@pytest.mark.asyncio
async def test_init_time_window_rejects_invalid_time_range() -> None:
    """A window with start >= end should be rejected."""
    handler = TisseoOptionsFlowHandler(_DummyConfigEntry())
    handler._strategy_override = UPDATE_STRATEGY_TIME_WINDOW
    handler.async_show_form = lambda **kwargs: kwargs

    result = await handler.async_step_init(
        {
            CONF_STATIC_INTERVAL: DEFAULT_STATIC_INTERVAL,
            CONF_DEBUG: False,
            CONF_ACTIVE_WINDOWS: [
                {
                    CONF_WINDOW_NAME: "Invalid",
                    CONF_WINDOW_DAYS: ["mon"],
                    CONF_WINDOW_START: "10:00:00",
                    CONF_WINDOW_END: "09:59:00",
                }
            ],
        }
    )

    assert result["step_id"] == "init"
    assert result["errors"]["base"] == "invalid_time_range"


@pytest.mark.asyncio
async def test_stop_entry_options_only_updates_imminent_threshold() -> None:
    """Stop-entry options should keep global keys and only change threshold."""
    handler = TisseoOptionsFlowHandler(
        _DummyConfigEntry(
            data={CONF_STOP_ID: "1234"},
            options={CONF_STATIC_INTERVAL: 120, CONF_IMMINENT_THRESHOLD: 2},
        )
    )
    handler.async_create_entry = lambda title, data: {
        "type": "create_entry",
        "title": title,
        "data": data,
    }

    result = await handler.async_step_init({CONF_IMMINENT_THRESHOLD: 7})

    assert result["type"] == "create_entry"
    assert result["data"][CONF_IMMINENT_THRESHOLD] == 7
    assert result["data"][CONF_STATIC_INTERVAL] == 120
