"""Package checks, setup, unload, tokens and stored energy."""

import json
import re
from importlib.metadata import version
from pathlib import Path

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import __version__ as HA_VERSION
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.loader import async_get_integration
from pytest_homeassistant_custom_component.common import MockConfigEntry

import ankerprime
from ankerprime.model import AuthenticationError, ChargerConnectionError

from custom_components.anker_prime.const import CONF_AUTHENTICATION, DOMAIN
from custom_components.anker_prime.storage import HomeAssistantStore
from tests.conftest import entry_data, find_device
from tests.fakes import (
    OTHER_SERIAL, SERIAL, FakeCharger, FakeCloud, make_authentication)


ROOT = Path(__file__).parent.parent
REQUIREMENT_PATTERN = re.compile(
    r'anker-prime-driver\[[a-z,]+\]==(?P<version>[0-9A-Za-z.+-]+)')


def test_versions_in_use() -> None:
    """Prints what the run is testing against (visible with -s or -v)."""

    print(f'Home Assistant {HA_VERSION}, anker-prime-driver '
          f'{ankerprime.__version__}')


async def test_manifest_loads(hass: HomeAssistant) -> None:
    integration = await async_get_integration(hass, DOMAIN)
    assert integration.domain == DOMAIN
    assert integration.version is not None
    assert integration.iot_class == 'cloud_push'


def test_manifest_requires_the_tested_library() -> None:
    """The manifest pins exactly the library version these tests ran with.

    Fails when the library working copy moved on: publish it and move the
    pin together.
    """

    manifest = json.loads(
        (ROOT / 'custom_components' / DOMAIN / 'manifest.json').read_text())
    matches = [REQUIREMENT_PATTERN.fullmatch(requirement)
               for requirement in manifest['requirements']]
    versions = [match['version'] for match in matches if match]
    assert versions == [version('anker-prime-driver')]


def test_minimum_home_assistant_version() -> None:
    hacs = json.loads((ROOT / 'hacs.json').read_text())
    minimum = tuple(int(part) for part in hacs['homeassistant'].split('.'))
    current = tuple(int(part) for part in
                    re.findall(r'\d+', HA_VERSION)[:3])
    assert current >= minimum


async def test_setup_creates_device_and_entities(
        hass: HomeAssistant, loaded: MockConfigEntry, cloud: FakeCloud,
        charger: FakeCharger) -> None:
    assert loaded.state is ConfigEntryState.LOADED
    assert charger.connected
    account = cloud.accounts[0]
    assert cloud.logins == []  # the stored token was used
    assert account.credentials is not None
    assert isinstance(account.energy_store, HomeAssistantStore)
    device = find_device(hass, loaded)
    assert (device.manufacturer, device.model, device.model_id) == (
        'Anker', 'Anker Prime Charger 250W', 'A2345')
    assert device.name == 'Desk charger'
    assert device.sw_version == '2.1.1.6'
    entities = er.async_entries_for_config_entry(er.async_get(hass),
                                                 loaded.entry_id)
    assert len(entities) > 60
    power = hass.states.get('sensor.desk_charger_c1_power')
    assert power is not None and power.state == '30.0'


async def test_unload_disconnects(hass: HomeAssistant,
                                  loaded: MockConfigEntry, cloud: FakeCloud,
                                  charger: FakeCharger) -> None:
    assert await hass.config_entries.async_unload(loaded.entry_id)
    assert loaded.state is ConfigEntryState.NOT_LOADED
    assert cloud.accounts[0].closed and not charger.connected


async def test_missing_token_signs_in_and_stores_it(
        hass: HomeAssistant, cloud: FakeCloud) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id='user-1',
                            data=entry_data(authentication=None))
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    assert len(cloud.logins) == 1
    assert entry.data[CONF_AUTHENTICATION]['auth_token'] == 'token-new'


async def test_new_token_is_stored(hass: HomeAssistant,
                                   loaded: MockConfigEntry,
                                   cloud: FakeCloud) -> None:
    listener = cloud.accounts[0].on_authentication
    assert listener is not None
    listener(make_authentication(token='token-2'))
    assert loaded.data[CONF_AUTHENTICATION]['auth_token'] == 'token-2'


@pytest.mark.parametrize(('stage', 'error', 'expected'), [
    ('devices', AuthenticationError('expired'), ConfigEntryState.SETUP_ERROR),
    ('devices', ChargerConnectionError('down'), ConfigEntryState.SETUP_RETRY),
    ('connect', ChargerConnectionError('down'), ConfigEntryState.SETUP_RETRY),
    ('connect', AuthenticationError('expired'), ConfigEntryState.SETUP_ERROR),
])
async def test_setup_failures(hass: HomeAssistant, cloud: FakeCloud,
                              charger: FakeCharger, entry: MockConfigEntry,
                              stage: str, error: Exception,
                              expected: ConfigEntryState) -> None:
    if stage == 'devices':
        cloud.devices_error = error
    else:
        charger.connect_error = error
    await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is expected
    assert cloud.accounts[0].closed
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    reauth = [flow for flow in flows if flow['context']['source'] == 'reauth']
    assert bool(reauth) == isinstance(error, AuthenticationError)


async def test_unbound_charger_is_skipped(hass: HomeAssistant,
                                          cloud: FakeCloud,
                                          caplog: pytest.LogCaptureFixture
                                          ) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id='user-1',
                            data=entry_data(serials=[SERIAL, OTHER_SERIAL]))
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    assert list(entry.runtime_data.coordinators) == [SERIAL]
    assert '...0001 is no longer bound' in caplog.text


async def test_energy_store_and_removal(hass: HomeAssistant,
                                        loaded: MockConfigEntry) -> None:
    store = HomeAssistantStore(hass)
    await store.save('energy-' + SERIAL.lower(), {'version': 1})
    assert await store.load('energy-' + SERIAL.lower()) == {'version': 1}
    await hass.config_entries.async_remove(loaded.entry_id)
    assert await HomeAssistantStore(hass).load(
        'energy-' + SERIAL.lower()) is None
