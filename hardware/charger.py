"""The charger under test, seen through Home Assistant.

Writes go through the integration's entities and actions; read-backs use
the entity states and the entry's diagnostics, which hold the full charger
state.
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest

from ankerprime.cloud.auth import AccountCredentials
from ankerprime.model import A2345, OutputId, Product, Weekday

from hardware.api import HomeAssistantApi, JsonObject


DOMAIN = 'anker_prime'
# Entities left disabled: pressing would change something for good.
KEEP_DISABLED = frozenset({'reset_energy'})
WEEKDAYS = {'mon': Weekday.MONDAY, 'tue': Weekday.TUESDAY,
            'wed': Weekday.WEDNESDAY, 'thu': Weekday.THURSDAY,
            'fri': Weekday.FRIDAY, 'sat': Weekday.SATURDAY,
            'sun': Weekday.SUNDAY}
PICTURE_THEMES = ('picture', 'custom')
OWN_PREFIX = 'Own '
UNAVAILABLE = 'unavailable'
POLL_INTERVAL = 1.0

Fingerprint = dict[str, Any]


class EntryError(Exception):
    """The config flow did not create the entry."""


async def add_cloud_entry(api: HomeAssistantApi,
                          credentials: AccountCredentials,
                          serial: str | None) -> tuple[str, str]:
    """Run the email sign-in flow for one charger; entry ID and serial.

    Without ``serial`` the account must have exactly one charger.
    """

    flow = await api.start_flow(DOMAIN)
    flow_id = flow['flow_id']
    flow = await api.configure_flow(flow_id, {'next_step_id': 'cloud'})
    flow = await api.configure_flow(flow_id, {
        'email': credentials.email, 'password': credentials.password,
        'country': credentials.country})
    if flow.get('step_id') != 'chargers':
        raise EntryError(f'sign-in not accepted: {_outcome(flow)}')
    offered = [option['value'] for option
               in _field(flow, 'serials')['selector']['select']['options']]
    if serial is None:
        if len(offered) != 1:
            raise EntryError('the account has several chargers; choose one '
                             f'with --hardware-serial: {offered}')
        serial = offered[0]
    elif serial not in offered:
        raise EntryError(f'{serial} is not offered: {offered}')
    flow = await api.configure_flow(flow_id, {'serials': [serial]})
    if flow.get('type') != 'create_entry':
        raise EntryError(f'no entry created: {_outcome(flow)}')
    return flow['result']['entry_id'], serial


def _field(flow: JsonObject, name: str) -> JsonObject:
    for field in flow.get('data_schema') or ():
        if field['name'] == name:
            return field
    raise EntryError(f'form {flow.get("step_id")} has no {name} field')


def _outcome(flow: JsonObject) -> str:
    return (f'{flow.get("type")} {flow.get("step_id") or ""} '
            f'{flow.get("errors") or flow.get("reason") or ""}').strip()


@dataclass(init=False)
class Snapshot:
    """Entity states by key and the charger state from diagnostics."""

    _states: dict[str, JsonObject]
    _charger: JsonObject

    def __init__(self, states: dict[str, JsonObject], charger: JsonObject):
        self._states = states
        self._charger = charger

    @property
    def charger(self) -> JsonObject:
        """``state_to_dict`` of the library's state."""

        return self._charger

    @property
    def settings(self) -> JsonObject:
        return self._charger['settings']

    @property
    def clock(self) -> JsonObject | None:
        return self.settings['clock']

    def output(self, output: OutputId) -> JsonObject:
        return self._charger['outputs'][output.value]

    def state(self, key: str) -> str | None:
        found = self._states.get(key)
        return None if found is None else found['state']

    def attributes(self, key: str) -> JsonObject:
        found = self._states.get(key)
        return {} if found is None else found['attributes']

    def options(self, key: str) -> list[str]:
        return list(self.attributes(key).get('options') or ())

    def profile(self, number: int) -> JsonObject | None:
        for profile in self.settings['custom_profiles'] or ():
            if profile['number'] == number:
                return profile
        return None

    def fingerprint(self) -> Fingerprint:
        """Every value the tests change, for comparing before and after.

        Controls as Home Assistant shows them, and the charger's settings and
        outputs as the library reads them.
        """

        values: Fingerprint = {}
        for key, state in self._states.items():
            domain = state['entity_id'].split('.')[0]
            if domain not in ('switch', 'select', 'number'):
                continue
            values[key] = state['state']
            attributes = state['attributes']
            if domain == 'switch':
                values[f'{key}.attributes'] = attributes
            elif domain == 'select':
                values[f'{key}.options'] = attributes.get('options')
        settings = dict(self.settings)
        settings.pop('updating_firmware', None)
        values.update(_flatten('settings', settings))
        for output, control in self._charger['outputs'].items():
            values[f'outputs.{output}'] = {
                **control, 'countdown': control['countdown'] is not None,
                # Reported only in some modes; unknown counts as not preferred.
                'preferred': bool(control['preferred'])}
        return values


@dataclass(init=False)
class ChargerUnderTest:
    """One charger of a loaded entry and its entities by key.

    Keys are the integration's unique ID suffixes (``c1_output``,
    ``brightness``, …).
    """

    _api: HomeAssistantApi
    _entry_id: str
    _serial: str
    _entities: dict[str, str]
    _settle: float
    _timeout: float

    def __init__(self, api: HomeAssistantApi, entry_id: str, serial: str, *,
                 settle: float, timeout: float):
        self._api = api
        self._entry_id = entry_id
        self._serial = serial
        self._entities = {}
        self._settle = settle
        self._timeout = timeout

    @property
    def api(self) -> HomeAssistantApi:
        return self._api

    @property
    def entry_id(self) -> str:
        return self._entry_id

    @property
    def product(self) -> Product:
        return A2345

    @property
    def entities(self) -> dict[str, str]:
        return dict(self._entities)

    async def discover(self, *, enable: bool) -> list[str]:
        """Find the charger's entities; ``enable`` turns on disabled ones.

        The entities enabled, to be loaded with a reload of the entry.
        """

        prefix = f'{self._serial}_'
        enabled = []
        for entry in await self._api.entity_registry():
            unique_id = entry.get('unique_id') or ''
            if (entry.get('platform') != DOMAIN
                    or not unique_id.startswith(prefix)):
                continue
            key = unique_id[len(prefix):]
            self._entities[key] = entry['entity_id']
            if (enable and entry.get('disabled_by')
                    and key not in KEEP_DISABLED):
                await self._api.enable_entity(entry['entity_id'])
                enabled.append(entry['entity_id'])
        return enabled

    async def reload(self) -> None:
        """Reload the entry: a new connection reads everything again."""

        await self._api.reload_entry(self._entry_id)
        await self._api.wait_for_entry(self._entry_id, self._timeout)
        await self.wait_available()

    async def wait_available(self) -> None:
        """Wait until the refresh button is available: the charger is."""

        entity_id = self.entity('refresh')
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._timeout
        while True:
            states = await self._api.states()
            state = states.get(entity_id)
            if state is not None and state['state'] != UNAVAILABLE:
                return
            if loop.time() > deadline:
                raise AssertionError(
                    f'the charger is unavailable after {self._timeout:g} s')
            await asyncio.sleep(POLL_INTERVAL)

    def entity(self, key: str) -> str:
        """The entity ID of a key; skips when there is no such entity."""

        entity_id = self._entities.get(key)
        if entity_id is None:
            pytest.skip(f'no {key} entity: not offered for this charger')
        return entity_id

    async def need(self, *keys: str) -> Snapshot:
        """Skip unless every entity exists and is available; a snapshot."""

        snapshot = await self.snapshot()
        for key in keys:
            self.entity(key)
            if snapshot.state(key) in (None, UNAVAILABLE):
                pytest.skip(f'{key} unavailable: the charger does not '
                            'offer it')
        return snapshot

    async def snapshot(self) -> Snapshot:
        """Current entity states and diagnostics, without a refresh."""

        states = await self._api.states()
        by_key = {key: states[entity_id]
                  for key, entity_id in self._entities.items()
                  if entity_id in states}
        diagnostics = await self._api.diagnostics(self._entry_id)
        chargers = diagnostics['chargers']
        assert len(chargers) == 1, f'{len(chargers)} chargers in the entry'
        return Snapshot(by_key, chargers[0]['state'])

    async def settled(self, *, account: bool = False) -> Snapshot:
        """The snapshot after a refresh: what the charger itself reports.

        A write already updates the state once acknowledged; the refresh
        shows whether the charger kept it. ``account`` reloads the entry
        first, so the account's settings and profiles are read again too.
        """

        if account:
            await self.reload()
        await self.press('refresh')
        await asyncio.sleep(self._settle)
        return await self.snapshot()

    async def expect(self, check: Callable[[Snapshot], bool], what: str, *,
                     account: bool = False) -> Snapshot:
        """Assert ``check`` on the read-back snapshot."""

        snapshot = await self.settled(account=account)
        assert check(snapshot), f'Home Assistant does not report {what}'
        return snapshot

    # Actions.

    async def call(self, domain: str, service: str, key: str,
                   data: dict[str, Any] | None = None, *,
                   return_response: bool = False) -> Any:
        return await self._api.call(domain, service, self.entity(key), data,
                                    return_response=return_response)

    async def action(self, service: str, key: str, **data: Any) -> None:
        """One of the integration's own actions."""

        await self.call(DOMAIN, service, key, data)

    async def turn(self, key: str, on: bool) -> None:
        await self.call('switch', 'turn_on' if on else 'turn_off', key)

    async def select(self, key: str, option: str) -> None:
        await self.call('select', 'select_option', key, {'option': option})

    async def set_number(self, key: str, value: float) -> None:
        await self.call('number', 'set_value', key, {'value': value})

    async def press(self, key: str) -> None:
        await self.call('button', 'press', key)

    async def picture_options(self) -> list[str]:
        """The clock picture select's options, once loaded."""

        self.entity('clock_picture')
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._timeout
        while True:
            options = (await self.snapshot()).options('clock_picture')
            if options:
                return options
            if loop.time() > deadline:
                raise AssertionError('the clock pictures were not loaded')
            await asyncio.sleep(POLL_INTERVAL)

    # Restoring.

    async def restore_clock(self, original: JsonObject) -> None:
        """Put back the clock as found: theme or picture, switch, extras.

        Compares with a fresh read-back: a write that failed may still have
        been applied.
        """

        clock = (await self.settled()).clock
        assert clock is not None
        theme = original['theme']
        picture_id = original['picture_id']
        if theme in PICTURE_THEMES and picture_id is not None:
            if clock['theme'] != theme or clock['picture_id'] != picture_id:
                await self.select('clock_picture', picture_option(
                    await self.picture_options(), picture_id,
                    own=theme == 'custom'))
            if not original['enabled']:
                await self.turn('clock', False)
        else:
            if clock['theme'] != theme and theme is not None:
                await self.select('clock_theme', theme)
            if clock['enabled'] != original['enabled']:
                await self.turn('clock', original['enabled'])
        clock = (await self.snapshot()).clock
        assert clock is not None
        if (original['holiday_theme'] is not None
                and clock['holiday_theme'] != original['holiday_theme']):
            await self.turn('holiday_theme', original['holiday_theme'])
        schedule = original['schedule']
        if schedule is not None and clock['schedule'] != schedule:
            await self.action('set_clock_schedule', 'clock',
                              **clock_schedule_fields(schedule))
        if (original['picture_time'] is not None
                and clock['picture_time'] != original['picture_time']):
            await self.turn('picture_time', original['picture_time'])

    async def restore_switches(self, max_compatibility: bool,
                               device_identification: bool) -> None:
        """Put back the two exclusive switches.

        Switching one on switches the other off, so the one that was on goes
        last; with both off, each is switched off.
        """

        settings = (await self.settled(account=True)).settings
        if max_compatibility:
            await self.turn('max_compatibility', True)
        elif device_identification:
            await self.turn('device_identification', True)
        else:
            if settings['max_compatibility']:
                await self.turn('max_compatibility', False)
            if settings['device_identification']:
                await self.turn('device_identification', False)

    def idle_output(self, snapshot: Snapshot) -> OutputId:
        """An output that is on, without a countdown and powering nothing.

        Skips when every output is busy, so no plugged-in device is cut off.
        """

        ports = snapshot.charger['ports']
        for spec in reversed(self.product.outputs):
            control = snapshot.output(spec.output)
            if not control['is_on'] or control['countdown'] is not None:
                continue
            readings = [ports.get(port.value) for port in spec.ports]
            if all(reading is not None and not reading['delivering']
                   and reading['power'] < 0.5 for reading in readings):
                return spec.output
        pytest.skip('no idle output: every output is off or powers a device')


def _flatten(prefix: str, values: JsonObject) -> Fingerprint:
    """Nested objects as dotted keys, so a difference names its field."""

    flat: Fingerprint = {}
    for key, value in values.items():
        if isinstance(value, dict):
            flat.update(_flatten(f'{prefix}.{key}', value))
        else:
            flat[f'{prefix}.{key}'] = value
    return flat


def picture_option(options: list[str], picture_id: int, *, own: bool) -> str:
    """The clock picture select's option of a picture."""

    if own:
        option = f'{OWN_PREFIX}{picture_id}'
        if option in options:
            return option
    else:
        for option in options:
            if (not option.startswith(OWN_PREFIX)
                    and option.endswith(f'({picture_id})')):
                return option
    raise AssertionError(f'clock picture {picture_id} not offered to restore')


def own_picture_ids(options: list[str]) -> set[int]:
    return {int(option[len(OWN_PREFIX):]) for option in options
            if option.startswith(OWN_PREFIX)}


def weekday_names(days: int) -> list[str]:
    return [name for name, day in WEEKDAYS.items() if days & day]


def schedule_fields(schedule: JsonObject) -> dict[str, Any]:
    """``set_schedule`` fields of a schedule from diagnostics."""

    return {'time': f'{schedule["time"]}:00', 'enabled': schedule['enabled'],
            'weekdays': weekday_names(schedule['weekdays'])}


def clock_schedule_fields(schedule: JsonObject) -> dict[str, Any]:
    """``set_clock_schedule`` fields of a clock schedule from diagnostics."""

    return {'start': f'{schedule["start"]}:00',
            'end': f'{schedule["end"]}:00',
            'weekdays': weekday_names(schedule['weekdays'])}
