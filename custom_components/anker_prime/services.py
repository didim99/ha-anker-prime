"""Actions on the integration's switches: schedules, countdowns, clock.

They target output switches (schedules, countdowns) or the clock switch
(clock schedule); other switches reject them.
"""

from __future__ import annotations

import voluptuous as vol

from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.service import async_register_platform_entity_service
from homeassistant.helpers.typing import VolSchemaType

from ankerprime.model import ScheduleSlot

from .const import DOMAIN
from .switch import WEEKDAYS


WEEKDAY_LIST = vol.All(cv.ensure_list, [vol.In(list(WEEKDAYS))])
SLOT = vol.In([slot.value for slot in ScheduleSlot])

SERVICES: dict[str, tuple[VolSchemaType, str]] = {
    'set_schedule': (cv.make_entity_service_schema({
        vol.Required('slot'): SLOT,
        vol.Required('time'): cv.time,
        vol.Optional('weekdays'): WEEKDAY_LIST,
        vol.Optional('enabled', default=True): cv.boolean,
    }), 'async_set_schedule'),
    'disable_schedule': (cv.make_entity_service_schema({
        vol.Required('slot'): SLOT,
    }), 'async_disable_schedule'),
    'start_countdown': (cv.make_entity_service_schema({
        vol.Required('duration'): vol.All(cv.time_period,
                                          cv.positive_timedelta),
    }), 'async_start_countdown'),
    'cancel_countdown': (cv.make_entity_service_schema({}),
                         'async_cancel_countdown'),
    'set_clock_schedule': (cv.make_entity_service_schema({
        vol.Required('start'): cv.time,
        vol.Required('end'): cv.time,
        vol.Optional('weekdays'): WEEKDAY_LIST,
    }), 'async_set_clock_schedule'),
}


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    for name, (schema, method) in SERVICES.items():
        async_register_platform_entity_service(
            hass, DOMAIN, name, entity_domain=SWITCH_DOMAIN, schema=schema,
            func=method)
