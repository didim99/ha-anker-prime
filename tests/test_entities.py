"""Entity states, commands, capability gating and availability."""

import pytest
from homeassistant.components.button import SERVICE_PRESS
from homeassistant.components.number import (
    ATTR_VALUE, SERVICE_SET_VALUE)
from homeassistant.components.select import ATTR_OPTION, SERVICE_SELECT_OPTION
from homeassistant.const import (
    ATTR_ENTITY_ID, SERVICE_TURN_OFF, SERVICE_TURN_ON, STATE_UNAVAILABLE,
    STATE_UNKNOWN)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from ankerprime.model import (
    ChargerConnectionError, ChargingMode, ClockTheme, InvalidParameterError,
    OutputId, ScreenTimeout)

from tests.fakes import FakeCharger, make_state


def state_of(hass: HomeAssistant, entity_id: str) -> str:
    state = hass.states.get(entity_id)
    assert state is not None, entity_id
    return state.state


async def test_sensor_states(hass: HomeAssistant,
                             loaded: MockConfigEntry) -> None:
    assert state_of(hass, 'sensor.desk_charger_c1_voltage') == '20.0'
    assert state_of(hass, 'sensor.desk_charger_c1_current') == '1.5'
    assert state_of(hass, 'sensor.desk_charger_c1_status') == 'charging'
    assert state_of(hass, 'sensor.desk_charger_c2_status') == 'idle'
    assert state_of(hass, 'sensor.desk_charger_c3_power') == STATE_UNKNOWN
    assert state_of(hass, 'sensor.desk_charger_total_power') == '30.0'
    assert state_of(hass, 'sensor.desk_charger_c1_energy') == '12.5'
    assert state_of(hass, 'sensor.desk_charger_total_energy') == '12.5'
    assert state_of(hass, 'sensor.desk_charger_c2_countdown_end') == (
        STATE_UNKNOWN)
    status = hass.states.get('sensor.desk_charger_c1_status')
    assert status is not None
    assert status.attributes['cable'] is None
    energy = hass.states.get('sensor.desk_charger_c1_energy')
    assert energy is not None
    assert energy.attributes['state_class'] == 'total_increasing'
    assert energy.attributes['unit_of_measurement'] == 'Wh'


async def test_countdown_and_schedule_attributes(
        hass: HomeAssistant, loaded: MockConfigEntry,
        charger: FakeCharger) -> None:
    charger.push(make_state(countdown_c2=True))
    await hass.async_block_till_done()
    assert state_of(hass, 'sensor.desk_charger_c2_countdown_end') == (
        '2026-11-04T12:10:00+00:00')
    c2 = hass.states.get('switch.desk_charger_c2_output')
    assert c2 is not None
    assert c2.attributes['countdown_ends_at'] == '2026-11-04T12:10:00+00:00'
    c1 = hass.states.get('switch.desk_charger_c1_output')
    assert c1 is not None
    assert c1.attributes['power_on_schedule'] == {
        'enabled': True, 'time': '07:30', 'weekdays': ['mon', 'fri']}
    assert c1.attributes['power_off_schedule'] is None
    clock = hass.states.get('switch.desk_charger_clock_screensaver')
    assert clock is not None
    assert clock.attributes['schedule'] == {
        'start': '08:00', 'end': '23:00',
        'weekdays': ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']}


async def test_binary_sensors(hass: HomeAssistant,
                              loaded: MockConfigEntry) -> None:
    assert state_of(hass, 'binary_sensor.desk_charger_over_temperature') == (
        'off')
    assert state_of(hass, 'binary_sensor.desk_charger_c1_fault') == 'off'
    registry = er.async_get(hass)
    charging = registry.async_get('binary_sensor.desk_charger_c1_charging')
    assert charging is not None and charging.disabled


async def test_switch_states_and_commands(hass: HomeAssistant,
                                          loaded: MockConfigEntry,
                                          charger: FakeCharger) -> None:
    assert state_of(hass, 'switch.desk_charger_c1_output') == 'on'
    assert state_of(hass, 'switch.desk_charger_c3_output') == 'off'
    assert state_of(hass, 'switch.desk_charger_device_identification') == 'on'
    for service, entity_id in (
            (SERVICE_TURN_OFF, 'switch.desk_charger_c1_output'),
            (SERVICE_TURN_ON, 'switch.desk_charger_usb_a_output'),
            (SERVICE_TURN_ON, 'switch.desk_charger_c2_preferred'),
            (SERVICE_TURN_OFF, 'switch.desk_charger_c1_preferred'),
            (SERVICE_TURN_ON, 'switch.desk_charger_clock_screensaver'),
            (SERVICE_TURN_ON, 'switch.desk_charger_max_compatibility')):
        await hass.services.async_call('switch', service,
                                       {ATTR_ENTITY_ID: entity_id},
                                       blocking=True)
    assert charger.calls == [
        ('set_output', (OutputId.C1, False)),
        ('set_output', (OutputId.USB_A, True)),
        ('set_preferred_outputs', ({OutputId.C1, OutputId.C2},)),
        ('set_preferred_outputs', (set(),)),
        ('set_clock', (True, None)),
        ('set_max_compatibility', (True,)),
    ]


async def test_select_number_and_buttons(hass: HomeAssistant,
                                         loaded: MockConfigEntry,
                                         charger: FakeCharger) -> None:
    mode = hass.states.get('select.desk_charger_charging_mode')
    assert mode is not None and mode.state == 'ai'
    assert mode.attributes['options'] == [
        'ai', 'port_priority', 'dual_laptop', 'low_current']
    assert state_of(hass, 'select.desk_charger_screen_timeout') == '5min'
    assert state_of(hass, 'select.desk_charger_clock_theme') == 'style_2'
    assert state_of(hass, 'number.desk_charger_display_brightness') == '60'
    calls: list[tuple[str, str, str, dict[str, object]]] = [
        ('select', SERVICE_SELECT_OPTION, 'select.desk_charger_charging_mode',
         {ATTR_OPTION: 'port_priority'}),
        ('select', SERVICE_SELECT_OPTION, 'select.desk_charger_screen_timeout',
         {ATTR_OPTION: '30s'}),
        ('select', SERVICE_SELECT_OPTION, 'select.desk_charger_clock_theme',
         {ATTR_OPTION: 'style_3'}),
        ('number', SERVICE_SET_VALUE,
         'number.desk_charger_display_brightness', {ATTR_VALUE: 85}),
        ('button', SERVICE_PRESS, 'button.desk_charger_refresh', {}),
    ]
    for domain, service, entity_id, data in calls:
        await hass.services.async_call(
            domain, service, {ATTR_ENTITY_ID: entity_id, **data},
            blocking=True)
    assert charger.calls == [
        ('set_charging_mode', (ChargingMode.PORT_PRIORITY,)),
        ('set_screen_timeout', (ScreenTimeout.THIRTY_SECONDS,)),
        ('set_clock', (False, ClockTheme.STYLE_3)),
        ('set_brightness', (85,)),
        ('refresh', ()),
    ]


async def test_reset_energy_button_is_disabled_by_default(
        hass: HomeAssistant, loaded: MockConfigEntry) -> None:
    entry = er.async_get(hass).async_get(
        'button.desk_charger_reset_energy_counters')
    assert entry is not None and entry.disabled


async def test_experimental_capability_is_disabled_by_default(
        hass: HomeAssistant, loaded: MockConfigEntry) -> None:
    ufcs = er.async_get(hass).async_get('switch.desk_charger_ufcs')
    assert ufcs is not None and ufcs.disabled
    clock = er.async_get(hass).async_get(
        'switch.desk_charger_clock_screensaver')
    assert clock is not None and not clock.disabled


async def test_unavailable_charger(hass: HomeAssistant,
                                   loaded: MockConfigEntry,
                                   charger: FakeCharger) -> None:
    charger.push(make_state(available=False))
    await hass.async_block_till_done()
    assert state_of(hass, 'sensor.desk_charger_c1_power') == STATE_UNAVAILABLE
    assert state_of(hass, 'switch.desk_charger_c1_output') == (
        STATE_UNAVAILABLE)
    assert state_of(hass, 'sensor.desk_charger_c1_energy') == '12.5'


@pytest.mark.parametrize(('error', 'raised'), [
    (ChargerConnectionError('charger is not ready'), HomeAssistantError),
    (InvalidParameterError('brightness out of range'),
     ServiceValidationError),
])
async def test_command_errors(hass: HomeAssistant, loaded: MockConfigEntry,
                              charger: FakeCharger, error: Exception,
                              raised: type[Exception]) -> None:
    charger.fail_with = error
    with pytest.raises(raised):
        await hass.services.async_call(
            'switch', SERVICE_TURN_ON,
            {ATTR_ENTITY_ID: 'switch.desk_charger_c3_output'}, blocking=True)
