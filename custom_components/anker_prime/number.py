"""Display brightness."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from ankerprime.model import Capability

from .coordinator import AnkerPrimeConfigEntry, AnkerPrimeCoordinator
from .entity import AnkerPrimeEntity, creatable


async def async_setup_entry(hass: HomeAssistant, entry: AnkerPrimeConfigEntry,
                            add_entities: AddConfigEntryEntitiesCallback
                            ) -> None:
    add_entities(
        BrightnessNumber(coordinator)
        for coordinator in entry.runtime_data.coordinators.values()
        if creatable(coordinator.data, Capability.SCREEN_BRIGHTNESS)
        and coordinator.data.product.brightness is not None)


class BrightnessNumber(AnkerPrimeEntity, NumberEntity):
    """Brightness in percent, in the steps the product accepts."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.SLIDER
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_translation_key = 'brightness'

    def __init__(self, coordinator: AnkerPrimeCoordinator):
        super().__init__(coordinator, 'brightness',
                         capability=Capability.SCREEN_BRIGHTNESS)
        accepted = coordinator.data.product.brightness
        assert accepted is not None
        self._attr_native_min_value = accepted.minimum
        self._attr_native_max_value = accepted.maximum
        self._attr_native_step = accepted.step

    @property
    def native_value(self) -> float | None:
        return self.charger_state.settings.display.brightness

    async def async_set_native_value(self, value: float) -> None:
        await self.run_command(self.charger.set_brightness(round(value)))
