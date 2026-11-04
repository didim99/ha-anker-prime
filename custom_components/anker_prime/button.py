"""Refresh the charger state; reset the energy counters."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import AnkerPrimeConfigEntry, AnkerPrimeCoordinator
from .entity import AnkerPrimeEntity


async def async_setup_entry(hass: HomeAssistant, entry: AnkerPrimeConfigEntry,
                            add_entities: AddConfigEntryEntitiesCallback
                            ) -> None:
    entities: list[ButtonEntity] = []
    for coordinator in entry.runtime_data.coordinators.values():
        entities.append(RefreshButton(coordinator))
        entities.append(ResetEnergyButton(coordinator))
    add_entities(entities)


class RefreshButton(AnkerPrimeEntity, ButtonEntity):
    """Reads every setting again; telemetry is live anyway."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = 'refresh'

    def __init__(self, coordinator: AnkerPrimeCoordinator):
        super().__init__(coordinator, 'refresh')

    async def async_press(self) -> None:
        await self.run_command(self.charger.refresh())


class ResetEnergyButton(AnkerPrimeEntity, ButtonEntity):
    """Sets every energy counter to zero; disabled by default.

    Statistics treat the drop as a meter reset, so long-term energy data is
    kept.
    """

    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False
    _attr_translation_key = 'reset_energy'

    def __init__(self, coordinator: AnkerPrimeCoordinator):
        super().__init__(coordinator, 'reset_energy')

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    async def async_press(self) -> None:
        await self.run_command(self.charger.reset_energy())
