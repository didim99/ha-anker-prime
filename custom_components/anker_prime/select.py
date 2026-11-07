"""Charging mode, custom profile, allocation, display and clock options.

The 160W never reports its display language or fixed allocation; those read
unknown until set from Home Assistant. The custom profile select applies the
250W's profiles stored in the Anker account and carries the actions that
save and delete them (registered in ``services.py``).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from ankerprime.interfaces.charger import Charger
from ankerprime.model import (
    Capability, ChargerSettings, ChargingMode, ChargingProfile, ClockTheme,
    CustomModeRules, CustomPortLimit, DisplayLanguage, FixedAllocation,
    HourFormat, KnobDirection, OutputId, Product, ScreenOrientation,
    ScreenTimeout)

from .coordinator import AnkerPrimeConfigEntry, AnkerPrimeCoordinator
from .entity import AnkerPrimeEntity, creatable


BUILTIN_CLOCK_THEMES = (ClockTheme.STYLE_1, ClockTheme.STYLE_2,
                        ClockTheme.STYLE_3)
# Action fields with the watts of each output, in the library's port order.
PROFILE_PORT_FIELDS = {OutputId.C1: 'c1', OutputId.C2: 'c2',
                       OutputId.C3: 'c3', OutputId.C4: 'c4',
                       OutputId.USB_A: 'usb_a'}


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
        key='fixed_allocation', translation_key='fixed_allocation',
        capability=Capability.FIXED_ALLOCATION,
        options_fn=lambda product: tuple(FixedAllocation),
        value_fn=lambda settings: settings.fixed_allocation,
        set_fn=lambda charger, value: charger.set_fixed_allocation(
            FixedAllocation(value))),
    OptionSelectDescription(
        key='screen_orientation', translation_key='screen_orientation',
        capability=Capability.SCREEN_ORIENTATION,
        entity_category=EntityCategory.CONFIG,
        options_fn=lambda product: tuple(ScreenOrientation),
        value_fn=lambda settings: settings.display.orientation,
        set_fn=lambda charger, value: charger.set_screen_orientation(
            ScreenOrientation(value))),
    OptionSelectDescription(
        key='display_language', translation_key='display_language',
        capability=Capability.DISPLAY_LANGUAGE,
        entity_category=EntityCategory.CONFIG,
        options_fn=lambda product: product.display_languages,
        value_fn=lambda settings: settings.display.language,
        set_fn=lambda charger, value: charger.set_display_language(
            DisplayLanguage(value))),
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
    entities: list[SelectEntity] = []
    for coordinator in entry.runtime_data.coordinators.values():
        state = coordinator.data
        entities.extend(OptionSelect(coordinator, description)
                        for description in SELECTS
                        if creatable(state, description.capability))
        if (creatable(state, Capability.CUSTOM_PROFILES)
                and creatable(state, Capability.CUSTOM_CHARGING_MODE)):
            entities.append(CustomProfileSelect(coordinator))
    add_entities(entities)


class AnkerPrimeSelect(AnkerPrimeEntity, SelectEntity):
    """Rejects the actions that only the custom profile select supports."""

    async def async_save_custom_profile(self, number: int, **fields: Any
                                        ) -> None:
        raise self._unsupported_action('save_custom_profile')

    async def async_delete_custom_profile(self, number: int) -> None:
        raise self._unsupported_action('delete_custom_profile')

    def _unsupported_action(self, action: str) -> ServiceValidationError:
        return ServiceValidationError(
            f'{self.entity_id} does not support the {action} action')


class OptionSelect(AnkerPrimeSelect):
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


class CustomProfileSelect(AnkerPrimeSelect):
    """Applies a custom profile stored in the Anker account (250W).

    Options are ``"<number>: <name>"``; the profile in use is shown while
    the charger is in custom mode. Leave custom mode with the charging mode
    select.
    """

    _attr_translation_key = 'custom_profile'

    def __init__(self, coordinator: AnkerPrimeCoordinator):
        super().__init__(coordinator, 'custom_profile',
                         capability=Capability.CUSTOM_PROFILES)

    @property
    def options(self) -> list[str]:
        return [profile_option(profile) for profile
                in self.charger_state.settings.custom_profiles or ()]

    @property
    def current_option(self) -> str | None:
        settings = self.charger_state.settings
        if settings.charging_mode != ChargingMode.CUSTOM:
            return None
        number = settings.active_profile
        profile = (settings.custom_profile(number)
                   if number is not None else None)
        return profile_option(profile) if profile is not None else None

    async def async_select_option(self, option: str) -> None:
        for profile in self.charger_state.settings.custom_profiles or ():
            if profile_option(profile) == option:
                await self.run_command(
                    self.charger.apply_custom_profile(profile))
                return
        raise ServiceValidationError(f'no stored profile {option!r}')

    async def async_save_custom_profile(self, number: int, **fields: Any
                                        ) -> None:
        """Store a new profile or change a stored one.

        A new profile starts from the Anker app's defaults; unset fields of a
        stored one stay as they are.
        """

        rules = self._rules()
        settings = self.charger_state.settings
        profile = settings.custom_profile(number)
        name = fields.get('name')
        if profile is None:
            profile = rules.template(number, name or f'Profile {number}')
        elif name:
            profile = profile.replace(name=name)
        profile = apply_profile_fields(profile, fields)
        await self.run_command(self.charger.save_custom_profile(profile))

    async def async_delete_custom_profile(self, number: int) -> None:
        if self.charger_state.settings.custom_profile(number) is None:
            raise ServiceValidationError(f'no stored profile {number}')
        await self.run_command(self.charger.delete_custom_profile(number))

    def _rules(self) -> CustomModeRules:
        rules = self.charger_state.product.custom_mode
        if rules is None:
            raise ServiceValidationError('custom mode is not supported')
        return rules


def profile_option(profile: ChargingProfile) -> str:
    return f'{profile.number}: {profile.name}'


def apply_profile_fields(profile: ChargingProfile, fields: dict[str, Any]
                         ) -> ChargingProfile:
    """Apply the action's watts and auto-exit; protocols are kept."""

    for output, field in PROFILE_PORT_FIELDS.items():
        watts = fields.get(field)
        if watts is None:
            continue
        current = profile.port(output)
        protocols = current.protocols if current is not None else ()
        profile = profile.with_port(
            CustomPortLimit(output, int(watts), protocols))
    auto_exit = fields.get('auto_exit')
    if auto_exit is not None:
        profile = profile.replace(auto_exit=bool(auto_exit))
    return profile


async def _set_clock_theme(charger: Charger, value: str) -> None:
    """Keep the screensaver's on/off state while changing its theme."""

    clock = charger.state.settings.clock
    enabled = clock.enabled if clock is not None else False
    await charger.set_clock(enabled, ClockTheme(value))
