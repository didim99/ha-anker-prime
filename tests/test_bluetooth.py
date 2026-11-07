"""160W Bluetooth entries: flows, setup, entities, reauth, options."""

import re
from datetime import timedelta

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.select import ATTR_OPTION, SERVICE_SELECT_OPTION
from homeassistant.config_entries import (
    SOURCE_BLUETOOTH, SOURCE_USER, ConfigEntryState, ConfigFlowResult)
from homeassistant.const import (
    ATTR_ENTITY_ID, CONF_ADDRESS, CONF_COUNTRY, SERVICE_TURN_ON)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry, async_fire_time_changed)
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from ankerprime.model import (
    AccountRefusedError, ChargerConnectionError, DisplayLanguage,
    OutputId, ScreenOrientation)

from custom_components.anker_prime.const import (
    CONF_CLIENT_ID, CONF_CONNECTION, CONF_OWNER_ID, CONF_SERIAL,
    CONNECTION_BLUETOOTH, DOMAIN, OPTION_KEEP_CONNECTION,
    OPTION_READ_INTERVAL, OPTION_UPDATE_INTERVAL)
from custom_components.anker_prime.storage import HomeAssistantStore
from tests.conftest import find_device
from tests.fakes import (
    BLE_ADDRESS, BLE_SERIAL, USER_ID, FakeBluetooth, make_ble_state,
    make_service_info)


CONFIRM_INPUT = {CONF_OWNER_ID: ' owner-1 ', CONF_COUNTRY: 'DE'}


@pytest.fixture
async def ble_loaded(hass: HomeAssistant, bluetooth: FakeBluetooth,
                     ble_entry: MockConfigEntry) -> MockConfigEntry:
    assert await hass.config_entries.async_setup(ble_entry.entry_id)
    await hass.async_block_till_done()
    return ble_entry


def suggested(result: ConfigFlowResult, key: str) -> object:
    assert result['data_schema'] is not None
    field = next(field for field in result['data_schema'].schema
                 if field == key)
    return (field.description or {}).get('suggested_value')


async def test_discovery_flow_creates_entry(hass: HomeAssistant,
                                            bluetooth: FakeBluetooth) -> None:
    MockConfigEntry(domain=DOMAIN, unique_id=USER_ID,
                    data={}).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={'source': SOURCE_BLUETOOTH},
        data=make_service_info())
    assert result['type'] is FlowResultType.FORM
    assert result['step_id'] == 'bluetooth_confirm'
    assert suggested(result, CONF_OWNER_ID) == USER_ID
    result = await hass.config_entries.flow.async_configure(
        result['flow_id'], CONFIRM_INPUT)
    assert result['type'] is FlowResultType.CREATE_ENTRY
    assert result['title'] == 'Anker Prime 160W 1771'
    assert result['result'].unique_id == BLE_ADDRESS
    data = result['data']
    assert data[CONF_CONNECTION] == CONNECTION_BLUETOOTH
    assert data[CONF_SERIAL] == BLE_SERIAL
    assert data[CONF_OWNER_ID] == 'owner-1'
    assert re.fullmatch('[0-9a-f]{40}', data[CONF_CLIENT_ID])
    probe = bluetooth.factory_calls[0]
    assert probe['keep_connection'] is False
    assert probe['energy_store'] is None
    assert probe['owner_id'] == 'owner-1'
    assert probe['country'] == 'DE'


async def test_discovery_of_a_configured_charger_aborts(
        hass: HomeAssistant, bluetooth: FakeBluetooth,
        ble_entry: MockConfigEntry) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={'source': SOURCE_BLUETOOTH},
        data=make_service_info())
    assert result['type'] is FlowResultType.ABORT
    assert result['reason'] == 'already_configured'


async def test_pick_lists_unconfigured_chargers(
        hass: HomeAssistant, bluetooth: FakeBluetooth) -> None:
    bluetooth.discovered.append(make_service_info('AA:BB:CC:DD:EE:02',
                                                  'Speaker'))
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={'source': SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result['flow_id'], {'next_step_id': 'bluetooth_pick'})
    assert result['step_id'] == 'bluetooth_pick'
    schema = result['data_schema'].schema  # type: ignore[union-attr]
    options = next(iter(schema.values())).config['options']
    assert [option['value'] for option in options] == [BLE_ADDRESS]
    result = await hass.config_entries.flow.async_configure(
        result['flow_id'], {CONF_ADDRESS: BLE_ADDRESS})
    assert result['step_id'] == 'bluetooth_confirm'
    result = await hass.config_entries.flow.async_configure(
        result['flow_id'], {CONF_COUNTRY: 'US'})
    assert result['type'] is FlowResultType.CREATE_ENTRY
    assert result['data'][CONF_OWNER_ID] is None


async def test_pick_without_chargers_aborts(
        hass: HomeAssistant, bluetooth: FakeBluetooth,
        ble_entry: MockConfigEntry) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={'source': SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result['flow_id'], {'next_step_id': 'bluetooth_pick'})
    assert result['type'] is FlowResultType.ABORT
    assert result['reason'] == 'no_devices_found'


@pytest.mark.parametrize(('failure', 'key'), [
    ('out_of_range', 'not_in_range'),
    (AccountRefusedError('refused'), 'owner_refused'),
    (ChargerConnectionError('busy'), 'cannot_connect'),
    (RuntimeError('boom'), 'unknown'),
])
async def test_confirm_errors_then_recovery(
        hass: HomeAssistant, bluetooth: FakeBluetooth,
        failure: Exception | str, key: str) -> None:
    if isinstance(failure, Exception):
        bluetooth.charger.connect_error = failure
    else:
        bluetooth.in_range = False
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={'source': SOURCE_BLUETOOTH},
        data=make_service_info())
    result = await hass.config_entries.flow.async_configure(
        result['flow_id'], CONFIRM_INPUT)
    assert result['errors'] == {'base': key}
    assert not bluetooth.charger.connected
    bluetooth.charger.connect_error = None
    bluetooth.in_range = True
    result = await hass.config_entries.flow.async_configure(
        result['flow_id'], CONFIRM_INPUT)
    assert result['type'] is FlowResultType.CREATE_ENTRY


async def test_charger_without_serial_is_refused(
        hass: HomeAssistant, bluetooth: FakeBluetooth) -> None:
    bluetooth.charger.push(make_ble_state(serial=None))
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={'source': SOURCE_BLUETOOTH},
        data=make_service_info())
    result = await hass.config_entries.flow.async_configure(
        result['flow_id'], CONFIRM_INPUT)
    assert result['errors'] == {'base': 'cannot_connect'}


async def test_setup_builds_the_charger_and_entities(
        hass: HomeAssistant, bluetooth: FakeBluetooth,
        ble_loaded: MockConfigEntry) -> None:
    assert ble_loaded.state is ConfigEntryState.LOADED
    call = bluetooth.factory_calls[-1]
    assert call['keep_connection'] is True
    assert call['client_id'] == 'c' * 40
    assert call['owner_id'] is None
    assert call['country'] == 'DE'
    assert call['info'].serial == BLE_SERIAL
    assert isinstance(call['energy_store'], HomeAssistantStore)
    assert call['timings'].update_interval == 60
    assert call['ble_device_callback']() is not None
    assert bluetooth.charger.connected
    device = find_device(hass, ble_loaded, BLE_SERIAL)
    assert (dr.CONNECTION_BLUETOOTH, BLE_ADDRESS) in device.connections
    assert device.model_id == 'A2687'
    state = hass.states.get('sensor.anker_prime_160w_1771_c1_power')
    assert state is not None and state.state == '20.0'
    registry = er.async_get(hass)
    for entity_id, enabled in (
            ('select.anker_prime_160w_1771_display_language', True),
            ('select.anker_prime_160w_1771_screen_orientation', True),
            ('switch.anker_prime_160w_1771_auto_rotation', True),
            ('select.anker_prime_160w_1771_fixed_allocation', False),
            ('switch.anker_prime_160w_1771_c1_output', False)):
        entry = registry.async_get(entity_id)
        assert entry is not None, entity_id
        assert (entry.disabled_by is None) == enabled, entity_id
    assert registry.async_get('switch.anker_prime_160w_1771_ufcs') is None


async def test_160w_commands(hass: HomeAssistant, bluetooth: FakeBluetooth,
                             ble_loaded: MockConfigEntry) -> None:
    await hass.services.async_call(
        'select', SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: 'select.anker_prime_160w_1771_display_language',
         ATTR_OPTION: 'de'}, blocking=True)
    await hass.services.async_call(
        'select', SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: 'select.anker_prime_160w_1771_screen_orientation',
         ATTR_OPTION: 'left'}, blocking=True)
    await hass.services.async_call(
        'switch', SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: 'switch.anker_prime_160w_1771_auto_rotation'},
        blocking=True)
    assert bluetooth.charger.calls == [
        ('set_display_language', (DisplayLanguage.GERMAN,)),
        ('set_screen_orientation', (ScreenOrientation.LEFT,)),
        ('set_auto_rotation', (True,))]
    language = hass.states.get('select.anker_prime_160w_1771_display_language')
    assert language is not None and language.state == 'unknown'
    assert OutputId.C1 in bluetooth.charger.state.outputs


async def test_setup_retries_when_out_of_range(
        hass: HomeAssistant, bluetooth: FakeBluetooth,
        ble_entry: MockConfigEntry) -> None:
    bluetooth.in_range = False
    await hass.config_entries.async_setup(ble_entry.entry_id)
    await hass.async_block_till_done()
    assert ble_entry.state is ConfigEntryState.SETUP_RETRY


@pytest.mark.parametrize(('error', 'expected', 'reauth'), [
    (ChargerConnectionError('busy'), ConfigEntryState.SETUP_RETRY, False),
    (AccountRefusedError('refused'), ConfigEntryState.SETUP_ERROR, True),
])
async def test_setup_failures(hass: HomeAssistant, bluetooth: FakeBluetooth,
                              ble_entry: MockConfigEntry, error: Exception,
                              expected: ConfigEntryState,
                              reauth: bool) -> None:
    bluetooth.charger.connect_error = error
    await hass.config_entries.async_setup(ble_entry.entry_id)
    await hass.async_block_till_done()
    assert ble_entry.state is expected
    flows = hass.config_entries.flow.async_progress()
    assert any(flow['context']['source'] == 'reauth'
               for flow in flows) == reauth


async def test_unload_disconnects(hass: HomeAssistant,
                                  bluetooth: FakeBluetooth,
                                  ble_loaded: MockConfigEntry) -> None:
    assert await hass.config_entries.async_unload(ble_loaded.entry_id)
    assert not bluetooth.charger.connected


async def test_refused_identity_starts_owner_reauth(
        hass: HomeAssistant, bluetooth: FakeBluetooth,
        ble_loaded: MockConfigEntry,
        freezer: FrozenDateTimeFactory) -> None:
    bluetooth.charger.set_last_error(AccountRefusedError('refused'))
    freezer.tick(timedelta(minutes=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    [flow] = [flow for flow in hass.config_entries.flow.async_progress()
              if flow['context']['source'] == 'reauth']
    assert flow['step_id'] == 'reauth_owner'
    bluetooth.charger.set_last_error(None)
    result = await hass.config_entries.flow.async_configure(
        flow['flow_id'], {CONF_OWNER_ID: 'owner-2'})
    assert result['type'] is FlowResultType.ABORT
    assert result['reason'] == 'reauth_successful'
    assert ble_loaded.data[CONF_OWNER_ID] == 'owner-2'


async def test_owner_reauth_errors(hass: HomeAssistant,
                                   bluetooth: FakeBluetooth,
                                   ble_entry: MockConfigEntry) -> None:
    result = await ble_entry.start_reauth_flow(hass)
    assert result['step_id'] == 'reauth_owner'
    bluetooth.charger.connect_error = AccountRefusedError('refused')
    result = await hass.config_entries.flow.async_configure(
        result['flow_id'], {CONF_OWNER_ID: 'wrong'})
    assert result['errors'] == {'base': 'owner_refused'}
    bluetooth.charger.connect_error = None
    bluetooth.charger.push(make_ble_state(serial='ASHDOTHER0000001'))
    result = await hass.config_entries.flow.async_configure(
        result['flow_id'], {CONF_OWNER_ID: 'owner'})
    assert result['type'] is FlowResultType.ABORT
    assert result['reason'] == 'wrong_charger'


async def test_options(hass: HomeAssistant, bluetooth: FakeBluetooth,
                       ble_loaded: MockConfigEntry) -> None:
    result = await hass.config_entries.options.async_init(
        ble_loaded.entry_id)
    assert result['step_id'] == 'bluetooth'
    result = await hass.config_entries.options.async_configure(
        result['flow_id'], {OPTION_UPDATE_INTERVAL: 10,
                            OPTION_KEEP_CONNECTION: False,
                            OPTION_READ_INTERVAL: 120})
    assert result['type'] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert ble_loaded.options == {OPTION_UPDATE_INTERVAL: 10,
                                  OPTION_KEEP_CONNECTION: False,
                                  OPTION_READ_INTERVAL: 120}
    call = bluetooth.factory_calls[-1]
    assert call['keep_connection'] is False
    assert call['timings'].update_interval == 120


async def test_offline_issue_names_bluetooth(
        hass: HomeAssistant, bluetooth: FakeBluetooth,
        ble_loaded: MockConfigEntry,
        freezer: FrozenDateTimeFactory) -> None:
    bluetooth.charger.push(make_ble_state(available=False))
    await hass.async_block_till_done()
    freezer.tick(timedelta(minutes=31))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    issue = ir.async_get(hass).async_get_issue(DOMAIN,
                                               f'offline_{BLE_SERIAL}')
    assert issue is not None
    assert issue.translation_key == 'charger_offline_bluetooth'


async def test_diagnostics_are_redacted(
        hass: HomeAssistant, hass_client: ClientSessionGenerator,
        bluetooth: FakeBluetooth, ble_loaded: MockConfigEntry) -> None:
    result = await get_diagnostics_for_config_entry(hass, hass_client,
                                                    ble_loaded)
    text = str(result)
    for secret in (BLE_ADDRESS, BLE_SERIAL, 'c' * 40):
        assert secret not in text
    charger = result['chargers'][0]
    assert charger['product_code'] == 'A2687'
    assert charger['bluetooth'] is True


async def test_removal_deletes_energy(hass: HomeAssistant,
                                      bluetooth: FakeBluetooth,
                                      ble_loaded: MockConfigEntry) -> None:
    store = HomeAssistantStore(hass)
    key = f'energy-{BLE_SERIAL.lower()}'
    await store.save(key, {'version': 1, 'counters': {'c1': 1.0}})
    assert await hass.config_entries.async_remove(ble_loaded.entry_id)
    await hass.async_block_till_done()
    assert await store.load(key) is None
