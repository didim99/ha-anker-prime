"""Base entity: device info, availability, capability gating, error mapping."""

from __future__ import annotations

from collections.abc import Awaitable

from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.device_registry import (
    CONNECTION_BLUETOOTH, DeviceInfo)
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ankerprime.interfaces.charger import Charger
from ankerprime.model import (
    AnkerPrimeError, Capability, ChargerState, InvalidParameterError,
    UnsupportedCapabilityError, Verification)

from .const import DOMAIN, MANUFACTURER
from .coordinator import AnkerPrimeCoordinator


class AnkerPrimeEntity(CoordinatorEntity[AnkerPrimeCoordinator]):
    """Entity of one charger.

    With a capability, the entity exists only when the product has it
    (planned ones are skipped by ``creatable``), is disabled by default while
    the capability is experimental, and is unavailable while the charger's
    firmware does not offer it.
    """

    _attr_has_entity_name = True

    _capability: Capability | None

    def __init__(self, coordinator: AnkerPrimeCoordinator, key: str, *,
                 capability: Capability | None = None,
                 placeholders: dict[str, str] | None = None):
        super().__init__(coordinator)
        self._capability = capability
        identity = coordinator.identity
        state = coordinator.data
        self._attr_unique_id = f'{identity.serial}_{key}'
        if placeholders:
            self._attr_translation_placeholders = placeholders
        if (capability is not None
                and state.product.capabilities.get(capability)
                == Verification.EXPERIMENTAL):
            self._attr_entity_registry_enabled_default = False
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, identity.serial)},
            manufacturer=MANUFACTURER, model=state.product.name,
            model_id=state.product.code.value, name=identity.name,
            serial_number=identity.serial,
            sw_version=(state.info.firmware_version
                        or identity.software_version))
        if identity.address is not None:
            self._attr_device_info['connections'] = {
                (CONNECTION_BLUETOOTH, identity.address)}

    @property
    def available(self) -> bool:
        state = self.coordinator.data
        if not (super().available and state.available):
            return False
        return self._capability is None or state.supports(self._capability)

    @property
    def charger(self) -> Charger:
        return self.coordinator.charger

    @property
    def charger_state(self) -> ChargerState:
        return self.coordinator.data

    async def run_command(self, command: Awaitable[None]) -> None:
        """Await a charger command, mapping library errors for the UI."""

        try:
            await command
        except (UnsupportedCapabilityError, InvalidParameterError) as error:
            raise ServiceValidationError(str(error)) from error
        except AnkerPrimeError as error:
            raise HomeAssistantError(
                f'Charger command failed: {error}') from error


def creatable(state: ChargerState, capability: Capability) -> bool:
    """The product has the capability and the library implements it."""

    verification = state.product.capabilities.get(capability)
    return verification is not None and verification != Verification.PLANNED
