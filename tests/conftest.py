"""Shared fixtures: custom integrations enabled, the fake cloud, an entry."""

from collections.abc import Iterator
from typing import Any
from unittest.mock import patch

import pytest
from homeassistant.const import (
    CONF_ADDRESS, CONF_COUNTRY, CONF_EMAIL, CONF_PASSWORD)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.anker_prime.const import (
    CONF_AUTHENTICATION, CONF_CLIENT_ID, CONF_CONNECTION, CONF_OWNER_ID,
    CONF_SERIAL, CONF_SERIALS, CONNECTION_BLUETOOTH, DOMAIN,
    OPTION_UPDATE_INTERVAL)
from tests.fakes import (
    BLE_ADDRESS, BLE_SERIAL, COUNTRY, EMAIL, PASSWORD, SERIAL, USER_ID,
    FakeBluetooth, FakeCharger, FakeCloud, FakeCloudAccount,
    make_authentication)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None,
                                    mock_bluetooth: None) -> None:
    """Custom integrations on; Bluetooth set up without real adapters."""


@pytest.fixture
def bluetooth() -> Iterator[FakeBluetooth]:
    """Fake Bluetooth stack and charger factory for 160W entries."""

    fake = FakeBluetooth()
    with (patch('custom_components.anker_prime.ble.ble_charger',
                fake.ble_charger),
          patch('custom_components.anker_prime.ble.bluetooth.'
                'async_ble_device_from_address', fake.ble_device),
          patch('custom_components.anker_prime.config_flow.'
                'async_discovered_service_info',
                fake.discovered_service_info)):
        yield fake


def ble_entry_data(**overrides: Any) -> dict[str, Any]:
    data = {CONF_CONNECTION: CONNECTION_BLUETOOTH, CONF_ADDRESS: BLE_ADDRESS,
            CONF_SERIAL: BLE_SERIAL, CONF_OWNER_ID: None,
            CONF_COUNTRY: 'DE', CONF_CLIENT_ID: 'c' * 40}
    data.update(overrides)
    return data


@pytest.fixture
def ble_entry(hass: HomeAssistant) -> MockConfigEntry:
    config_entry = MockConfigEntry(domain=DOMAIN,
                                   title='Anker Prime 160W 1771',
                                   unique_id=BLE_ADDRESS,
                                   data=ble_entry_data(),
                                   options={OPTION_UPDATE_INTERVAL: 0})
    config_entry.add_to_hass(hass)
    return config_entry


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
