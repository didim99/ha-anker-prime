"""Charging mode, display and clock options."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from ankerprime.interfaces.charger import Charger
from ankerprime.model import (
    Capability, ChargerSettings, ChargingMode, ClockTheme,
    HourFormat, KnobDirection, Product, ScreenTimeout)

from .coordinator import AnkerPrimeConfigEntry, AnkerPrimeCoordinator
from .entity import AnkerPrimeEntity, creatable


BUILTIN_CLOCK_THEMES = (ClockTheme.STYLE_1, ClockTheme.STYLE_2,
                        ClockTheme.STYLE_3)


@dataclass(frozen=True, kw_only=True)
class OptionSelectDescription(SelectEntityDescription):
    capability: Capability
    options_fn: Callable[[Product], Sequence[StrEnum]]
    value_fn: Callable[[ChargerSettings], StrEnum | None]
    set_fn: Callable[[Charger, str], Awaitable[None]]


SELECTS = (
    OptionSelectDescription(
        key='charging_mode', translation_key='charging_mode',
        capability=Capability.CHARGING_MODE,
        options_fn=lambda product: product.charging_modes,
        value_fn=lambda settings: settings.charging_mode,
        set_fn=lambda charger, value: charger.set_charging_mode(
            ChargingMode(value))),
    OptionSelectDescription(
        key='screen_timeout', translation_key='screen_timeout',
        capability=Capability.SCREEN_TIMEOUT,
        entity_category=EntityCategory.CONFIG,
        options_fn=lambda product: product.screen_timeouts,
        value_fn=lambda settings: settings.display.screen_timeout,
        set_fn=lambda charger, value: charger.set_screen_timeout(
            ScreenTimeout(value))),
    OptionSelectDescription(
        key='knob_direction', translation_key='knob_direction',
        capability=Capability.KNOB_DIRECTION,
        entity_category=EntityCategory.CONFIG,
        options_fn=lambda product: tuple(KnobDirection),
        value_fn=lambda settings: settings.display.knob_direction,
        set_fn=lambda charger, value: charger.set_knob_direction(
            KnobDirection(value))),
    OptionSelectDescription(
        key='hour_format', translation_key='hour_format',
        capability=Capability.HOUR_FORMAT,
        entity_category=EntityCategory.CONFIG,
        options_fn=lambda product: tuple(HourFormat),
        value_fn=lambda settings: settings.display.hour_format,
        set_fn=lambda charger, value: charger.set_hour_format(
            HourFormat(value))),
    OptionSelectDescription(
        key='clock_theme', translation_key='clock_theme',
        capability=Capability.CLOCK_SCREENSAVER,
        entity_category=EntityCategory.CONFIG,
        options_fn=lambda product: BUILTIN_CLOCK_THEMES,
        value_fn=lambda settings: (settings.clock.theme
                                   if settings.clock else None),
        set_fn=lambda charger, value: _set_clock_theme(charger, value)),
)


async def async_setup_entry(hass: HomeAssistant, entry: AnkerPrimeConfigEntry,
                            add_entities: AddConfigEntryEntitiesCallback
                            ) -> None:
    add_entities(
        OptionSelect(coordinator, description)
        for coordinator in entry.runtime_data.coordinators.values()
        for description in SELECTS
        if creatable(coordinator.data, description.capability))


class OptionSelect(AnkerPrimeEntity, SelectEntity):
    """One enumerated setting; values outside the offered set read unknown."""

    entity_description: OptionSelectDescription

    def __init__(self, coordinator: AnkerPrimeCoordinator,
                 description: OptionSelectDescription):
        super().__init__(coordinator, description.key,
                         capability=description.capability)
        self.entity_description = description
        product = coordinator.data.product
        self._attr_options = [option.value for option
                              in description.options_fn(product)]

    @property
    def current_option(self) -> str | None:
        value = self.entity_description.value_fn(self.charger_state.settings)
        if value is None or value.value not in self.options:
            return None
        return value.value

    async def async_select_option(self, option: str) -> None:
        await self.run_command(self.entity_description.set_fn(self.charger,
                                                              option))


async def _set_clock_theme(charger: Charger, value: str) -> None:
    """Keep the screensaver's on/off state while changing its theme."""

    clock = charger.state.settings.clock
    enabled = clock.enabled if clock is not None else False
    await charger.set_clock(enabled, ClockTheme(value))
