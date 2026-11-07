"""Building the library's Bluetooth charger from entry data.

The ``BLEDevice`` comes from Home Assistant's Bluetooth stack, so local
adapters and Bluetooth proxies both work; before each connection attempt the
newest one is asked for.
"""

from collections.abc import Mapping
from typing import Any

from bleak.backends.device import BLEDevice
from homeassistant.components import bluetooth
from homeassistant.const import CONF_ADDRESS, CONF_COUNTRY
from homeassistant.core import HomeAssistant

from ankerprime.api.ble import A2687Timings, ble_charger
from ankerprime.interfaces.charger import Charger
from ankerprime.model import ChargerConnectionError, DeviceInfo

from .const import (
    BLUETOOTH_NAME, CONF_CLIENT_ID, CONF_OWNER_ID, CONF_SERIAL,
    DEFAULT_COUNTRY, DEFAULT_KEEP_CONNECTION, DEFAULT_READ_INTERVAL,
    OPTION_KEEP_CONNECTION, OPTION_READ_INTERVAL)
from .coordinator import ChargerIdentity
from .storage import HomeAssistantStore


def create_charger(hass: HomeAssistant, data: Mapping[str, Any],
                   options: Mapping[str, Any], *,
                   keep_connection: bool | None = None,
                   linger: float | None = None,
                   energy: bool = True) -> Charger:
    """The charger of an entry; raises when it was not seen nearby.

    ``keep_connection`` and ``linger`` override the options; the config flow
    probes without them and without the energy store.
    """

    address = data[CONF_ADDRESS]
    device = bluetooth.async_ble_device_from_address(hass, address,
                                                     connectable=True)
    if device is None:
        raise ChargerConnectionError(
            f'charger {address} is not in range of a connectable Bluetooth '
            f'adapter or proxy')
    if keep_connection is None:
        keep_connection = bool(options.get(OPTION_KEEP_CONNECTION,
                                           DEFAULT_KEEP_CONNECTION))
    timings = A2687Timings(update_interval=float(options.get(
        OPTION_READ_INTERVAL, DEFAULT_READ_INTERVAL)))
    if linger is not None:
        timings = A2687Timings(update_interval=timings.update_interval,
                               linger=linger)

    def latest_device() -> BLEDevice | None:
        return bluetooth.async_ble_device_from_address(hass, address,
                                                       connectable=True)

    serial = data.get(CONF_SERIAL)
    return ble_charger(device, owner_id=data.get(CONF_OWNER_ID) or None,
                       client_id=data[CONF_CLIENT_ID],
                       country=data.get(CONF_COUNTRY) or DEFAULT_COUNTRY,
                       keep_connection=keep_connection,
                       info=DeviceInfo(serial=serial, name=BLUETOOTH_NAME),
                       energy_store=HomeAssistantStore(hass) if energy
                       else None,
                       timings=timings, ble_device_callback=latest_device)


def identity_from(data: Mapping[str, Any], title: str) -> ChargerIdentity:
    return ChargerIdentity(data[CONF_SERIAL], title, 'A2687',
                           address=data[CONF_ADDRESS])
