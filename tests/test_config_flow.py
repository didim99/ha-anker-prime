"""Config flow: sign-in, charger selection, errors, reauth and options."""

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_COUNTRY, CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from ankerprime.model import ChargerConnectionError, InvalidParameterError

from custom_components.anker_prime.const import (
    CONF_AUTHENTICATION, CONF_SERIALS, DOMAIN, OPTION_UPDATE_INTERVAL)
from tests.fakes import (
    COUNTRY, EMAIL, OTHER_SERIAL, PASSWORD, SERIAL, FakeCloud, make_device)


USER_INPUT = {CONF_EMAIL: EMAIL, CONF_PASSWORD: PASSWORD,
              CONF_COUNTRY: COUNTRY}


async def start(hass: HomeAssistant) -> str:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={'source': SOURCE_USER})
    assert result['type'] is FlowResultType.FORM
    assert result['step_id'] == 'user'
    return result['flow_id']


async def test_full_flow_creates_entry(hass: HomeAssistant,
                                       cloud: FakeCloud) -> None:
    cloud.devices.append(make_device(OTHER_SERIAL, name='Shelf'))
    cloud.devices.append(make_device('BLE160', product_code='A2687'))
    flow_id = await start(hass)
    result = await hass.config_entries.flow.async_configure(flow_id,
                                                            USER_INPUT)
    assert result['type'] is FlowResultType.FORM
    assert result['step_id'] == 'chargers'
    assert result['data_schema'] is not None
    schema = result['data_schema'].schema
    options = next(iter(schema.values())).config['options']
    assert [option['value'] for option in options] == [SERIAL, OTHER_SERIAL]
    assert options[0]['label'] == 'Desk charger (A2345, ...0868)'
    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_SERIALS: [SERIAL]})
    assert result['type'] is FlowResultType.CREATE_ENTRY
    assert result['title'] == EMAIL
    assert result['result'].unique_id == 'user-1'
    data = result['data']
    assert data[CONF_SERIALS] == [SERIAL]
    assert data[CONF_PASSWORD] == PASSWORD
    assert data[CONF_AUTHENTICATION]['auth_token'] == 'token-new'
    assert cloud.accounts[0].closed  # the sign-in account of the flow


@pytest.mark.parametrize(('error', 'key'), [
    (ChargerConnectionError('down'), 'cannot_connect'),
    (InvalidParameterError('bad email'), 'invalid_input'),
    (RuntimeError('boom'), 'unknown'),
])
async def test_sign_in_errors_then_recovery(hass: HomeAssistant,
                                            cloud: FakeCloud,
                                            error: Exception, key: str) -> None:
    cloud.login_error = error
    flow_id = await start(hass)
    result = await hass.config_entries.flow.async_configure(flow_id,
                                                            USER_INPUT)
    assert result['type'] is FlowResultType.FORM
    assert result['errors'] == {'base': key}
    cloud.login_error = None
    result = await hass.config_entries.flow.async_configure(flow_id,
                                                            USER_INPUT)
    assert result['step_id'] == 'chargers'


async def test_wrong_password(hass: HomeAssistant, cloud: FakeCloud) -> None:
    flow_id = await start(hass)
    result = await hass.config_entries.flow.async_configure(
        flow_id, {**USER_INPUT, CONF_PASSWORD: 'wrong'})
    assert result['errors'] == {'base': 'invalid_auth'}


async def test_device_list_failure(hass: HomeAssistant,
                                   cloud: FakeCloud) -> None:
    cloud.devices_error = ChargerConnectionError('down')
    flow_id = await start(hass)
    result = await hass.config_entries.flow.async_configure(flow_id,
                                                            USER_INPUT)
    assert result['errors'] == {'base': 'cannot_connect'}


async def test_no_cloud_chargers_aborts(hass: HomeAssistant,
                                        cloud: FakeCloud) -> None:
    cloud.devices = [make_device('BLE160', product_code='A2687')]
    flow_id = await start(hass)
    result = await hass.config_entries.flow.async_configure(flow_id,
                                                            USER_INPUT)
    assert result['type'] is FlowResultType.ABORT
    assert result['reason'] == 'no_chargers'


async def test_empty_selection_is_refused(hass: HomeAssistant,
                                          cloud: FakeCloud) -> None:
    flow_id = await start(hass)
    await hass.config_entries.flow.async_configure(flow_id, USER_INPUT)
    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_SERIALS: []})
    assert result['errors'] == {'base': 'no_selection'}


async def test_same_account_aborts(hass: HomeAssistant, cloud: FakeCloud,
                                   entry: MockConfigEntry) -> None:
    flow_id = await start(hass)
    result = await hass.config_entries.flow.async_configure(flow_id,
                                                            USER_INPUT)
    assert result['type'] is FlowResultType.ABORT
    assert result['reason'] == 'already_configured'


async def test_country_defaults_to_home_assistant_country(
        hass: HomeAssistant, cloud: FakeCloud) -> None:
    hass.config.country = 'GB'
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={'source': SOURCE_USER})
    assert result['data_schema'] is not None
    schema = result['data_schema'].schema
    country = next(key for key in schema if key == CONF_COUNTRY)
    assert country.description == {'suggested_value': 'UK'}


async def test_reauth_updates_password(hass: HomeAssistant, cloud: FakeCloud,
                                       entry: MockConfigEntry) -> None:
    result = await entry.start_reauth_flow(hass)
    assert result['step_id'] == 'reauth_confirm'
    result = await hass.config_entries.flow.async_configure(
        result['flow_id'], {CONF_PASSWORD: 'wrong'})
    assert result['errors'] == {'base': 'invalid_auth'}
    result = await hass.config_entries.flow.async_configure(
        result['flow_id'], {CONF_PASSWORD: PASSWORD})
    assert result['type'] is FlowResultType.ABORT
    assert result['reason'] == 'reauth_successful'
    assert entry.data[CONF_AUTHENTICATION]['auth_token'] == 'token-new'


async def test_reauth_with_another_account_aborts(
        hass: HomeAssistant, cloud: FakeCloud,
        entry: MockConfigEntry) -> None:
    cloud.user_id = 'someone-else'
    result = await entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result['flow_id'], {CONF_PASSWORD: PASSWORD})
    assert result['type'] is FlowResultType.ABORT
    assert result['reason'] == 'wrong_account'


async def test_options_flow_sets_interval(hass: HomeAssistant,
                                          loaded: MockConfigEntry) -> None:
    result = await hass.config_entries.options.async_init(loaded.entry_id)
    assert result['step_id'] == 'init'
    result = await hass.config_entries.options.async_configure(
        result['flow_id'], {OPTION_UPDATE_INTERVAL: 12})
    assert result['type'] is FlowResultType.CREATE_ENTRY
    assert loaded.options == {OPTION_UPDATE_INTERVAL: 12}
