"""Actions on the integration's switches and selects.

Switch actions target output switches (schedules, countdowns) or the clock
switch (clock schedule); select actions target the custom profile select.
Other entities of the domain reject them.
"""

from __future__ import annotations

import voluptuous as vol

from homeassistant.components.select import DOMAIN as SELECT_DOMAIN
from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.service import async_register_platform_entity_service
from homeassistant.helpers.typing import VolSchemaType

from ankerprime.model import ScheduleSlot

from .const import DOMAIN
from .select import PROFILE_PORT_FIELDS
from .switch import WEEKDAYS


WEEKDAY_LIST = vol.All(cv.ensure_list, [vol.In(list(WEEKDAYS))])
SLOT = vol.In([slot.value for slot in ScheduleSlot])

PROFILE_NUMBER = vol.All(vol.Coerce(int), vol.Range(min=1, max=4))
WATTS = vol.All(vol.Coerce(int), vol.Range(min=0, max=140))

SWITCH_SERVICES: dict[str, tuple[VolSchemaType, str]] = {
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

SELECT_SERVICES: dict[str, tuple[VolSchemaType, str]] = {
    'save_custom_profile': (cv.make_entity_service_schema({
        vol.Required('number'): PROFILE_NUMBER,
        vol.Optional('name'): vol.All(cv.string, vol.Length(min=1, max=20)),
        **{vol.Optional(field): WATTS
           for field in PROFILE_PORT_FIELDS.values()},
        vol.Optional('auto_exit'): cv.boolean,
    }), 'async_save_custom_profile'),
    'delete_custom_profile': (cv.make_entity_service_schema({
        vol.Required('number'): PROFILE_NUMBER,
    }), 'async_delete_custom_profile'),
}


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    for domain, services in ((SWITCH_DOMAIN, SWITCH_SERVICES),
                             (SELECT_DOMAIN, SELECT_SERVICES)):
        for name, (schema, method) in services.items():
            async_register_platform_entity_service(
                hass, DOMAIN, name, entity_domain=domain, schema=schema,
                func=method)
