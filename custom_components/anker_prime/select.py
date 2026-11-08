"""Charging mode, custom profile, allocation, display and clock options.

The 160W never reports its display language or fixed allocation; those read
unknown until set from Home Assistant. Selects also carry actions
(registered in ``services.py``): custom limits on the charging mode select,
saving and deleting profiles on the custom profile select (250W stored in
the Anker account), uploading and deleting own pictures on the clock picture
select. Other selects reject them.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import CONF_COUNTRY, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from ankerprime.interfaces.charger import Charger
from ankerprime.model import (
    AnkerPrimeError, Capability, ChargerSettings, ChargingMode,
    ChargingProfile, ClockPicture, ClockTheme, CustomModeRules,
    CustomPortLimit, DisplayLanguage, FixedAllocation, HourFormat,
    KnobDirection, OutputId, Product, ScreenOrientation, ScreenTimeout)
from ankerprime.pictures import CLOCK_PICTURE

from .const import MAINLAND_COUNTRY
from .coordinator import AnkerPrimeConfigEntry, AnkerPrimeCoordinator
from .entity import AnkerPrimeEntity, creatable, read_picture_file


BUILTIN_CLOCK_THEMES = (ClockTheme.STYLE_1, ClockTheme.STYLE_2,
                        ClockTheme.STYLE_3)
# Action fields with the watts of each output, in the library's port order.
PROFILE_PORT_FIELDS = {OutputId.C1: 'c1', OutputId.C2: 'c2',
                       OutputId.C3: 'c3', OutputId.C4: 'c4',
                       OutputId.USB_A: 'usb_a'}
# Retry loading the picture lists after a failure at most this often.
PICTURE_RETRY_SECONDS = 600.0
CATALOGUE_LANGUAGE_ZH = 'zh'

logger = logging.getLogger(__name__)


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
        entities.extend(
            (ChargingModeSelect if description.key == 'charging_mode'
             else OptionSelect)(coordinator, description)
            for description in SELECTS
            if creatable(state, description.capability))
        if (creatable(state, Capability.CUSTOM_PROFILES)
                and creatable(state, Capability.CUSTOM_CHARGING_MODE)):
            entities.append(CustomProfileSelect(coordinator))
        if creatable(state, Capability.CLOCK_PICTURE):
            entities.append(ClockPictureSelect(coordinator))
    add_entities(entities)


class AnkerPrimeSelect(AnkerPrimeEntity, SelectEntity):
    """Rejects the actions that only some selects support."""

    async def async_set_custom_limits(self, **fields: Any) -> None:
        raise self._unsupported_action('set_custom_limits')

    async def async_save_custom_profile(self, number: int, **fields: Any
                                        ) -> None:
        raise self._unsupported_action('save_custom_profile')

    async def async_delete_custom_profile(self, number: int) -> None:
        raise self._unsupported_action('delete_custom_profile')

    async def async_upload_clock_picture(self, file: str) -> None:
        raise self._unsupported_action('upload_clock_picture')

    async def async_delete_clock_picture(self, picture_id: int) -> None:
        raise self._unsupported_action('delete_clock_picture')

    def _unsupported_action(self, action: str) -> ServiceValidationError:
        return ServiceValidationError(
            f'{self.entity_id} does not support the {action} action')

    def _rules(self) -> CustomModeRules:
        rules = self.charger_state.product.custom_mode
        if rules is None:
            raise ServiceValidationError('custom mode is not supported')
        return rules

    def _mainland(self) -> bool:
        """The account is a mainland China one (its own profile limits)."""

        entry = self.coordinator.config_entry
        return (entry is not None
                and entry.data.get(CONF_COUNTRY) == MAINLAND_COUNTRY)


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


class ChargingModeSelect(OptionSelect):
    """The charging mode; also applies custom limits without storing them.

    Custom mode itself is not an option: it is entered with the limits (or
    a stored profile) and left by choosing another mode.
    """

    async def async_set_custom_limits(self, **fields: Any) -> None:
        """Switch to custom mode with these limits, unstored.

        Outputs left out keep the Anker app's defaults; the 160W takes C1–C3
        only.
        """

        rules = self._rules()
        outputs = {rule.output for rule in rules.ports}
        unknown = [field for output, field in PROFILE_PORT_FIELDS.items()
                   if fields.get(field) is not None and output not in outputs]
        if unknown:
            raise ServiceValidationError(
                f'this charger has no {", ".join(unknown)} limit')
        number = fields.get('number') or rules.numbers[0]
        profile = rules.template(int(number), 'Custom',
                                 mainland=self._mainland())
        profile = apply_profile_fields(profile, fields)
        await self.run_command(self.charger.apply_custom_profile(profile))


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
            profile = rules.template(number, name or f'Profile {number}',
                                     mainland=self._mainland())
        elif name:
            profile = profile.replace(name=name)
        profile = apply_profile_fields(profile, fields)
        await self.run_command(self.charger.save_custom_profile(profile))

    async def async_delete_custom_profile(self, number: int) -> None:
        if self.charger_state.settings.custom_profile(number) is None:
            raise ServiceValidationError(f'no stored profile {number}')
        await self.run_command(self.charger.delete_custom_profile(number))


class ClockPictureSelect(AnkerPrimeSelect):
    """The picture behind the 250W's clock: catalogue or own (account).

    Options are ``"<title> (<id>)"`` for the catalogue and ``"Own <id>"``
    for the account's own pictures. The lists are read from the Anker
    account when the entity is added, after uploads and deletions, and again
    later when reading failed. Selecting a picture waits until the charger
    has downloaded it and switches the clock on.
    """

    _attr_translation_key = 'clock_picture'
    _attr_entity_category = EntityCategory.CONFIG

    _pictures: tuple[ClockPicture, ...]
    _loaded: bool
    _loading: bool
    _failed_at: float | None

    def __init__(self, coordinator: AnkerPrimeCoordinator):
        super().__init__(coordinator, 'clock_picture',
                         capability=Capability.CLOCK_PICTURE)
        self._pictures = ()
        self._loaded = False
        self._loading = False
        self._failed_at = None

    @property
    def options(self) -> list[str]:
        return [picture_option(picture) for picture in self._pictures]

    @property
    def current_option(self) -> str | None:
        clock = self.charger_state.settings.clock
        if clock is None or clock.picture_id is None:
            return None
        own = clock.theme == ClockTheme.CUSTOM
        if not own and clock.theme != ClockTheme.PICTURE:
            return None
        for picture in self._pictures:
            if picture.own == own and picture.picture_id == clock.picture_id:
                return picture_option(picture)
        return None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._schedule_load()

    def _handle_coordinator_update(self) -> None:
        if (not self._loaded and self._failed_at is not None
                and time.monotonic() - self._failed_at
                >= PICTURE_RETRY_SECONDS):
            self._schedule_load()
        super()._handle_coordinator_update()

    async def async_select_option(self, option: str) -> None:
        for picture in self._pictures:
            if picture_option(picture) == option:
                await self.run_command(
                    self.charger.apply_clock_picture(picture))
                return
        raise ServiceValidationError(f'no clock picture {option!r}')

    async def async_upload_clock_picture(self, file: str) -> None:
        """Add an own picture from an image file under the allowed paths.

        The image is cropped to fill the clock (480x200) and stored in the
        Anker account; choose it in the select to show it.
        """

        jpeg = await read_picture_file(self.hass, file, CLOCK_PICTURE)
        try:
            await self.run_command(self.charger.upload_clock_picture(jpeg))
        finally:
            await self._async_load()

    async def async_delete_clock_picture(self, picture_id: int) -> None:
        try:
            await self.run_command(
                self.charger.delete_clock_picture(picture_id))
        finally:
            await self._async_load()

    def _schedule_load(self) -> None:
        if not self._loading:
            self._loading = True
            self.hass.async_create_background_task(
                self._async_load(), f'{self.entity_id} pictures')

    async def _async_load(self) -> None:
        self._loading = True
        language = (CATALOGUE_LANGUAGE_ZH
                    if self.hass.config.language.startswith('zh') else 'en')
        try:
            pictures = list(await self.charger.clock_pictures(language))
            if self.charger.supports(Capability.OWN_CLOCK_PICTURES):
                pictures.extend(await self.charger.own_clock_pictures())
        except AnkerPrimeError as error:
            logger.debug('clock pictures not read: %s', error)
            self._failed_at = time.monotonic()
        else:
            self._pictures = tuple(pictures)
            self._loaded = True
            self._failed_at = None
        finally:
            self._loading = False
        if self.hass is not None and self.entity_id:
            self.async_write_ha_state()


def profile_option(profile: ChargingProfile) -> str:
    return f'{profile.number}: {profile.name}'


def picture_option(picture: ClockPicture) -> str:
    if picture.own:
        return f'Own {picture.picture_id}'
    return f'{picture.title or "Picture"} ({picture.picture_id})'


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
