"""Update throttling, offline repair issue and reauthentication."""

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry, async_fire_time_changed)

from ankerprime.model import AuthenticationError, ChargerState, PortId

from custom_components.anker_prime.const import (
    DOMAIN, OPTION_UPDATE_INTERVAL)
from tests.conftest import find_device
from tests.fakes import SERIAL, FakeCharger, make_state


TOTAL_ENERGY = 'sensor.desk_charger_total_energy'


def energy(hass: HomeAssistant) -> str:
    state = hass.states.get(TOTAL_ENERGY)
    assert state is not None
    return state.state


def state_with_energy(value: float, available: bool = True) -> ChargerState:
    return make_state(available=available, energy={PortId.C1: value})


async def test_updates_are_throttled(hass: HomeAssistant, cloud: object,
                                     entry: MockConfigEntry,
                                     charger: FakeCharger,
                                     freezer: FrozenDateTimeFactory) -> None:
    hass.config_entries.async_update_entry(
        entry, options={OPTION_UPDATE_INTERVAL: 10})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    charger.push(state_with_energy(1.0))
    await hass.async_block_till_done()
    assert energy(hass) == '1.0'
    charger.push(state_with_energy(2.0))
    charger.push(state_with_energy(3.0))
    await hass.async_block_till_done()
    assert energy(hass) == '1.0'
    freezer.tick(timedelta(seconds=11))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert energy(hass) == '3.0'


async def test_availability_change_passes_at_once(
        hass: HomeAssistant, cloud: object, entry: MockConfigEntry,
        charger: FakeCharger) -> None:
    hass.config_entries.async_update_entry(
        entry, options={OPTION_UPDATE_INTERVAL: 300})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    charger.push(state_with_energy(1.0))
    charger.push(state_with_energy(1.0, available=False))
    await hass.async_block_till_done()
    state = hass.states.get('sensor.desk_charger_c1_power')
    assert state is not None and state.state == 'unavailable'


async def test_offline_issue_is_raised_and_cleared(
        hass: HomeAssistant, loaded: MockConfigEntry, charger: FakeCharger,
        freezer: FrozenDateTimeFactory) -> None:
    issues = ir.async_get(hass)
    charger.push(make_state(available=False))
    await hass.async_block_till_done()
    freezer.tick(timedelta(minutes=31))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    issue = issues.async_get_issue(DOMAIN, f'offline_{SERIAL}')
    assert issue is not None
    assert issue.translation_placeholders == {'name': 'Desk charger'}
    charger.push(make_state(available=True))
    await hass.async_block_till_done()
    assert issues.async_get_issue(DOMAIN, f'offline_{SERIAL}') is None


async def test_lost_authentication_starts_reauth(
        hass: HomeAssistant, loaded: MockConfigEntry, charger: FakeCharger,
        freezer: FrozenDateTimeFactory) -> None:
    charger.set_last_error(AuthenticationError('token revoked'))
    for _ in range(2):
        freezer.tick(timedelta(minutes=1, seconds=1))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [flow['context']['source'] for flow in flows] == ['reauth']


async def test_firmware_update_reaches_device_registry(
        hass: HomeAssistant, loaded: MockConfigEntry,
        charger: FakeCharger) -> None:
    charger.push(make_state(firmware='2.1.1.7'))
    await hass.async_block_till_done()
    assert find_device(hass, loaded).sw_version == '2.1.1.7'
