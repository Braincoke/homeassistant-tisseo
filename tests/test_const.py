"""Tests for Tisseo constants and defaults."""
import pytest

from custom_components.tisseo.const import (
    ALERT_CACHE_DURATION,
    API_BASE_URL,
    API_TIMEOUT,
    ATTRIBUTION,
    CONF_API_KEY,
    CONF_DEBUG,
    CONF_IMMINENT_THRESHOLD,
    CONF_LINE,
    CONF_ACTIVE_WINDOWS,
    CONF_INACTIVE_INTERVAL,
    CONF_MESSAGES_REFRESH_INTERVAL,
    CONF_OUTAGES_REFRESH_INTERVAL,
    CONF_ROUTE,
    CONF_SCHEDULE_ENABLED,
    CONF_STATIC_INTERVAL,
    CONF_STOP_ID,
    CONF_UPDATE_STRATEGY,
    CONF_USE_MOCK,
    CONF_WINDOW_DAYS,
    CONF_WINDOW_END,
    CONF_WINDOW_NAME,
    CONF_WINDOW_START,
    COUNTDOWN_UPDATE_INTERVAL,
    DAYS_OF_WEEK,
    DAY_TO_WEEKDAY,
    DEFAULT_INACTIVE_INTERVAL,
    DEFAULT_IMMINENT_THRESHOLD,
    DEFAULT_MESSAGES_REFRESH_INTERVAL,
    DEFAULT_OUTAGES_REFRESH_INTERVAL,
    DEFAULT_SCHEDULE_ENABLED,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_STATIC_INTERVAL,
    DEFAULT_UPDATE_STRATEGY,
    DEVICE_MANUFACTURER,
    DEVICE_MODEL,
    DOMAIN,
    SMART_POST_DEPARTURE_SECONDS,
    SMART_PRE_DEPARTURE_SECONDS,
    UPDATE_STRATEGY_SMART,
    UPDATE_STRATEGY_STATIC,
    UPDATE_STRATEGY_TIME_WINDOW,
)


class TestDomainConstants:
    """Test basic domain constants."""

    def test_domain(self):
        assert DOMAIN == "tisseo"

    def test_api_base_url(self):
        assert API_BASE_URL.startswith("https://")
        assert "tisseo" in API_BASE_URL

    def test_attribution(self):
        assert "Tisseo" in ATTRIBUTION


class TestConfigKeys:
    """Test that config keys are valid strings."""

    def test_config_keys_are_strings(self):
        keys = [
            CONF_API_KEY, CONF_USE_MOCK, CONF_DEBUG,
            CONF_STOP_ID, CONF_LINE, CONF_ROUTE,
            CONF_UPDATE_STRATEGY, CONF_STATIC_INTERVAL,
            CONF_IMMINENT_THRESHOLD,
            CONF_SCHEDULE_ENABLED, CONF_ACTIVE_WINDOWS,
            CONF_MESSAGES_REFRESH_INTERVAL, CONF_OUTAGES_REFRESH_INTERVAL,
            CONF_INACTIVE_INTERVAL, CONF_WINDOW_DAYS,
            CONF_WINDOW_START, CONF_WINDOW_END, CONF_WINDOW_NAME,
        ]
        for key in keys:
            assert isinstance(key, str)
            assert len(key) > 0

    def test_config_keys_are_unique(self):
        keys = [
            CONF_API_KEY, CONF_USE_MOCK, CONF_DEBUG,
            CONF_STOP_ID, CONF_LINE, CONF_ROUTE,
            CONF_UPDATE_STRATEGY, CONF_STATIC_INTERVAL,
            CONF_MESSAGES_REFRESH_INTERVAL, CONF_OUTAGES_REFRESH_INTERVAL,
            CONF_SCHEDULE_ENABLED, CONF_ACTIVE_WINDOWS,
            CONF_INACTIVE_INTERVAL, CONF_WINDOW_DAYS,
            CONF_WINDOW_START, CONF_WINDOW_END, CONF_WINDOW_NAME,
        ]
        assert len(keys) == len(set(keys))


class TestDefaults:
    """Test default values are reasonable."""

    def test_default_strategy_is_smart(self):
        assert DEFAULT_UPDATE_STRATEGY == UPDATE_STRATEGY_SMART

    def test_smart_strategy_value(self):
        assert UPDATE_STRATEGY_SMART == "smart"

    def test_static_strategy_value(self):
        assert UPDATE_STRATEGY_STATIC == "static"

    def test_time_window_strategy_value(self):
        assert UPDATE_STRATEGY_TIME_WINDOW == "time_window"

    def test_default_imminent_threshold(self):
        assert DEFAULT_IMMINENT_THRESHOLD == 2
        assert DEFAULT_IMMINENT_THRESHOLD > 0

    def test_default_scan_interval(self):
        assert DEFAULT_SCAN_INTERVAL == 60
        assert DEFAULT_SCAN_INTERVAL >= 30  # Don't poll too aggressively

    def test_default_static_interval(self):
        assert DEFAULT_STATIC_INTERVAL == 60
        assert DEFAULT_STATIC_INTERVAL >= 30

    def test_default_alert_refresh_intervals(self):
        assert DEFAULT_MESSAGES_REFRESH_INTERVAL == ALERT_CACHE_DURATION
        assert DEFAULT_OUTAGES_REFRESH_INTERVAL == ALERT_CACHE_DURATION
        assert DEFAULT_MESSAGES_REFRESH_INTERVAL >= 0
        assert DEFAULT_OUTAGES_REFRESH_INTERVAL >= 0


class TestSmartUpdateTiming:
    """Test smart update timing constants."""

    def test_pre_departure_seconds(self):
        assert SMART_PRE_DEPARTURE_SECONDS == 60
        assert SMART_PRE_DEPARTURE_SECONDS > 0

    def test_post_departure_seconds(self):
        assert SMART_POST_DEPARTURE_SECONDS == 20
        assert SMART_POST_DEPARTURE_SECONDS > 0

    def test_countdown_interval(self):
        assert COUNTDOWN_UPDATE_INTERVAL == 30
        assert COUNTDOWN_UPDATE_INTERVAL > 0

    def test_alert_cache_duration(self):
        assert ALERT_CACHE_DURATION == 300  # 5 minutes
        assert ALERT_CACHE_DURATION >= 60  # At least 1 minute

    def test_api_timeout(self):
        assert API_TIMEOUT == 10
        assert API_TIMEOUT > 0
        assert API_TIMEOUT <= 30  # Don't wait too long


class TestScheduleConstants:
    """Test schedule-related constants and defaults."""

    def test_schedule_defaults(self):
        assert DEFAULT_SCHEDULE_ENABLED is False
        assert DEFAULT_INACTIVE_INTERVAL == 0

    def test_days_of_week_shape(self):
        assert len(DAYS_OF_WEEK) == 7
        assert all("value" in day and "label" in day for day in DAYS_OF_WEEK)

    def test_day_to_weekday_mapping(self):
        assert DAY_TO_WEEKDAY["mon"] == 0
        assert DAY_TO_WEEKDAY["tue"] == 1
        assert DAY_TO_WEEKDAY["wed"] == 2
        assert DAY_TO_WEEKDAY["thu"] == 3
        assert DAY_TO_WEEKDAY["fri"] == 4
        assert DAY_TO_WEEKDAY["sat"] == 5
        assert DAY_TO_WEEKDAY["sun"] == 6


class TestDeviceInfo:
    """Test device metadata constants."""

    def test_manufacturer(self):
        assert DEVICE_MANUFACTURER == "Tisseo"

    def test_model(self):
        assert isinstance(DEVICE_MODEL, str)
        assert len(DEVICE_MODEL) > 0
