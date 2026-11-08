"""250W clock pictures and the 160W's screen picture."""

import io
from pathlib import Path

import pytest
import voluptuous as vol
from homeassistant.components.select import ATTR_OPTION, SERVICE_SELECT_OPTION
from homeassistant.const import ATTR_ENTITY_ID, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er
from PIL import Image
from pytest_homeassistant_custom_component.common import MockConfigEntry

from ankerprime.model import (
    ChargerConnectionError, ChargerState,
    ClockSettings, ClockTheme, PictureTransferError)

from custom_components.anker_prime.const import DOMAIN
from tests.fakes import (
    FOREST, OWN_PICTURE, FakeBluetooth, FakeCharger,
    FakeCloud, make_ble_state, make_state)


PICTURE = 'select.desk_charger_clock_picture'
PICTURE_TIME = 'switch.desk_charger_time_over_own_pictures'
SCREEN = 'sensor.anker_prime_160w_1771_screen_picture'


async def call(hass: HomeAssistant, service: str, entity_id: str,
               **data: object) -> None:
    await hass.services.async_call(DOMAIN, service,
                                   {ATTR_ENTITY_ID: entity_id, **data},
                                   blocking=True)


@pytest.fixture
def image_file(hass: HomeAssistant, tmp_path: Path) -> Path:
    """A detailed image in an allowed folder."""

    hass.config.allowlist_external_dirs = {str(tmp_path)}
    path = tmp_path / 'picture.png'
    noise = Image.merge('RGB', [Image.effect_noise((640, 480), 60)
                                for _ in range(3)])
    noise.save(path, format='PNG')
    return path


def showing(theme: ClockTheme, picture_id: int) -> ChargerState:
    return make_state(clock=ClockSettings(True, theme=theme,
                                          holiday_theme=False,
                                          picture_id=picture_id,
                                          picture_time=True))


def option_of(hass: HomeAssistant, entity_id: str) -> str:
    state = hass.states.get(entity_id)
    assert state is not None
    return state.state


def image_size(jpeg: bytes) -> tuple[int, int]:
    with Image.open(io.BytesIO(jpeg)) as picture:
        return picture.size


async def test_clock_picture_select(hass: HomeAssistant,
                                    loaded: MockConfigEntry,
                                    charger: FakeCharger) -> None:
    select = hass.states.get(PICTURE)
    assert select is not None and select.state == STATE_UNKNOWN
    assert select.attributes['options'] == ['Forest (31)', 'Sea (32)',
                                            'Own 7']
    assert charger.picture_reads == ['en']
    await hass.services.async_call(
        'select', SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: PICTURE, ATTR_OPTION: 'Own 7'}, blocking=True)
    await hass.services.async_call(
        'select', SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: PICTURE, ATTR_OPTION: 'Forest (31)'}, blocking=True)
    assert charger.calls == [('apply_clock_picture', (OWN_PICTURE,)),
                             ('apply_clock_picture', (FOREST,))]
    charger.push(showing(ClockTheme.PICTURE, 31))
    await hass.async_block_till_done()
    assert option_of(hass, PICTURE) == 'Forest (31)'
    charger.push(showing(ClockTheme.CUSTOM, 7))
    await hass.async_block_till_done()
    assert option_of(hass, PICTURE) == 'Own 7'
    charger.push(showing(ClockTheme.CUSTOM, 31))  # not an own picture
    await hass.async_block_till_done()
    assert option_of(hass, PICTURE) == STATE_UNKNOWN
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            'select', SERVICE_SELECT_OPTION,
            {ATTR_ENTITY_ID: PICTURE, ATTR_OPTION: 'Gone (9)'},
            blocking=True)


async def test_failed_list_is_retried_later(
        hass: HomeAssistant, cloud: FakeCloud, entry: MockConfigEntry,
        charger: FakeCharger, monkeypatch: pytest.MonkeyPatch) -> None:
    charger.picture_error = ChargerConnectionError('offline')
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    select = hass.states.get(PICTURE)
    assert select is not None and select.attributes['options'] == []
    charger.picture_error = None
    charger.push(make_state())  # too soon: no new attempt
    await hass.async_block_till_done()
    assert len(charger.picture_reads) == 1
    monkeypatch.setattr(
        'custom_components.anker_prime.select.PICTURE_RETRY_SECONDS', 0.0)
    charger.push(make_state(firmware='2.1.1.7'))
    await hass.async_block_till_done()
    select = hass.states.get(PICTURE)
    assert select is not None and len(select.attributes['options']) == 3


async def test_upload_and_delete_own_pictures(
        hass: HomeAssistant, loaded: MockConfigEntry, charger: FakeCharger,
        image_file: Path) -> None:
    await call(hass, 'upload_clock_picture', PICTURE, file=str(image_file))
    name, (jpeg,) = charger.calls[-1]
    assert name == 'upload_clock_picture'
    assert image_size(jpeg) == (480, 200)
    select = hass.states.get(PICTURE)
    assert select is not None and 'Own 41' in select.attributes['options']

    await call(hass, 'delete_clock_picture', PICTURE, picture_id=7)
    assert charger.calls[-1] == ('delete_clock_picture', (7,))
    select = hass.states.get(PICTURE)
    assert select is not None and 'Own 7' not in select.attributes['options']


async def test_upload_needs_an_allowed_readable_image(
        hass: HomeAssistant, loaded: MockConfigEntry, charger: FakeCharger,
        image_file: Path, tmp_path: Path) -> None:
    hass.config.allowlist_external_dirs = set()
    with pytest.raises(ServiceValidationError, match='allows'):
        await call(hass, 'upload_clock_picture', PICTURE,
                   file=str(image_file))
    hass.config.allowlist_external_dirs = {str(tmp_path)}
    with pytest.raises(ServiceValidationError, match='cannot read'):
        await call(hass, 'upload_clock_picture', PICTURE,
                   file=str(tmp_path / 'missing.png'))
    (tmp_path / 'text.png').write_text('not an image')
    with pytest.raises(ServiceValidationError):
        await call(hass, 'upload_clock_picture', PICTURE,
                   file=str(tmp_path / 'text.png'))
    assert charger.calls == []


async def test_picture_actions_need_the_picture_select(
        hass: HomeAssistant, loaded: MockConfigEntry,
        charger: FakeCharger) -> None:
    with pytest.raises(ServiceValidationError, match='does not support'):
        await call(hass, 'delete_clock_picture',
                   'select.desk_charger_clock_theme', picture_id=7)
    assert charger.calls == []


async def test_picture_time_switch_is_experimental(
        hass: HomeAssistant, loaded: MockConfigEntry) -> None:
    entry = er.async_get(hass).async_get(PICTURE_TIME)
    assert entry is not None and entry.disabled
    picture = er.async_get(hass).async_get(PICTURE)
    assert picture is not None and not picture.disabled


async def enable_screen_picture(hass: HomeAssistant,
                                ble_entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_setup(ble_entry.entry_id)
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    entry = registry.async_get(SCREEN)
    assert entry is not None and entry.disabled
    registry.async_update_entity(SCREEN, disabled_by=None)
    await hass.config_entries.async_reload(ble_entry.entry_id)
    await hass.async_block_till_done()


async def test_screen_picture_upload_and_select(
        hass: HomeAssistant, bluetooth: FakeBluetooth,
        ble_entry: MockConfigEntry, image_file: Path) -> None:
    charger = bluetooth.charger
    charger.push(make_ble_state(screen_picture=0x0001))
    await enable_screen_picture(hass, ble_entry)
    state = hass.states.get(SCREEN)
    assert state is not None and state.state == '1'

    response = await hass.services.async_call(
        DOMAIN, 'upload_screen_picture',
        {ATTR_ENTITY_ID: SCREEN, 'file': str(image_file),
         'acknowledge_irreversible': True},
        blocking=True, return_response=True)
    assert response == {SCREEN: {'picture_id': 0x1_2345,
                                 'crc32': '1a2b3c4d', 'witnessed': True}}
    name, (jpeg, acknowledged) = charger.calls[-1]
    assert name == 'upload_screen_picture' and acknowledged
    assert image_size(jpeg) == (240, 240)
    state = hass.states.get(SCREEN)
    assert state is not None
    assert state.attributes['last_upload_crc32'] == '1a2b3c4d'

    await call(hass, 'select_screen_picture', SCREEN, picture_id=0x1_2345,
               crc32='0x1A2B3C4D')
    assert charger.calls[-1] == ('select_screen_picture',
                                 (0x1_2345, 0x1A2B3C4D))


async def test_screen_picture_needs_the_acknowledgement(
        hass: HomeAssistant, bluetooth: FakeBluetooth,
        ble_entry: MockConfigEntry, image_file: Path) -> None:
    await enable_screen_picture(hass, ble_entry)
    for data in ({'file': str(image_file)},
                 {'file': str(image_file), 'acknowledge_irreversible': False}):
        with pytest.raises(vol.Invalid):
            await hass.services.async_call(
                DOMAIN, 'upload_screen_picture',
                {ATTR_ENTITY_ID: SCREEN, **data},
                blocking=True, return_response=True)
    with pytest.raises(vol.Invalid):
        await call(hass, 'select_screen_picture', SCREEN, picture_id=1,
                   crc32='xyz')
    assert bluetooth.charger.calls == []


async def test_failed_screen_upload_says_what_is_on_the_charger(
        hass: HomeAssistant, bluetooth: FakeBluetooth,
        ble_entry: MockConfigEntry, image_file: Path) -> None:
    await enable_screen_picture(hass, ble_entry)
    bluetooth.charger.fail_with = PictureTransferError(
        'slice 12 not acknowledged', pixels_written=True)
    with pytest.raises(HomeAssistantError, match='on the charger now'):
        await hass.services.async_call(
            DOMAIN, 'upload_screen_picture',
            {ATTR_ENTITY_ID: SCREEN, 'file': str(image_file),
             'acknowledge_irreversible': True},
            blocking=True, return_response=True)

