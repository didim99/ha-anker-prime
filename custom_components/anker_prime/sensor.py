"""Readings per port and for the whole charger, energy and countdown ends.

The 160W's screen picture sensor carries the screen picture actions
(registered in ``services.py``).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass, SensorEntity, SensorEntityDescription, SensorStateClass)
from homeassistant.const import (
    EntityCategory, UnitOfElectricCurrent,
    UnitOfElectricPotential, UnitOfEnergy, UnitOfPower)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from ankerprime.model import (
    Capability, OutputId, PictureTransferError,
    PortId, PortReading, ScreenPictureUpload)
from ankerprime.pictures import SCREEN_PICTURE
from ankerprime.utils import enum_value

from .const import OUTPUT_LABELS, PORT_LABELS
from .coordinator import AnkerPrimeConfigEntry, AnkerPrimeCoordinator
from .entity import AnkerPrimeEntity, creatable, read_picture_file


PORT_STATUSES = ['idle', 'active', 'charging']


@dataclass(frozen=True, kw_only=True)
class PortSensorDescription(SensorEntityDescription):
    value_fn: Callable[[PortReading], StateType]


PORT_SENSORS = (
    PortSensorDescription(
        key='power', translation_key='port_power',
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=2, value_fn=lambda reading: reading.power),
    PortSensorDescription(
        key='voltage', translation_key='port_voltage',
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        suggested_display_precision=2,
        value_fn=lambda reading: reading.voltage),
    PortSensorDescription(
        key='current', translation_key='port_current',
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        suggested_display_precision=2,
        value_fn=lambda reading: reading.current),
    PortSensorDescription(
        key='status', translation_key='port_status',
        device_class=SensorDeviceClass.ENUM, options=PORT_STATUSES,
        value_fn=lambda reading: port_status(reading)),
)

TOTAL_POWER = SensorEntityDescription(
    key='total_power', translation_key='total_power',
    device_class=SensorDeviceClass.POWER,
    state_class=SensorStateClass.MEASUREMENT,
    native_unit_of_measurement=UnitOfPower.WATT,
    suggested_display_precision=2)

ENERGY = SensorEntityDescription(
    key='energy', device_class=SensorDeviceClass.ENERGY,
    state_class=SensorStateClass.TOTAL_INCREASING,
    native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
    suggested_display_precision=2)

COUNTDOWN_END = SensorEntityDescription(
    key='countdown_end', translation_key='countdown_end',
    device_class=SensorDeviceClass.TIMESTAMP)


async def async_setup_entry(hass: HomeAssistant, entry: AnkerPrimeConfigEntry,
                            add_entities: AddConfigEntryEntitiesCallback
                            ) -> None:
    entities: list[SensorEntity] = []
    for coordinator in entry.runtime_data.coordinators.values():
        product = coordinator.data.product
        entities.append(TotalPowerSensor(coordinator, TOTAL_POWER))
        entities.append(EnergySensor(coordinator, None))
        for spec in product.ports:
            entities.extend(PortSensor(coordinator, description, spec.port)
                            for description in PORT_SENSORS)
            entities.append(EnergySensor(coordinator, spec.port))
        if creatable(coordinator.data, Capability.OUTPUT_COUNTDOWN):
            entities.extend(CountdownEndSensor(coordinator, output.output)
                            for output in product.outputs)
        if creatable(coordinator.data, Capability.SCREEN_PICTURE):
            entities.append(ScreenPictureSensor(coordinator))
    add_entities(entities)


def port_status(reading: PortReading) -> str:
    if reading.delivering:
        return 'charging'
    return 'active' if reading.active else 'idle'


class PortSensor(AnkerPrimeEntity, SensorEntity):
    """One reading of one port; unknown until the port reported."""

    entity_description: PortSensorDescription

    _port: PortId

    def __init__(self, coordinator: AnkerPrimeCoordinator,
                 description: PortSensorDescription, port: PortId):
        super().__init__(coordinator, f'{port.value}_{description.key}',
                         placeholders={'port': PORT_LABELS[port]})
        self.entity_description = description
        self._port = port

    @property
    def native_value(self) -> StateType:
        reading = self.charger_state.ports.get(self._port)
        if reading is None:
            return None
        return self.entity_description.value_fn(reading)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.key != 'status':
            return None
        reading = self.charger_state.ports.get(self._port)
        if reading is None:
            return None
        return {'cable': enum_value(reading.cable),
                'charging_protocol': enum_value(reading.charging_protocol),
                'device_brand': enum_value(reading.device_brand),
                'usb_vendor_id': _hex(reading.usb_vendor_id),
                'usb_product_id': _hex(reading.usb_product_id)}


class TotalPowerSensor(AnkerPrimeEntity, SensorEntity):

    def __init__(self, coordinator: AnkerPrimeCoordinator,
                 description: SensorEntityDescription):
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float:
        return self.charger_state.total_power


class EnergySensor(AnkerPrimeEntity, SensorEntity):
    """Energy counted by the library; stays available while offline."""

    _port: PortId | None

    def __init__(self, coordinator: AnkerPrimeCoordinator,
                 port: PortId | None):
        if port is None:
            super().__init__(coordinator, 'total_energy')
            self._attr_translation_key = 'total_energy'
        else:
            super().__init__(coordinator, f'{port.value}_energy',
                             placeholders={'port': PORT_LABELS[port]})
            self._attr_translation_key = 'port_energy'
        self.entity_description = ENERGY
        self._port = port

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def native_value(self) -> float | None:
        energy = self.charger_state.energy
        if self._port is None:
            return self.charger_state.total_energy if energy else None
        return energy.get(self._port)


class CountdownEndSensor(AnkerPrimeEntity, SensorEntity):
    """When the output's countdown switches it off; unknown without one."""

    _output: OutputId

    def __init__(self, coordinator: AnkerPrimeCoordinator, output: OutputId):
        super().__init__(coordinator, f'{output.value}_countdown_end',
                         capability=Capability.OUTPUT_COUNTDOWN,
                         placeholders={'output': OUTPUT_LABELS[output]})
        self.entity_description = COUNTDOWN_END
        self._output = output

    @property
    def native_value(self) -> datetime | None:
        control = self.charger_state.outputs.get(self._output)
        if control is None or control.countdown is None:
            return None
        return control.countdown.ends_at


class ScreenPictureSensor(AnkerPrimeEntity, SensorEntity):
    """The picture the 160W's screen shows (low 16 bits of its id).

    Attributes name the last picture uploaded from Home Assistant; its id
    and CRC-32 select it again later.
    """

    _attr_translation_key = 'screen_picture'
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    _last_upload: ScreenPictureUpload | None

    def __init__(self, coordinator: AnkerPrimeCoordinator):
        super().__init__(coordinator, 'screen_picture',
                         capability=Capability.SCREEN_PICTURE)
        self._last_upload = None

    @property
    def native_value(self) -> int | None:
        return self.charger_state.settings.display.screen_picture

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        upload = self._last_upload
        if upload is None:
            return None
        return {'last_upload_id': upload.picture_id,
                'last_upload_crc32': f'{upload.crc32:08x}'}

    async def async_upload(self, file: str) -> dict[str, Any]:
        """Write an image file to the screen; nothing can erase it later."""

        jpeg = await read_picture_file(self.hass, file, SCREEN_PICTURE)
        try:
            result = await self.run_command(self.charger.upload_screen_picture(
                jpeg, acknowledge_irreversible=True))
        except HomeAssistantError as error:
            cause = error.__cause__
            if (isinstance(cause, PictureTransferError)
                    and cause.pixels_written):
                raise HomeAssistantError(
                    f'{error}. Part or all of the picture is on the charger '
                    'now.') from cause
            raise
        self._last_upload = result
        self.async_write_ha_state()
        return {'picture_id': result.picture_id,
                'crc32': f'{result.crc32:08x}',
                'witnessed': result.witnessed}

    async def async_select(self, picture_id: int, crc32: int) -> None:
        await self.run_command(
            self.charger.select_screen_picture(picture_id, crc32))


def _hex(value: int | None) -> str | None:
    return None if value is None else f'{value:04x}'
