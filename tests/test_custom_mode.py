"""250W custom charging: the profile select, its actions, the Labs switch."""

import pytest
import voluptuous as vol
from homeassistant.components.select import ATTR_OPTION, SERVICE_SELECT_OPTION
from homeassistant.const import (
    ATTR_ENTITY_ID, SERVICE_TURN_OFF, STATE_UNKNOWN)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from ankerprime.model import ChargingProfile, CustomPortLimit, OutputId

from custom_components.anker_prime.const import DOMAIN
from tests.fakes import FakeCharger, make_profile, make_state


PROFILE = 'select.desk_charger_custom_profile'
LABS = 'switch.desk_charger_custom_mode_setting_labs'


async def call(hass: HomeAssistant, service: str, entity_id: str,
               **data: object) -> None:
    await hass.services.async_call(DOMAIN, service,
                                   {ATTR_ENTITY_ID: entity_id, **data},
                                   blocking=True)


def saved(charger: FakeCharger) -> ChargingProfile:
    name, args = charger.calls[-1]
    assert name == 'save_custom_profile'
    profile = args[0]
    assert isinstance(profile, ChargingProfile)
    return profile


async def test_profile_select_lists_and_applies(
        hass: HomeAssistant, loaded: MockConfigEntry,
        charger: FakeCharger) -> None:
    select = hass.states.get(PROFILE)
    assert select is not None and select.state == STATE_UNKNOWN
    assert select.attributes['options'] == ['1: Desk', '3: Travel']
    entry = er.async_get(hass).async_get(PROFILE)
    assert entry is not None and not entry.disabled

    await hass.services.async_call(
        'select', SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: PROFILE, ATTR_OPTION: '3: Travel'}, blocking=True)
    assert charger.calls == [('apply_custom_profile',
                              (make_profile(3, 'Travel'),))]

    charger.push(make_state(custom_profile=3))
    await hass.async_block_till_done()
    select = hass.states.get(PROFILE)
    assert select is not None and select.state == '3: Travel'


async def test_unknown_profile_is_rejected(hass: HomeAssistant,
                                           loaded: MockConfigEntry) -> None:
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            'select', SERVICE_SELECT_OPTION,
            {ATTR_ENTITY_ID: PROFILE, ATTR_OPTION: '2: Gone'}, blocking=True)


async def test_save_new_profile_from_defaults(
        hass: HomeAssistant, loaded: MockConfigEntry,
        charger: FakeCharger) -> None:
    await call(hass, 'save_custom_profile', PROFILE, number=2, c1=60,
               usb_a=15, auto_exit=True)
    profile = saved(charger)
    expected = make_profile(2, 'Profile 2')
    assert profile.number == 2 and profile.name == 'Profile 2'
    assert profile.watts(OutputId.C1) == 60
    assert profile.watts(OutputId.USB_A) == 15
    assert profile.watts(OutputId.C2) == expected.watts(OutputId.C2)
    assert profile.auto_exit
    c1 = profile.port(OutputId.C1)
    default_c1 = expected.port(OutputId.C1)
    assert c1 is not None and default_c1 is not None
    assert c1.protocols == default_c1.protocols


async def test_edit_keeps_unset_fields(hass: HomeAssistant,
                                       loaded: MockConfigEntry,
                                       charger: FakeCharger) -> None:
    await call(hass, 'save_custom_profile', PROFILE, number=1, name='Work',
               c4=45)
    stored = make_profile(1, 'Desk')
    c4 = stored.port(OutputId.C4)
    assert c4 is not None
    expected = stored.replace(name='Work').with_port(
        CustomPortLimit(OutputId.C4, 45, c4.protocols))
    assert saved(charger) == expected


async def test_delete_profile(hass: HomeAssistant, loaded: MockConfigEntry,
                              charger: FakeCharger) -> None:
    await call(hass, 'delete_custom_profile', PROFILE, number=3)
    assert charger.calls == [('delete_custom_profile', (3,))]
    with pytest.raises(ServiceValidationError, match='no stored profile 2'):
        await call(hass, 'delete_custom_profile', PROFILE, number=2)


@pytest.mark.parametrize(('service', 'data'), [
    ('save_custom_profile', {'number': 1}),
    ('delete_custom_profile', {'number': 1}),
])
async def test_profile_actions_need_the_profile_select(
        hass: HomeAssistant, loaded: MockConfigEntry, charger: FakeCharger,
        service: str, data: dict[str, object]) -> None:
    with pytest.raises(ServiceValidationError, match='does not support'):
        await call(hass, service, 'select.desk_charger_charging_mode', **data)
    assert charger.calls == []


@pytest.mark.parametrize('data', [
    {'number': 5}, {'number': 1, 'c1': 141}, {'number': 1, 'name': ''},
    {'number': 1, 'name': 'x' * 21},
])
async def test_invalid_action_fields(hass: HomeAssistant,
                                     loaded: MockConfigEntry,
                                     charger: FakeCharger,
                                     data: dict[str, object]) -> None:
    with pytest.raises(vol.Invalid):
        await call(hass, 'save_custom_profile', PROFILE, **data)
    assert charger.calls == []


async def test_labs_switch(hass: HomeAssistant, loaded: MockConfigEntry,
                           charger: FakeCharger) -> None:
    labs = hass.states.get(LABS)
    assert labs is not None and labs.state == 'on'
    await hass.services.async_call('switch', SERVICE_TURN_OFF,
                                   {ATTR_ENTITY_ID: LABS}, blocking=True)
    assert charger.calls == [('set_custom_mode_enabled', (False,))]
