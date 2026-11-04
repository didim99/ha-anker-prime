"""Actions on output and clock switches."""

from datetime import time

import pytest
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from ankerprime.model import (
    ClockSchedule, OutputId, Schedule, ScheduleSlot, Weekday)

from custom_components.anker_prime.const import DOMAIN
from tests.fakes import FakeCharger


C1 = 'switch.desk_charger_c1_output'


async def call(hass: HomeAssistant, service: str, entity_id: str,
               **data: object) -> None:
    await hass.services.async_call(DOMAIN, service,
                                   {ATTR_ENTITY_ID: entity_id, **data},
                                   blocking=True)


async def test_schedules(hass: HomeAssistant, loaded: MockConfigEntry,
                         charger: FakeCharger) -> None:
    await call(hass, 'set_schedule', C1, slot='power_off', time='23:15:00',
               weekdays=['sat', 'sun'])
    await call(hass, 'set_schedule', C1, slot='power_on', time='06:00')
    await call(hass, 'disable_schedule', C1, slot='power_on')
    await call(hass, 'disable_schedule', C1, slot='power_off')
    assert charger.calls == [
        ('set_schedule', (OutputId.C1, ScheduleSlot.POWER_OFF,
                          Schedule(True, 23, 15,
                                   Weekday.SATURDAY | Weekday.SUNDAY))),
        ('set_schedule', (OutputId.C1, ScheduleSlot.POWER_ON,
                          Schedule(True, 6, 0, Weekday.ONCE))),
        ('set_schedule', (OutputId.C1, ScheduleSlot.POWER_ON,
                          Schedule(False, 7, 30,
                                   Weekday.MONDAY | Weekday.FRIDAY))),
        ('set_schedule', (OutputId.C1, ScheduleSlot.POWER_OFF,
                          Schedule(False, 0, 0, Weekday.ONCE))),
    ]


async def test_countdowns(hass: HomeAssistant, loaded: MockConfigEntry,
                          charger: FakeCharger) -> None:
    await call(hass, 'start_countdown', 'switch.desk_charger_c2_output',
               duration={'hours': 1, 'minutes': 30})
    await call(hass, 'cancel_countdown', 'switch.desk_charger_c2_output')
    assert charger.calls == [
        ('start_countdown', (OutputId.C2, 5400)),
        ('cancel_countdown', (OutputId.C2,)),
    ]


async def test_clock_schedule(hass: HomeAssistant, loaded: MockConfigEntry,
                              charger: FakeCharger) -> None:
    await call(hass, 'set_clock_schedule',
               'switch.desk_charger_clock_screensaver', start='22:00',
               end=time(7, 0))
    assert charger.calls == [
        ('set_clock_schedule', (ClockSchedule(22, 0, 7, 0,
                                              Weekday.EVERY_DAY),)),
    ]


@pytest.mark.parametrize(('service', 'entity_id', 'data'), [
    ('set_clock_schedule', C1, {'start': '22:00', 'end': '07:00'}),
    ('start_countdown', 'switch.desk_charger_clock_screensaver',
     {'duration': 60}),
    ('cancel_countdown', 'switch.desk_charger_c1_preferred', {}),
])
async def test_wrong_target_is_rejected(hass: HomeAssistant,
                                        loaded: MockConfigEntry,
                                        service: str, entity_id: str,
                                        data: dict[str, object]) -> None:
    with pytest.raises(ServiceValidationError):
        await call(hass, service, entity_id, **data)
