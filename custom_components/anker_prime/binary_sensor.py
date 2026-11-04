"""Problems reported by the charger and whether a port delivers power."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass, BinarySensorEntity)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from ankerprime.model import OutputId, PortId

from .const import OUTPUT_LABELS, PORT_LABELS
from .coordinator import AnkerPrimeConfigEntry, AnkerPrimeCoordinator
from .entity import AnkerPrimeEntity


async def async_setup_entry(hass: HomeAssistant, entry: AnkerPrimeConfigEntry,
                            add_entities: AddConfigEntryEntitiesCallback
                            ) -> None:
    entities: list[BinarySensorEntity] = []
    for coordinator in entry.runtime_data.coordinators.values():
        product = coordinator.data.product
        entities.append(OverTemperatureSensor(coordinator))
        entities.extend(OutputFaultSensor(coordinator, spec.output)
                        for spec in product.outputs)
        entities.extend(PortChargingSensor(coordinator, spec.port)
                        for spec in product.ports)
    add_entities(entities)


class OverTemperatureSensor(AnkerPrimeEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = 'over_temperature'

    def __init__(self, coordinator: AnkerPrimeCoordinator):
        super().__init__(coordinator, 'over_temperature')

    @property
    def is_on(self) -> bool | None:
        return self.charger_state.over_temperature


class OutputFaultSensor(AnkerPrimeEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = 'output_fault'

    _output: OutputId

    def __init__(self, coordinator: AnkerPrimeCoordinator, output: OutputId):
        super().__init__(coordinator, f'{output.value}_fault',
                         placeholders={'output': OUTPUT_LABELS[output]})
        self._output = output

    @property
    def is_on(self) -> bool | None:
        control = self.charger_state.outputs.get(self._output)
        return None if control is None else control.fault


class PortChargingSensor(AnkerPrimeEntity, BinarySensorEntity):
    """A device draws power from the port; disabled by default (see status)."""

    _attr_device_class = BinarySensorDeviceClass.POWER
    _attr_entity_registry_enabled_default = False
    _attr_translation_key = 'port_charging'

    _port: PortId

    def __init__(self, coordinator: AnkerPrimeCoordinator, port: PortId):
        super().__init__(coordinator, f'{port.value}_charging',
                         placeholders={'port': PORT_LABELS[port]})
        self._port = port

    @property
    def is_on(self) -> bool | None:
        reading = self.charger_state.ports.get(self._port)
        return None if reading is None else reading.delivering
