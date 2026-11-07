"""Anker Prime chargers in Home Assistant, through anker-prime-driver.

Two entry types:

- cloud: one entry per Anker account; each selected charger becomes a device
  with its own coordinator, and all share the account's MQTT connection;
- Bluetooth: one entry per 160W, connected through Home Assistant's
  Bluetooth stack (local adapters or proxies).
"""

from __future__ import annotations

import logging

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from ankerprime.api.cloud import CloudAccount
from ankerprime.cloud.auth import Authentication
from ankerprime.energy.store import EnergyStore
from ankerprime.model import AnkerPrimeError, AuthenticationError

from .account import async_create_account
from .ble import create_charger, identity_from
from .const import (
    CONF_AUTHENTICATION, CONF_SERIAL, CONF_SERIALS, DOMAIN, is_bluetooth)
from .coordinator import (
    AnkerPrimeConfigEntry, AnkerPrimeCoordinator, AnkerPrimeData,
    ChargerIdentity)
from .services import async_setup_services
from .storage import HomeAssistantStore


PLATFORMS = [Platform.BINARY_SENSOR, Platform.BUTTON, Platform.NUMBER,
             Platform.SELECT, Platform.SENSOR, Platform.SWITCH]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

logger = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant,
                            entry: AnkerPrimeConfigEntry) -> bool:
    if is_bluetooth(entry.data):
        await _async_setup_bluetooth(hass, entry)
    else:
        await _async_setup_cloud(hass, entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_setup_cloud(hass: HomeAssistant,
                             entry: AnkerPrimeConfigEntry) -> None:
    @callback
    def remember_token(authentication: Authentication) -> None:
        data = {**entry.data,
                CONF_AUTHENTICATION: authentication.to_document()}
        hass.config_entries.async_update_entry(entry, data=data)

    try:
        account = await async_create_account(hass, entry.data, remember_token)
    except AuthenticationError as error:
        raise ConfigEntryAuthFailed(str(error)) from error
    except AnkerPrimeError as error:
        raise ConfigEntryNotReady(str(error)) from error
    try:
        coordinators = await _async_start_chargers(hass, entry, account)
    except BaseException:
        await account.close()
        raise
    entry.runtime_data = AnkerPrimeData(account, coordinators)


async def _async_setup_bluetooth(hass: HomeAssistant,
                                 entry: AnkerPrimeConfigEntry) -> None:
    try:
        charger = create_charger(hass, entry.data, entry.options)
    except AnkerPrimeError as error:
        raise ConfigEntryNotReady(str(error)) from error
    coordinator = AnkerPrimeCoordinator(hass, entry, charger,
                                        identity_from(entry.data, entry.title))
    try:
        await coordinator.async_start()
    except BaseException as error:
        await coordinator.async_close()
        if isinstance(error, AuthenticationError):
            raise ConfigEntryAuthFailed(str(error)) from error
        if isinstance(error, AnkerPrimeError):
            raise ConfigEntryNotReady(str(error)) from error
        raise
    entry.runtime_data = AnkerPrimeData(None, {coordinator.serial:
                                               coordinator})


async def async_unload_entry(hass: HomeAssistant,
                             entry: AnkerPrimeConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry,
                                                               PLATFORMS)
    if unloaded:
        data = entry.runtime_data
        for coordinator in data.coordinators.values():
            if data.account is None:
                await coordinator.async_close()
            else:
                coordinator.async_stop()
        if data.account is not None:
            await data.account.close()
    return unloaded


async def async_remove_entry(hass: HomeAssistant,
                             entry: AnkerPrimeConfigEntry) -> None:
    """Delete the stored energy counters of the entry's chargers."""

    store = HomeAssistantStore(hass)
    serials = list(entry.data.get(CONF_SERIALS, []))
    if CONF_SERIAL in entry.data:
        serials.append(entry.data[CONF_SERIAL])
    for serial in serials:
        await store.delete(EnergyStore.for_serial(store, serial).key)


async def _async_start_chargers(hass: HomeAssistant,
                                entry: AnkerPrimeConfigEntry,
                                account: CloudAccount
                                ) -> dict[str, AnkerPrimeCoordinator]:
    try:
        devices = {device.serial: device
                   for device in await account.bound_devices()}
    except AuthenticationError as error:
        raise ConfigEntryAuthFailed(str(error)) from error
    except AnkerPrimeError as error:
        raise ConfigEntryNotReady(str(error)) from error
    coordinators: dict[str, AnkerPrimeCoordinator] = {}
    for serial in entry.data[CONF_SERIALS]:
        device = devices.get(serial)
        if device is None:
            logger.warning('Charger ...%s is no longer bound to %s; skipped',
                           serial[-4:], entry.title)
            continue
        coordinator = AnkerPrimeCoordinator(
            hass, entry, account.charger(device),
            ChargerIdentity.from_bound_device(device))
        coordinators[serial] = coordinator
    try:
        for coordinator in coordinators.values():
            await coordinator.async_start()
    except AuthenticationError as error:
        _stop(coordinators)
        raise ConfigEntryAuthFailed(str(error)) from error
    except AnkerPrimeError as error:
        _stop(coordinators)
        raise ConfigEntryNotReady(str(error)) from error
    return coordinators


def _stop(coordinators: dict[str, AnkerPrimeCoordinator]) -> None:
    for coordinator in coordinators.values():
        coordinator.async_stop()
