"""Output power, preferred outputs, clock and protocol switches.

Output switches also carry the schedule and countdown actions (registered in
``services.py``) and show both as attributes.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import time, timedelta
from typing import Any

from homeassistant.components.switch import (
    SwitchDeviceClass, SwitchEntity, SwitchEntityDescription)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from ankerprime.interfaces.charger import Charger
from ankerprime.model import (
    Capability, ChargerSettings, ClockSchedule,
    OutputId, Schedule, ScheduleSlot, Weekday)

from .const import OUTPUT_LABELS
from .coordinator import AnkerPrimeConfigEntry, AnkerPrimeCoordinator
from .entity import AnkerPrimeEntity, creatable


WEEKDAYS = {'mon': Weekday.MONDAY, 'tue': Weekday.TUESDAY,
            'wed': Weekday.WEDNESDAY, 'thu': Weekday.THURSDAY,
            'fri': Weekday.FRIDAY, 'sat': Weekday.SATURDAY,
            'sun': Weekday.SUNDAY}


@dataclass(frozen=True, kw_only=True)
class SettingSwitchDescription(SwitchEntityDescription):
    capability: Capability
    value_fn: Callable[[ChargerSettings], bool | None]
    set_fn: Callable[[Charger, bool], Awaitable[None]]


SETTING_SWITCHES = (
    SettingSwitchDescription(
        key='clock', translation_key='clock',
        capability=Capability.CLOCK_SCREENSAVER,
        value_fn=lambda settings: (settings.clock.enabled
                                   if settings.clock else None),
        set_fn=lambda charger, on: charger.set_clock(on)),
    SettingSwitchDescription(
        key='holiday_theme', translation_key='holiday_theme',
        capability=Capability.HOLIDAY_THEME,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda settings: (settings.clock.holiday_theme
                                   if settings.clock else None),
        set_fn=lambda charger, on: charger.set_holiday_theme(on)),
    SettingSwitchDescription(
        key='max_compatibility', translation_key='max_compatibility',
        capability=Capability.MAX_COMPATIBILITY,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda settings: settings.max_compatibility,
        set_fn=lambda charger, on: charger.set_max_compatibility(on)),
    SettingSwitchDescription(
        key='device_identification', translation_key='device_identification',
        capability=Capability.DEVICE_IDENTIFICATION,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda settings: settings.device_identification,
        set_fn=lambda charger, on: charger.set_device_identification(on)),
    SettingSwitchDescription(
        key='ufcs', translation_key='ufcs', capability=Capability.UFCS,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda settings: settings.ufcs,
        set_fn=lambda charger, on: charger.set_ufcs(on)),
)


async def async_setup_entry(hass: HomeAssistant, entry: AnkerPrimeConfigEntry,
                            add_entities: AddConfigEntryEntitiesCallback
                            ) -> None:
    entities: list[SwitchEntity] = []
    for coordinator in entry.runtime_data.coordinators.values():
        state = coordinator.data
        if creatable(state, Capability.OUTPUT_SWITCH):
            entities.extend(OutputSwitch(coordinator, spec.output)
                            for spec in state.product.outputs)
        if creatable(state, Capability.PORT_PRIORITY):
            entities.extend(PreferredOutputSwitch(coordinator, output)
                            for output in state.product.priority_outputs)
        entities.extend(SettingSwitch(coordinator, description)
                        for description in SETTING_SWITCHES
                        if creatable(state, description.capability))
    add_entities(entities)


class AnkerPrimeSwitch(AnkerPrimeEntity, SwitchEntity):
    """Rejects the actions that only some switches support."""

    async def async_set_schedule(self, slot: str, time: time,
                                 weekdays: list[str] | None = None,
                                 enabled: bool = True) -> None:
        raise self._unsupported_action('set_schedule')

    async def async_disable_schedule(self, slot: str) -> None:
        raise self._unsupported_action('disable_schedule')

    async def async_start_countdown(self, duration: timedelta) -> None:
        raise self._unsupported_action('start_countdown')

    async def async_cancel_countdown(self) -> None:
        raise self._unsupported_action('cancel_countdown')

    async def async_set_clock_schedule(self, start: time, end: time,
                                       weekdays: list[str] | None = None
                                       ) -> None:
        raise self._unsupported_action('set_clock_schedule')

    def _unsupported_action(self, action: str) -> ServiceValidationError:
        return ServiceValidationError(
            f'{self.entity_id} does not support the {action} action')


class OutputSwitch(AnkerPrimeSwitch):
    """Power of one output, with its schedules and countdown."""

    _attr_device_class = SwitchDeviceClass.OUTLET
    _attr_translation_key = 'output'

    _output: OutputId

    def __init__(self, coordinator: AnkerPrimeCoordinator, output: OutputId):
        super().__init__(coordinator, f'{output.value}_output',
                         capability=Capability.OUTPUT_SWITCH,
                         placeholders={'output': OUTPUT_LABELS[output]})
        self._output = output

    @property
    def is_on(self) -> bool | None:
        control = self.charger_state.outputs.get(self._output)
        return None if control is None else control.is_on

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        control = self.charger_state.outputs.get(self._output)
        if control is None:
            return None
        countdown = control.countdown
        return {
            'countdown_ends_at': (countdown.ends_at.isoformat()
                                  if countdown else None),
            'power_on_schedule': _schedule_attributes(
                control.power_on_schedule),
            'power_off_schedule': _schedule_attributes(
                control.power_off_schedule),
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.run_command(self.charger.set_output(self._output, True))

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.run_command(self.charger.set_output(self._output, False))

    async def async_set_schedule(self, slot: str, time: time,
                                 weekdays: list[str] | None = None,
                                 enabled: bool = True) -> None:
        schedule = Schedule(enabled, time.hour, time.minute,
                            parse_weekdays(weekdays, Weekday.ONCE))
        await self.run_command(self.charger.set_schedule(
            self._output, ScheduleSlot(slot), schedule))

    async def async_disable_schedule(self, slot: str) -> None:
        """Switch the slot off, keeping its time and days."""

        schedule_slot = ScheduleSlot(slot)
        control = self.charger_state.outputs.get(self._output)
        current = None
        if control is not None:
            current = (control.power_on_schedule
                       if schedule_slot == ScheduleSlot.POWER_ON
                       else control.power_off_schedule)
        disabled = (Schedule(False, current.hour, current.minute,
                             current.weekdays)
                    if current is not None
                    else Schedule(False, 0, 0, Weekday.ONCE))
        await self.run_command(self.charger.set_schedule(
            self._output, schedule_slot, disabled))

    async def async_start_countdown(self, duration: timedelta) -> None:
        seconds = int(duration.total_seconds())
        await self.run_command(self.charger.start_countdown(self._output,
                                                            seconds))

    async def async_cancel_countdown(self) -> None:
        await self.run_command(self.charger.cancel_countdown(self._output))


class PreferredOutputSwitch(AnkerPrimeSwitch):
    """Membership of an output in the port-priority mode's preferred set."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = 'preferred_output'

    _output: OutputId

    def __init__(self, coordinator: AnkerPrimeCoordinator, output: OutputId):
        super().__init__(coordinator, f'{output.value}_preferred',
                         capability=Capability.PORT_PRIORITY,
                         placeholders={'output': OUTPUT_LABELS[output]})
        self._output = output

    @property
    def is_on(self) -> bool | None:
        control = self.charger_state.outputs.get(self._output)
        return None if control is None else control.preferred

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)

    async def _set(self, preferred: bool) -> None:
        outputs = {output for output, control
                   in self.charger_state.outputs.items() if control.preferred}
        if preferred:
            outputs.add(self._output)
        else:
            outputs.discard(self._output)
        await self.run_command(self.charger.set_preferred_outputs(outputs))


class SettingSwitch(AnkerPrimeSwitch):
    """An on/off setting; the clock switch also takes the clock schedule."""

    entity_description: SettingSwitchDescription

    def __init__(self, coordinator: AnkerPrimeCoordinator,
                 description: SettingSwitchDescription):
        super().__init__(coordinator, description.key,
                         capability=description.capability)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value_fn(self.charger_state.settings)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        clock = self.charger_state.settings.clock
        if self.entity_description.key != 'clock' or clock is None:
            return None
        schedule = clock.schedule
        return {
            'theme': clock.theme.value if clock.theme else None,
            'schedule': None if schedule is None else {
                'start': f'{schedule.start_hour:02d}:'
                         f'{schedule.start_minute:02d}',
                'end': f'{schedule.end_hour:02d}:{schedule.end_minute:02d}',
                'weekdays': weekday_names(schedule.weekdays),
            },
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.run_command(self.entity_description.set_fn(self.charger,
                                                              True))

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.run_command(self.entity_description.set_fn(self.charger,
                                                              False))

    async def async_set_clock_schedule(self, start: time, end: time,
                                       weekdays: list[str] | None = None
                                       ) -> None:
        if self.entity_description.key != 'clock':
            raise self._unsupported_action('set_clock_schedule')
        schedule = ClockSchedule(start.hour, start.minute, end.hour,
                                 end.minute,
                                 parse_weekdays(weekdays, Weekday.EVERY_DAY))
        await self.run_command(self.charger.set_clock_schedule(schedule))


def parse_weekdays(names: list[str] | None, default: Weekday) -> Weekday:
    if not names:
        return default
    days = Weekday.ONCE
    for name in names:
        days |= WEEKDAYS[name]
    return days


def weekday_names(days: Weekday) -> list[str]:
    return [name for name, day in WEEKDAYS.items() if days & day]


def _schedule_attributes(schedule: Schedule | None) -> dict[str, Any] | None:
    if schedule is None:
        return None
    return {'enabled': schedule.enabled,
            'time': f'{schedule.hour:02d}:{schedule.minute:02d}',
            'weekdays': weekday_names(schedule.weekdays)}
