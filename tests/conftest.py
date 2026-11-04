"""Shared fixtures: custom integrations enabled, the fake cloud, an entry."""

from collections.abc import Iterator
from typing import Any
from unittest.mock import patch

import pytest
from homeassistant.const import CONF_COUNTRY, CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.anker_prime.const import (
    CONF_AUTHENTICATION, CONF_SERIALS, DOMAIN, OPTION_UPDATE_INTERVAL)
from tests.fakes import (
    COUNTRY, EMAIL, PASSWORD, SERIAL, USER_ID, FakeCharger, FakeCloud,
    FakeCloudAccount, make_authentication)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    pass


@pytest.fixture
def cloud() -> Iterator[FakeCloud]:
    """The fake Anker cloud, patched in for the library's CloudAccount."""

    fake = FakeCloud()
    account_class = type('PatchedAccount', (FakeCloudAccount,),
                         {'cloud': fake})
    with patch('custom_components.anker_prime.account.CloudAccount',
               account_class):
        yield fake


@pytest.fixture
def charger(cloud: FakeCloud) -> FakeCharger:
    return cloud.chargers[SERIAL]


def find_device(hass: HomeAssistant, entry: MockConfigEntry,
                serial: str = SERIAL) -> dr.DeviceEntry:
    """The registry device of a charger (works on old and new releases)."""

    devices = [device for device in dr.async_entries_for_config_entry(
        dr.async_get(hass), entry.entry_id)
        if (DOMAIN, serial) in device.identifiers]
    assert len(devices) == 1
    return devices[0]


def entry_data(**overrides: Any) -> dict[str, Any]:
    data = {CONF_EMAIL: EMAIL, CONF_PASSWORD: PASSWORD,
            CONF_COUNTRY: COUNTRY,
            CONF_AUTHENTICATION: make_authentication().to_document(),
            CONF_SERIALS: [SERIAL]}
    data.update(overrides)
    return data


@pytest.fixture
def entry(hass: HomeAssistant) -> MockConfigEntry:
    config_entry = MockConfigEntry(domain=DOMAIN, title=EMAIL,
                                   unique_id=USER_ID, data=entry_data(),
                                   options={OPTION_UPDATE_INTERVAL: 0})
    config_entry.add_to_hass(hass)
    return config_entry


@pytest.fixture
async def loaded(hass: HomeAssistant, cloud: FakeCloud,
                 entry: MockConfigEntry) -> MockConfigEntry:
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry
