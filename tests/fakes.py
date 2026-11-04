"""A fake Anker cloud account and charger in place of the library's network."""

from __future__ import annotations

from collections.abc import Collection
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ankerprime.api.cloud import AuthenticationListener
from ankerprime.cloud.auth import AccountCredentials, Authentication
from ankerprime.cloud.client import BoundDevice
from ankerprime.cloud.regions import COM_SERVER
from ankerprime.device.base import BaseCharger
from ankerprime.interfaces.http import HttpClient
from ankerprime.interfaces.storage import DocumentStore
from ankerprime.model import (
    A2345, AuthenticationError, ChargerSettings, ChargerState, ChargingMode,
    ClockSchedule, ClockSettings, ClockTheme, Countdown, DeviceInfo,
    DisplaySettings, HourFormat, KnobDirection, OutputId, OutputState, PortId,
    PortReading, Schedule, ScheduleSlot, ScreenTimeout, Weekday)


SERIAL = 'AZVD4F12340868'
OTHER_SERIAL = 'AZVD4F99990001'
USER_ID = 'user-1'
EMAIL = 'second@example.com'
PASSWORD = 'secret'
COUNTRY = 'US'
NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


def make_authentication(user_id: str = USER_ID,
                        token: str = 'token-1') -> Authentication:
    return Authentication(user_id=user_id, auth_token=token,
                          expires_at=NOW + timedelta(days=30), country=COUNTRY,
                          server=COM_SERVER)


def make_device(serial: str = SERIAL, product_code: str = 'A2345',
                name: str = 'Desk charger') -> BoundDevice:
    return BoundDevice(serial, product_code, alias_name=name,
                       wifi_online=True, software_version='2.1.1.6')


def make_state(*, available: bool = True, serial: str = SERIAL,
               energy: dict[PortId, float] | None = None,
               countdown_c2: bool = False, firmware: str = '2.1.1.6',
               ufcs: bool | None = None) -> ChargerState:
    ports = {
        PortId.C1: PortReading(PortId.C1, status_code=1, voltage=20.0,
                               current=1.5, power=30.0),
        PortId.C2: PortReading(PortId.C2, status_code=0, voltage=0.0,
                               current=0.0, power=0.0),
    }
    on_schedule = Schedule(True, 7, 30, Weekday.MONDAY | Weekday.FRIDAY)
    outputs = {
        output: OutputState(
            output, is_on=output != OutputId.C3,
            countdown=(Countdown(900, 600, NOW)
                       if countdown_c2 and output == OutputId.C2 else None),
            power_on_schedule=on_schedule if output == OutputId.C1 else None,
            preferred=output == OutputId.C1 if output != OutputId.USB_A
            else None)
        for output in OutputId
    }
    settings = ChargerSettings(
        charging_mode=ChargingMode.AI, max_compatibility=False,
        device_identification=True, ufcs=ufcs,
        display=DisplaySettings(brightness=60,
                                screen_timeout=ScreenTimeout.FIVE_MINUTES,
                                knob_direction=KnobDirection.FORWARD,
                                hour_format=HourFormat.TWENTY_FOUR_HOUR),
        clock=ClockSettings(False, theme=ClockTheme.STYLE_2,
                            holiday_theme=False,
                            schedule=ClockSchedule(8, 0, 23, 0,
                                                   Weekday.EVERY_DAY)))
    if energy is None:
        energy = dict.fromkeys((spec.port for spec in A2345.ports), 0.0)
        energy[PortId.C1] = 12.5
    return ChargerState(A2345,
                        info=DeviceInfo(serial=serial, name='Desk charger',
                                        firmware_version=firmware),
                        available=available, ports=ports, outputs=outputs,
                        settings=settings, over_temperature=False,
                        error_code=0, energy=energy, updated_at=NOW)


class FakeCharger(BaseCharger):
    """Records commands; tests push states and set errors."""

    calls: list[tuple[str, tuple[Any, ...]]]
    fail_with: Exception | None
    connect_error: Exception | None
    connected: bool

    def __init__(self, state: ChargerState | None = None):
        super().__init__(A2345)
        self.calls = []
        self.fail_with = None
        self.connect_error = None
        self.connected = False
        if state is not None:
            self._state = state

    def push(self, state: ChargerState) -> None:
        self._publish(state)

    def set_last_error(self, error: Exception | None) -> None:
        self._last_error = error  # type: ignore[assignment]

    async def connect(self) -> None:
        if self.connect_error is not None:
            raise self.connect_error
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False

    async def refresh(self) -> None:
        self._record('refresh')

    async def reset_energy(self, ports: Collection[PortId] | None = None
                           ) -> None:
        self._record('reset_energy', ports)

    async def _set_output(self, output: OutputId, on: bool) -> None:
        self._record('set_output', output, on)

    async def _start_countdown(self, output: OutputId, seconds: int) -> None:
        self._record('start_countdown', output, seconds)

    async def _cancel_countdown(self, output: OutputId) -> None:
        self._record('cancel_countdown', output)

    async def _set_schedule(self, output: OutputId, slot: ScheduleSlot,
                            schedule: Schedule) -> None:
        self._record('set_schedule', output, slot, schedule)

    async def _set_charging_mode(self, mode: ChargingMode) -> None:
        self._record('set_charging_mode', mode)

    async def _set_preferred_outputs(self, outputs: Collection[OutputId]
                                     ) -> None:
        self._record('set_preferred_outputs', set(outputs))

    async def _set_brightness(self, percent: int) -> None:
        self._record('set_brightness', percent)

    async def _set_screen_timeout(self, timeout: ScreenTimeout) -> None:
        self._record('set_screen_timeout', timeout)

    async def _set_knob_direction(self, direction: KnobDirection) -> None:
        self._record('set_knob_direction', direction)

    async def _set_hour_format(self, hour_format: HourFormat) -> None:
        self._record('set_hour_format', hour_format)

    async def _set_clock(self, enabled: bool, theme: ClockTheme | None
                         ) -> None:
        self._record('set_clock', enabled, theme)

    async def _set_clock_schedule(self, schedule: ClockSchedule) -> None:
        self._record('set_clock_schedule', schedule)

    async def _set_holiday_theme(self, enabled: bool) -> None:
        self._record('set_holiday_theme', enabled)

    async def _set_max_compatibility(self, enabled: bool) -> None:
        self._record('set_max_compatibility', enabled)

    async def _set_device_identification(self, enabled: bool) -> None:
        self._record('set_device_identification', enabled)

    async def _set_ufcs(self, enabled: bool) -> None:
        self._record('set_ufcs', enabled)

    def _record(self, name: str, *args: Any) -> None:
        if self.fail_with is not None:
            raise self.fail_with
        self.calls.append((name, args))


class FakeCloud:
    """What the fake accounts see: devices, chargers, errors, logins."""

    devices: list[BoundDevice]
    chargers: dict[str, FakeCharger]
    login_error: Exception | None
    devices_error: Exception | None
    user_id: str
    logins: list[AccountCredentials]
    accounts: list[FakeCloudAccount]

    def __init__(self) -> None:
        self.devices = [make_device()]
        self.chargers = {SERIAL: FakeCharger(make_state())}
        self.login_error = None
        self.devices_error = None
        self.user_id = USER_ID
        self.logins = []
        self.accounts = []


class FakeCloudAccount:
    """Stands in for ``ankerprime.api.cloud.CloudAccount``."""

    cloud: FakeCloud

    authentication: Authentication
    credentials: AccountCredentials | None
    energy_store: DocumentStore | None
    on_authentication: AuthenticationListener | None
    closed: bool

    def __init__(self, http: HttpClient, authentication: Authentication, *,
                 credentials: AccountCredentials | None = None,
                 tls_directory: Path | None = None,
                 on_authentication: AuthenticationListener | None = None,
                 energy_store: DocumentStore | None = None, **_: Any):
        self.authentication = authentication
        self.credentials = credentials
        self.energy_store = energy_store
        self.on_authentication = on_authentication
        self.closed = False
        self.cloud.accounts.append(self)

    @property
    def user_id(self) -> str:
        return self.authentication.user_id

    async def bound_devices(self) -> list[BoundDevice]:
        if self.cloud.devices_error is not None:
            raise self.cloud.devices_error
        return list(self.cloud.devices)

    def charger(self, device: BoundDevice) -> FakeCharger:
        return self.cloud.chargers[device.serial]

    async def close(self) -> None:
        self.closed = True
        for charger in self.cloud.chargers.values():
            await charger.disconnect()

    @classmethod
    async def login(cls, http: HttpClient, credentials: AccountCredentials,
                    **kwargs: Any) -> FakeCloudAccount:
        cls.cloud.logins.append(credentials)
        if cls.cloud.login_error is not None:
            raise cls.cloud.login_error
        if credentials.password != PASSWORD:
            raise AuthenticationError('login failed (26108): wrong password')
        authentication = make_authentication(cls.cloud.user_id, 'token-new')
        return cls(http, authentication, credentials=credentials, **kwargs)
