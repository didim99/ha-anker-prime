"""Actions on the integration's switches, selects and sensors.

Switch actions target output switches (schedules, countdowns) or the clock
switch (clock schedule). Select actions target the charging mode select
(custom limits), the custom profile select (stored profiles) or the clock
picture select (own pictures). Sensor actions target the 160W's screen
picture sensor. Other entities of the domain reject them.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.select import DOMAIN as SELECT_DOMAIN
from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.core import (
    HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse, callback)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.service import async_register_platform_entity_service
from homeassistant.helpers.typing import VolSchemaType

from ankerprime.model import ScheduleSlot

from .const import DOMAIN
from .select import PROFILE_PORT_FIELDS
from .sensor import ScreenPictureSensor
from .switch import WEEKDAYS


WEEKDAY_LIST = vol.All(cv.ensure_list, [vol.In(list(WEEKDAYS))])
SLOT = vol.In([slot.value for slot in ScheduleSlot])

PROFILE_NUMBER = vol.All(vol.Coerce(int), vol.Range(min=1, max=4))
WATTS = vol.All(vol.Coerce(int), vol.Range(min=0, max=140))
LIMIT_FIELDS = {**{vol.Optional(field): WATTS
                   for field in PROFILE_PORT_FIELDS.values()},
                vol.Optional('auto_exit'): cv.boolean}
PICTURE_ID = vol.All(vol.Coerce(int), vol.Range(min=0, max=0xFFFFFFFF))
FILE = vol.All(cv.string, vol.Length(min=1))


def hex_u32(value: Any) -> int:
    """A CRC-32 as printed by an upload: hexadecimal, ``0x`` optional."""

    try:
        number = int(str(value).strip().lower().removeprefix('0x'), 16)
    except ValueError:
        raise vol.Invalid(f'not a hexadecimal number: {value!r}') from None
    if not 0 <= number <= 0xFFFFFFFF:
        raise vol.Invalid(f'out of range: {value!r}')
    return number

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
    'set_custom_limits': (cv.make_entity_service_schema({
        vol.Optional('number'): PROFILE_NUMBER,
        **LIMIT_FIELDS,
    }), 'async_set_custom_limits'),
    'save_custom_profile': (cv.make_entity_service_schema({
        vol.Required('number'): PROFILE_NUMBER,
        vol.Optional('name'): vol.All(cv.string, vol.Length(min=1, max=20)),
        **LIMIT_FIELDS,
    }), 'async_save_custom_profile'),
    'delete_custom_profile': (cv.make_entity_service_schema({
        vol.Required('number'): PROFILE_NUMBER,
    }), 'async_delete_custom_profile'),
    'upload_clock_picture': (cv.make_entity_service_schema({
        vol.Required('file'): FILE,
    }), 'async_upload_clock_picture'),
    'delete_clock_picture': (cv.make_entity_service_schema({
        vol.Required('picture_id'): PICTURE_ID,
    }), 'async_delete_clock_picture'),
}


async def _upload_screen_picture(entity: Entity, call: ServiceCall
                                 ) -> ServiceResponse:
    sensor = _screen_picture_sensor(entity, call.service)
    return await sensor.async_upload(call.data['file'])


async def _select_screen_picture(entity: Entity, call: ServiceCall) -> None:
    sensor = _screen_picture_sensor(entity, call.service)
    await sensor.async_select(call.data['picture_id'], call.data['crc32'])


def _screen_picture_sensor(entity: Entity, action: str
                           ) -> ScreenPictureSensor:
    if not isinstance(entity, ScreenPictureSensor):
        raise ServiceValidationError(
            f'{entity.entity_id} does not support the {action} action')
    return entity


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    for domain, services in ((SWITCH_DOMAIN, SWITCH_SERVICES),
                             (SELECT_DOMAIN, SELECT_SERVICES)):
        for name, (schema, method) in services.items():
            async_register_platform_entity_service(
                hass, DOMAIN, name, entity_domain=domain, schema=schema,
                func=method)
    # Writing is irreversible: the action states it and must be confirmed.
    async_register_platform_entity_service(
        hass, DOMAIN, 'upload_screen_picture', entity_domain=SENSOR_DOMAIN,
        schema=cv.make_entity_service_schema({
            vol.Required('file'): FILE,
            vol.Required('acknowledge_irreversible'): vol.All(
                cv.boolean, vol.IsTrue('confirm that the picture cannot '
                                       'be removed from the charger')),
        }),
        func=_upload_screen_picture,
        supports_response=SupportsResponse.OPTIONAL)
    async_register_platform_entity_service(
        hass, DOMAIN, 'select_screen_picture', entity_domain=SENSOR_DOMAIN,
        schema=cv.make_entity_service_schema({
            vol.Required('picture_id'): PICTURE_ID,
            vol.Required('crc32'): hex_u32,
        }),
        func=_select_screen_picture)
