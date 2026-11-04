"""One coordinator per charger, fed by the library's push updates.

The library publishes a new state on every telemetry frame (about once a
second) and integrates energy at that rate. Entities are updated at most once
per configured interval; a change of availability passes at once. A periodic
health check starts reauthentication when the library gave up on the token
and raises a repair issue while a charger stays offline.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import (
    async_call_later, async_track_time_interval)
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from ankerprime.api.cloud import CloudAccount
from ankerprime.cloud.client import BoundDevice
from ankerprime.interfaces.charger import Charger, Unsubscribe
from ankerprime.model import AuthenticationError, ChargerState

from .const import (
    DEFAULT_UPDATE_INTERVAL, DOMAIN, HEALTH_CHECK_INTERVAL,
    OFFLINE_ISSUE_AFTER, OPTION_UPDATE_INTERVAL)


logger = logging.getLogger(__name__)


@dataclass
class AnkerPrimeData:
    """Runtime data of a config entry."""

    account: CloudAccount
    coordinators: dict[str, AnkerPrimeCoordinator]


AnkerPrimeConfigEntry = ConfigEntry[AnkerPrimeData]


class AnkerPrimeCoordinator(DataUpdateCoordinator[ChargerState]):
    """Throttles one charger's states for its entities."""

    _charger: Charger
    _device: BoundDevice
    _interval: float

    _latest: ChargerState
    _pushed_at: float | None
    _pending: CALLBACK_TYPE | None
    _unsubscribe: Unsubscribe | None
    _stop_health_check: CALLBACK_TYPE | None
    _offline_since: datetime | None
    _reauth_started: bool

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry,
                 charger: Charger, device: BoundDevice):
        super().__init__(hass, logger, config_entry=entry,
                         name=f'{DOMAIN} {device.serial[-4:]}',
                         update_interval=None, always_update=False)
        self._charger = charger
        self._device = device
        self._interval = float(entry.options.get(OPTION_UPDATE_INTERVAL,
                                                 DEFAULT_UPDATE_INTERVAL))
        self._latest = charger.state
        self.data = charger.state
        self._pushed_at = None
        self._pending = None
        self._unsubscribe = None
        self._stop_health_check = None
        self._offline_since = None
        self._reauth_started = False

    @property
    def charger(self) -> Charger:
        return self._charger

    @property
    def device(self) -> BoundDevice:
        return self._device

    @property
    def serial(self) -> str:
        return self._device.serial

    async def async_start(self) -> None:
        """Subscribe and connect; raises when the first connection fails."""

        self._unsubscribe = self._charger.subscribe(self._on_state)
        self._stop_health_check = async_track_time_interval(
            self.hass, self._check_health, HEALTH_CHECK_INTERVAL,
            cancel_on_shutdown=True)
        await self._charger.connect()

    @callback
    def async_stop(self) -> None:
        for stop in (self._unsubscribe, self._stop_health_check,
                     self._pending):
            if stop is not None:
                stop()
        self._unsubscribe = None
        self._stop_health_check = None
        self._pending = None

    @callback
    def _on_state(self, state: ChargerState) -> None:
        self._latest = state
        if state.available != self.data.available:
            self._push()
            return
        if self._pending is not None:
            return
        wait = 0.0
        if self._pushed_at is not None:
            wait = self._pushed_at + self._interval - self.hass.loop.time()
        if wait <= 0:
            self._push()
        else:
            self._pending = async_call_later(self.hass, wait, self._flush)

    @callback
    def _flush(self, _now: datetime) -> None:
        self._pending = None
        self._push()

    @callback
    def _push(self) -> None:
        if self._pending is not None:
            self._pending()
            self._pending = None
        self._pushed_at = self.hass.loop.time()
        state = self._latest
        self._update_device_registry(state)
        self._track_offline(state, dt_util.utcnow())
        self.async_set_updated_data(state)

    @callback
    def _check_health(self, now: datetime) -> None:
        if (isinstance(self._charger.last_error, AuthenticationError)
                and not self._reauth_started and self.config_entry is not None):
            self._reauth_started = True
            logger.warning('Anker account of %s needs signing in again',
                           self.config_entry.title)
            self.config_entry.async_start_reauth(self.hass)
        self._track_offline(self._latest, now)

    @callback
    def _track_offline(self, state: ChargerState, now: datetime) -> None:
        issue_id = f'offline_{self.serial}'
        if state.available:
            if self._offline_since is not None:
                self._offline_since = None
                ir.async_delete_issue(self.hass, DOMAIN, issue_id)
            return
        if self._offline_since is None:
            self._offline_since = now
        if now - self._offline_since >= OFFLINE_ISSUE_AFTER:
            ir.async_create_issue(
                self.hass, DOMAIN, issue_id, is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key='charger_offline',
                translation_placeholders={'name': self._device.display_name})

    @callback
    def _update_device_registry(self, state: ChargerState) -> None:
        firmware = state.info.firmware_version
        if firmware is None or firmware == self.data.info.firmware_version:
            return
        if self.config_entry is None:
            return
        registry = dr.async_get(self.hass)
        identifier = (DOMAIN, self.serial)
        for device in dr.async_entries_for_config_entry(
                registry, self.config_entry.entry_id):
            if identifier in device.identifiers and (
                    device.sw_version != firmware):
                registry.async_update_device(device.id, sw_version=firmware)
