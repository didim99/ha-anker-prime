"""Mainland China accounts: SMS sign-in, setup from the token, SMS reauth."""

import pytest
from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.const import CONF_COUNTRY, CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from ankerprime.model import AuthenticationError, ChargerConnectionError

from custom_components.anker_prime.const import (
    CONF_AUTHENTICATION, CONF_PHONE, CONF_SERIALS, DOMAIN)
from tests.conftest import phone_entry_data
from tests.fakes import PHONE, SERIAL, SMS_CODE, USER_ID, FakeCloud


async def start(hass: HomeAssistant) -> str:
    """A user flow at the phone number form."""

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={'source': SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result['flow_id'], {'next_step_id': 'cloud_phone'})
    assert result['type'] is FlowResultType.FORM
    assert result['step_id'] == 'cloud_phone'
    return result['flow_id']


@pytest.fixture
def phone_entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, title=PHONE, unique_id=USER_ID,
                            data=phone_entry_data())
    entry.add_to_hass(hass)
    return entry


async def test_sms_sign_in_creates_entry(hass: HomeAssistant,
                                         cloud: FakeCloud) -> None:
    flow_id = await start(hass)
    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_PHONE: ' 13800138000 '})
    assert result['step_id'] == 'phone_code'
    assert result['description_placeholders'] == {'phone': PHONE}
    assert cloud.sms_sent == [PHONE]
    result = await hass.config_entries.flow.async_configure(
        flow_id, {'code': '000000'})
    assert result['errors'] == {'base': 'invalid_code'}
    result = await hass.config_entries.flow.async_configure(
        flow_id, {'code': SMS_CODE})
    assert result['step_id'] == 'chargers'
    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_SERIALS: [SERIAL]})
    assert result['type'] is FlowResultType.CREATE_ENTRY
    assert result['title'] == PHONE
    data = result['data']
    assert data[CONF_PHONE] == PHONE and data[CONF_COUNTRY] == 'CN'
    assert CONF_EMAIL not in data and CONF_PASSWORD not in data
    assert data[CONF_AUTHENTICATION]['auth_token'] == 'token-sms'


@pytest.mark.parametrize(('phone', 'error', 'key'), [
    ('12345', None, 'invalid_phone'),
    (PHONE, AuthenticationError('no account (26124)'), 'phone_refused'),
    (PHONE, ChargerConnectionError('down'), 'cannot_connect'),
])
async def test_code_request_errors(hass: HomeAssistant, cloud: FakeCloud,
                                   phone: str, error: Exception | None,
                                   key: str) -> None:
    cloud.sms_error = error
    flow_id = await start(hass)
    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_PHONE: phone})
    assert result['step_id'] == 'cloud_phone'
    assert result['errors'] == {'base': key}
    assert cloud.sms_sent == []


async def test_device_list_failure_stays_on_the_code_form(
        hass: HomeAssistant, cloud: FakeCloud) -> None:
    cloud.devices_error = ChargerConnectionError('down')
    flow_id = await start(hass)
    await hass.config_entries.flow.async_configure(flow_id,
                                                   {CONF_PHONE: PHONE})
    result = await hass.config_entries.flow.async_configure(
        flow_id, {'code': SMS_CODE})
    assert result['step_id'] == 'phone_code'
    assert result['errors'] == {'base': 'cannot_connect'}


async def test_setup_uses_the_token_without_credentials(
        hass: HomeAssistant, cloud: FakeCloud,
        phone_entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_setup(phone_entry.entry_id)
    await hass.async_block_till_done()
    assert phone_entry.state is ConfigEntryState.LOADED
    account = cloud.accounts[0]
    assert account.credentials is None
    assert cloud.logins == []


async def test_setup_without_token_asks_for_a_code(
        hass: HomeAssistant, cloud: FakeCloud) -> None:
    entry = MockConfigEntry(domain=DOMAIN, title=PHONE, unique_id=USER_ID,
                            data=phone_entry_data(authentication=None))
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [flow['context']['source'] for flow in flows] == ['reauth']


async def test_reauth_sends_a_new_code(hass: HomeAssistant, cloud: FakeCloud,
                                       phone_entry: MockConfigEntry) -> None:
    result = await phone_entry.start_reauth_flow(hass)
    assert result['step_id'] == 'reauth_phone'
    assert cloud.sms_sent == []
    result = await hass.config_entries.flow.async_configure(
        result['flow_id'], {})
    assert result['step_id'] == 'reauth_code'
    assert cloud.sms_sent == [PHONE]
    result = await hass.config_entries.flow.async_configure(
        result['flow_id'], {'code': '111111'})
    assert result['errors'] == {'base': 'invalid_code'}
    result = await hass.config_entries.flow.async_configure(
        result['flow_id'], {'code': SMS_CODE})
    assert result['type'] is FlowResultType.ABORT
    assert result['reason'] == 'reauth_successful'
    assert phone_entry.data[CONF_AUTHENTICATION]['auth_token'] == 'token-sms'


async def test_reauth_with_another_account_aborts(
        hass: HomeAssistant, cloud: FakeCloud,
        phone_entry: MockConfigEntry) -> None:
    cloud.user_id = 'someone-else'
    result = await phone_entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result['flow_id'], {})
    result = await hass.config_entries.flow.async_configure(
        result['flow_id'], {'code': SMS_CODE})
    assert result['type'] is FlowResultType.ABORT
    assert result['reason'] == 'wrong_account'


async def test_diagnostics_redact_the_phone(
        hass: HomeAssistant, hass_client: ClientSessionGenerator,
        cloud: FakeCloud, phone_entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_setup(phone_entry.entry_id)
    await hass.async_block_till_done()
    result = await get_diagnostics_for_config_entry(hass, hass_client,
                                                    phone_entry)
    assert result['entry']['data'][CONF_PHONE] == '**REDACTED**'
