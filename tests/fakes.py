"""A fake Anker cloud account and charger in place of the library's network."""

from __future__ import annotations

from collections.abc import Collection
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ankerprime.api.cloud import AccountOptions, AuthenticationListener
from ankerprime.cloud.auth import AccountCredentials, Authentication
from ankerprime.cloud.client import BoundDevice
from ankerprime.cloud.regions import COM_SERVER
from ankerprime.device.base import BaseCharger
from ankerprime.interfaces.http import HttpClient
from ankerprime.interfaces.storage import DocumentStore
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak

from ankerprime.model import (
    A2345, A2687, AuthenticationError, ChargerSettings, ChargerState,
    ChargingMode, ChargingProfile, ClockPicture, ClockSchedule, ClockSettings,
    ClockTheme, Countdown, DeviceInfo, DisplayLanguage, DisplaySettings,
    FixedAllocation, HourFormat, InvalidParameterError, KnobDirection,
    OutputId, OutputState, PortId, PortReading, Product, Schedule, ScheduleSlot,
    ScreenOrientation, ScreenPictureUpload, ScreenTimeout, Weekday)


SERIAL = 'AZVD4F12340868'
OTHER_SERIAL = 'AZVD4F99990001'
USER_ID = 'user-1'
EMAIL = 'second@example.com'
PASSWORD = 'secret'
COUNTRY = 'US'
NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)

PHONE = '13800138000'
SMS_CODE = '123456'
FOREST = ClockPicture(31, 'https://cdn/forest.jpg', 0x1A2B3C4D,
                      title='Forest')
SEA = ClockPicture(32, 'https://cdn/sea.jpg', 0xBEEF, title='Sea')
OWN_PICTURE = ClockPicture(7, 'https://own/7.jpg', 0x77, own=True)

BLE_ADDRESS = 'AA:BB:CC:DD:EE:01'
BLE_SERIAL = 'ASHDK7U1F51501771'
BLE_NAME = 'ASHDJW1771'


def make_authentication(user_id: str = USER_ID,
                        token: str = 'token-1') -> Authentication:
    return Authentication(user_id=user_id, auth_token=token,
                          expires_at=NOW + timedelta(days=30), country=COUNTRY,
                          server=COM_SERVER)


def make_device(serial: str = SERIAL, product_code: str = 'A2345',
                name: str = 'Desk charger') -> BoundDevice:
    return BoundDevice(serial, product_code, alias_name=name,
                       wifi_online=True, software_version='2.1.1.6')


def make_profile(number: int = 1, name: str = 'Desk') -> ChargingProfile:
    rules = A2345.custom_mode
    assert rules is not None
    return rules.template(number, name)


def make_state(*, available: bool = True, serial: str = SERIAL,
               energy: dict[PortId, float] | None = None,
               countdown_c2: bool = False, firmware: str = '2.1.1.6',
               ufcs: bool | None = None,
               custom_profile: int | None = None,
               clock: ClockSettings | None = None) -> ChargerState:
    """A 250W; ``custom_profile`` puts it in custom mode with that profile."""
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
        charging_mode=(ChargingMode.AI if custom_profile is None
                       else ChargingMode.CUSTOM),
        max_compatibility=False, device_identification=True, ufcs=ufcs,
        custom_mode_enabled=True, active_profile=custom_profile,
        custom_profiles=(make_profile(1, 'Desk'), make_profile(3, 'Travel')),
        display=DisplaySettings(brightness=60,
                                screen_timeout=ScreenTimeout.FIVE_MINUTES,
                                knob_direction=KnobDirection.FORWARD,
                                hour_format=HourFormat.TWENTY_FOUR_HOUR),
        clock=clock or ClockSettings(
            False, theme=ClockTheme.STYLE_2, holiday_theme=False,
            schedule=ClockSchedule(8, 0, 23, 0, Weekday.EVERY_DAY)))
    if energy is None:
        energy = dict.fromkeys((spec.port for spec in A2345.ports), 0.0)
        energy[PortId.C1] = 12.5
    return ChargerState(A2345,
                        info=DeviceInfo(serial=serial, name='Desk charger',
                                        firmware_version=firmware),
                        available=available, ports=ports, outputs=outputs,
                        settings=settings, over_temperature=False,
                        error_code=0, energy=energy, updated_at=NOW)


def make_ble_state(*, available: bool = True,
                   serial: str | None = BLE_SERIAL,
                   screen_picture: int | None = None) -> ChargerState:
    ports = {port: PortReading(port, status_code=1, voltage=20.0,
                               current=1.0 if port == PortId.C1 else 0.0,
                               power=20.0 if port == PortId.C1 else 0.0)
             for port in (PortId.C1, PortId.C2, PortId.C3)}
    outputs = {output: OutputState(output, is_on=True)
               for output in (OutputId.C1, OutputId.C2, OutputId.C3)}
    settings = ChargerSettings(
        charging_mode=ChargingMode.AI,
        display=DisplaySettings(brightness=80,
                                screen_timeout=ScreenTimeout.ONE_MINUTE,
                                orientation=ScreenOrientation.UP,
                                auto_rotation=False,
                                screen_picture=screen_picture))
    return ChargerState(A2687,
                        info=DeviceInfo(serial=serial,
                                        firmware_version='v0.0.5.2'),
                        available=available, ports=ports, outputs=outputs,
                        settings=settings, updated_at=NOW)


def make_service_info(address: str = BLE_ADDRESS,
                      name: str = BLE_NAME) -> BluetoothServiceInfoBleak:
    advertisement = AdvertisementData(
        local_name=name, manufacturer_data={}, service_data={},
        service_uuids=[], tx_power=None, rssi=-60, platform_data=())
    return BluetoothServiceInfoBleak(
        name=name, address=address, rssi=-60, manufacturer_data={},
        service_data={}, service_uuids=[], source='local',
        device=BLEDevice(address, name, None), advertisement=advertisement,
        connectable=True, time=0, tx_power=None)


class FakeCharger(BaseCharger):
    """Records commands; tests push states and set errors."""

    calls: list[tuple[str, tuple[Any, ...]]]
    fail_with: Exception | None
    connect_error: Exception | None
    connected: bool
    catalogue: list[ClockPicture]
    own_pictures: list[ClockPicture]
    picture_reads: list[str]
    picture_error: Exception | None

    def __init__(self, state: ChargerState | None = None,
                 product: Product = A2345):
        super().__init__(product)
        self.calls = []
        self.fail_with = None
        self.connect_error = None
        self.connected = False
        self.catalogue = [FOREST, SEA]
        self.own_pictures = [OWN_PICTURE]
        self.picture_reads = []
        self.picture_error = None
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

    async def _set_fixed_allocation(self, allocation: FixedAllocation
                                    ) -> None:
        self._record('set_fixed_allocation', allocation)

    async def _set_screen_orientation(self, orientation: ScreenOrientation
                                      ) -> None:
        self._record('set_screen_orientation', orientation)

    async def _set_auto_rotation(self, enabled: bool) -> None:
        self._record('set_auto_rotation', enabled)

    async def _set_display_language(self, language: DisplayLanguage) -> None:
        self._record('set_display_language', language)

    async def _apply_custom_profile(self, profile: ChargingProfile) -> None:
        self._record('apply_custom_profile', profile)

    async def _exit_custom_mode(self) -> None:
        self._record('exit_custom_mode')

    async def _set_custom_mode_enabled(self, enabled: bool) -> None:
        self._record('set_custom_mode_enabled', enabled)

    async def _save_custom_profile(self, profile: ChargingProfile) -> None:
        self._record('save_custom_profile', profile)

    async def _delete_custom_profile(self, number: int) -> None:
        self._record('delete_custom_profile', number)

    async def _reload_custom_profiles(self) -> None:
        self._record('reload_custom_profiles')

    async def _clock_pictures(self, language: str
                              ) -> tuple[ClockPicture, ...]:
        # Reads, not commands: kept out of ``calls``.
        self.picture_reads.append(language)
        if self.picture_error is not None:
            raise self.picture_error
        return tuple(self.catalogue)

    async def _own_clock_pictures(self) -> tuple[ClockPicture, ...]:
        return tuple(self.own_pictures)

    async def _apply_clock_picture(self, picture: ClockPicture) -> None:
        self._record('apply_clock_picture', picture)

    async def _upload_clock_picture(self, jpeg: bytes) -> None:
        self._record('upload_clock_picture', jpeg)
        self.own_pictures.append(ClockPicture(
            40 + len(self.own_pictures), 'https://own/new.jpg', 1, own=True))

    async def _delete_clock_picture(self, picture_id: int) -> None:
        self._record('delete_clock_picture', picture_id)
        self.own_pictures[:] = [picture for picture in self.own_pictures
                                if picture.picture_id != picture_id]

    async def _set_picture_time(self, enabled: bool) -> None:
        self._record('set_picture_time', enabled)

    async def _upload_screen_picture(self, jpeg: bytes,
                                     acknowledge_irreversible: bool
                                     ) -> ScreenPictureUpload:
        self._record('upload_screen_picture', jpeg, acknowledge_irreversible)
        return ScreenPictureUpload(0x1_2345, 0x1A2B3C4D,
                                   byte_count=len(jpeg), chunk_count=1,
                                   previous=0x0001, witnessed=True)

    async def _select_screen_picture(self, picture_id: int, crc32: int
                                     ) -> None:
        self._record('select_screen_picture', picture_id, crc32)

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
    sms_sent: list[str]
    sms_error: Exception | None

    def __init__(self) -> None:
        self.devices = [make_device()]
        self.chargers = {SERIAL: FakeCharger(make_state())}
        self.login_error = None
        self.devices_error = None
        self.user_id = USER_ID
        self.logins = []
        self.accounts = []
        self.sms_sent = []
        self.sms_error = None


class FakeCloudAccount:
    """Stands in for ``ankerprime.api.cloud.CloudAccount``."""

    cloud: FakeCloud

    authentication: Authentication
    credentials: AccountCredentials | None
    tls_directory: Path | None
    energy_store: DocumentStore | None
    on_authentication: AuthenticationListener | None
    closed: bool

    def __init__(self, http: HttpClient, authentication: Authentication, *,
                 credentials: AccountCredentials | None = None,
                 options: AccountOptions | None = None):
        options = options or AccountOptions()
        self.authentication = authentication
        self.credentials = credentials
        self.tls_directory = options.tls_directory
        self.energy_store = options.energy_store
        self.on_authentication = options.on_authentication
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
                    *, options: AccountOptions | None = None
                    ) -> FakeCloudAccount:
        cls.cloud.logins.append(credentials)
        if cls.cloud.login_error is not None:
            raise cls.cloud.login_error
        if credentials.password != PASSWORD:
            raise AuthenticationError('login failed (26108): wrong password')
        authentication = make_authentication(cls.cloud.user_id, 'token-new')
        return cls(http, authentication, credentials=credentials,
                   options=options)

    @classmethod
    async def login_phone(cls, http: HttpClient, phone: str, code: str, *,
                          options: AccountOptions | None = None
                          ) -> FakeCloudAccount:
        if cls.cloud.login_error is not None:
            raise cls.cloud.login_error
        if code != SMS_CODE:
            raise AuthenticationError('phone login refused (26035)')
        authentication = make_authentication(cls.cloud.user_id, 'token-sms')
        return cls(http, authentication, options=options)


class FakeAccountClient:
    """Stands in for ``ankerprime.cloud.auth.AccountClient`` (SMS codes)."""

    cloud: FakeCloud

    def __init__(self, http: HttpClient, clock: Any = None):
        pass

    async def request_phone_code(self, phone: str) -> None:
        if len(phone) != 11 or not phone.startswith('1'):
            raise InvalidParameterError('a mainland China mobile number has '
                                        '11 digits and starts with 1')
        if self.cloud.sms_error is not None:
            raise self.cloud.sms_error
        self.cloud.sms_sent.append(phone)


class FakeBluetooth:
    """Home Assistant's Bluetooth stack and the library's factory, faked.

    Every ``ble_charger`` call returns the same charger and is recorded.
    """

    charger: FakeCharger
    in_range: bool
    discovered: list[BluetoothServiceInfoBleak]
    factory_calls: list[dict[str, Any]]

    def __init__(self) -> None:
        self.charger = FakeCharger(make_ble_state(), A2687)
        self.in_range = True
        self.discovered = [make_service_info()]
        self.factory_calls = []

    def ble_device(self, hass: Any, address: str,
                   connectable: bool = True) -> BLEDevice | None:
        if not self.in_range:
            return None
        return BLEDevice(address, BLE_NAME, None)

    def discovered_service_info(self, hass: Any, connectable: bool = True
                                ) -> list[BluetoothServiceInfoBleak]:
        return list(self.discovered)

    def ble_charger(self, device: BLEDevice, **kwargs: Any) -> FakeCharger:
        self.factory_calls.append({'device': device, **kwargs})
        return self.charger
