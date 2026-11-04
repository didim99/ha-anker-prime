"""Diagnostics: entry settings and each charger's state, secrets redacted."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant

from ankerprime.model.serialize import state_to_dict

from .const import CONF_AUTHENTICATION, CONF_SERIALS
from .coordinator import AnkerPrimeConfigEntry


TO_REDACT = {CONF_EMAIL, CONF_PASSWORD, CONF_AUTHENTICATION, CONF_SERIALS,
             'serial', 'mac_address', 'usb_vendor_id', 'usb_product_id'}


async def async_get_config_entry_diagnostics(
        hass: HomeAssistant, entry: AnkerPrimeConfigEntry) -> dict[str, Any]:
    chargers = []
    for coordinator in entry.runtime_data.coordinators.values():
        last_error = coordinator.charger.last_error
        chargers.append({
            'product_code': coordinator.device.product_code,
            'wifi_online': coordinator.device.wifi_online,
            'last_error': repr(last_error) if last_error else None,
            'state': state_to_dict(coordinator.data),
        })
    return async_redact_data({
        'entry': {'data': dict(entry.data), 'options': dict(entry.options)},
        'chargers': chargers,
    }, TO_REDACT)
