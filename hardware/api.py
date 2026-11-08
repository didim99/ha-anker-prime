"""Home Assistant's REST and websocket APIs, as the frontend uses them."""

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Self

import aiohttp


USER_NAME = 'hardware'
USER_PASSWORD = 'anker-prime-hardware'
TOKEN_NAME = 'anker-prime hardware tests'
POLL_INTERVAL = 1.0
# Entity registry lists and diagnostics can be large.
MAX_MESSAGE_SIZE = 64 * 1024 * 1024

JsonObject = dict[str, Any]


class HomeAssistantApiError(Exception):
    """A request Home Assistant answered with an error."""


class ServiceError(HomeAssistantApiError):
    """An action call Home Assistant refused or that failed."""

    _code: str

    def __init__(self, code: str, message: str):
        super().__init__(f'{code}: {message}')
        self._code = code

    @property
    def code(self) -> str:
        """``service_validation_error``, ``home_assistant_error``, …"""

        return self._code


@dataclass(init=False)
class HomeAssistantApi:
    """The administrator of a freshly started Home Assistant.

    Use as an async context manager; ``onboard`` creates the administrator
    and signs in with a long-lived token.
    """

    _url: str
    _session: aiohttp.ClientSession
    _token: str | None
    _websocket: aiohttp.ClientWebSocketResponse | None
    _lock: asyncio.Lock
    _next_id: int

    def __init__(self, url: str):
        self._url = url
        self._session = aiohttp.ClientSession()
        self._token = None
        self._websocket = None
        self._lock = asyncio.Lock()
        self._next_id = 1

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, kind: type[BaseException] | None,
                        error: BaseException | None,
                        traceback: TracebackType | None) -> None:
        await self.close()

    @property
    def url(self) -> str:
        return self._url

    async def close(self) -> None:
        if self._websocket is not None:
            await self._websocket.close()
        await self._session.close()

    # Start-up and sign-in.

    async def wait_until_up(self, timeout: float,
                            alive: Callable[[], Awaitable[bool]]) -> None:
        """Wait until Home Assistant answers the onboarding status.

        ``alive`` tells whether Home Assistant still runs.
        """

        deadline = time.monotonic() + timeout
        while True:
            if not await alive():
                raise HomeAssistantApiError(
                    'Home Assistant stopped while starting; see its log')
            try:
                async with self._session.get(
                        f'{self._url}/api/onboarding') as response:
                    if response.status == 200:
                        return
            except aiohttp.ClientError:
                pass
            if time.monotonic() > deadline:
                raise HomeAssistantApiError(
                    f'Home Assistant not up after {timeout:g} s')
            await asyncio.sleep(POLL_INTERVAL)

    async def onboard(self) -> None:
        """Create the owner, sign in and switch to a long-lived token."""

        client_id = f'{self._url}/'
        created = await self._post_json('/api/onboarding/users', {
            'client_id': client_id, 'name': 'Hardware tests',
            'username': USER_NAME, 'password': USER_PASSWORD,
            'language': 'en'})
        async with self._session.post(f'{self._url}/auth/token', data={
                'grant_type': 'authorization_code',
                'code': created['auth_code'],
                'client_id': client_id}) as response:
            tokens = await self._json(response)
        self._token = tokens['access_token']
        self._token = await self.command('auth/long_lived_access_token',
                                         client_name=TOKEN_NAME, lifespan=1)

    # Plain requests.

    async def rest(self, method: str, path: str,
                   payload: Mapping[str, Any] | None = None) -> Any:
        """A REST request as the administrator; its JSON answer."""

        async with self._session.request(
                method, f'{self._url}{path}', json=payload,
                headers=self._headers()) as response:
            return await self._json(response)

    async def command(self, kind: str, **data: Any) -> Any:
        """A websocket command; its result."""

        async with self._lock:
            websocket = await self._connected()
            message_id = self._next_id
            self._next_id += 1
            await websocket.send_json({'id': message_id, 'type': kind,
                                       **data})
            while True:
                answer = await websocket.receive_json()
                if answer.get('id') == message_id:
                    break
        if not answer.get('success'):
            error = answer.get('error') or {}
            raise ServiceError(error.get('code', 'unknown'),
                               error.get('message', repr(answer)))
        return answer.get('result')

    # Actions and states.

    async def call(self, domain: str, service: str, entity_id: str,
                   data: Mapping[str, Any] | None = None, *,
                   return_response: bool = False) -> Any:
        """Call an action on an entity and wait for it; its response."""

        result = await self.command(
            'call_service', domain=domain, service=service,
            service_data=dict(data or {}), target={'entity_id': entity_id},
            return_response=return_response)
        if not return_response:
            return None
        return (result or {}).get('response', {}).get(entity_id)

    async def states(self) -> dict[str, JsonObject]:
        """Every entity state by entity ID."""

        return {state['entity_id']: state
                for state in await self.rest('GET', '/api/states')}

    async def entity_registry(self) -> list[JsonObject]:
        return await self.command('config/entity_registry/list')

    async def enable_entity(self, entity_id: str) -> None:
        await self.command('config/entity_registry/update',
                           entity_id=entity_id, disabled_by=None)

    # Config entries.

    async def start_flow(self, handler: str) -> JsonObject:
        return await self.rest('POST', '/api/config/config_entries/flow',
                               {'handler': handler,
                                'show_advanced_options': False})

    async def configure_flow(self, flow_id: str,
                             data: Mapping[str, Any]) -> JsonObject:
        return await self.rest(
            'POST', f'/api/config/config_entries/flow/{flow_id}', data)

    async def set_options(self, entry_id: str,
                          options: Mapping[str, Any]) -> JsonObject:
        """Run the options flow with ``options`` as its only form."""

        flow = await self.rest('POST',
                               '/api/config/config_entries/options/flow',
                               {'handler': entry_id})
        return await self.rest(
            'POST', f'/api/config/config_entries/options/flow/'
                    f'{flow["flow_id"]}', options)

    async def entry(self, entry_id: str) -> JsonObject:
        for entry in await self.rest('GET', '/api/config/config_entries/entry'):
            if entry['entry_id'] == entry_id:
                return entry
        raise HomeAssistantApiError(f'no config entry {entry_id}')

    async def wait_for_entry(self, entry_id: str, timeout: float) -> None:
        """Wait until the entry is loaded; fails on a setup error."""

        deadline = time.monotonic() + timeout
        while True:
            entry = await self.entry(entry_id)
            state = entry['state']
            if state == 'loaded':
                return
            if state in ('setup_error', 'migration_error', 'failed_unload'):
                raise HomeAssistantApiError(
                    f'entry {state}: {entry.get("reason")}')
            if time.monotonic() > deadline:
                raise HomeAssistantApiError(
                    f'entry still {state} after {timeout:g} s: '
                    f'{entry.get("reason")}')
            await asyncio.sleep(POLL_INTERVAL)

    async def reload_entry(self, entry_id: str) -> None:
        await self.rest('POST',
                        f'/api/config/config_entries/entry/{entry_id}/reload')

    async def remove_entry(self, entry_id: str) -> None:
        await self.rest('DELETE',
                        f'/api/config/config_entries/entry/{entry_id}')

    async def diagnostics(self, entry_id: str) -> JsonObject:
        document = await self.rest(
            'GET', f'/api/diagnostics/config_entry/{entry_id}')
        return document['data']

    # Internals.

    def _headers(self) -> dict[str, str]:
        return {'Authorization': f'Bearer {self._access_token()}'}

    def _access_token(self) -> str:
        if self._token is None:
            raise HomeAssistantApiError('not signed in')
        return self._token

    async def _post_json(self, path: str, payload: Mapping[str, Any]) -> Any:
        async with self._session.post(f'{self._url}{path}',
                                      json=payload) as response:
            return await self._json(response)

    async def _connected(self) -> aiohttp.ClientWebSocketResponse:
        if self._websocket is not None and not self._websocket.closed:
            return self._websocket
        websocket = await self._session.ws_connect(
            f'{self._url}/api/websocket', max_msg_size=MAX_MESSAGE_SIZE)
        await websocket.receive_json()  # auth_required
        await websocket.send_json({'type': 'auth',
                                   'access_token': self._access_token()})
        answer = await websocket.receive_json()
        if answer.get('type') != 'auth_ok':
            await websocket.close()
            raise HomeAssistantApiError(f'websocket sign-in refused: {answer}')
        self._websocket = websocket
        return websocket

    @staticmethod
    async def _json(response: aiohttp.ClientResponse) -> Any:
        text = await response.text()
        if response.status >= 400:
            raise HomeAssistantApiError(
                f'{response.method} {response.url.path}: '
                f'HTTP {response.status} {text.strip()}')
        if not text:
            return None
        return await response.json(content_type=None)
