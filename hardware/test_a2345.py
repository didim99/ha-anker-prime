"""Every reversible change on a real 250W, made through Home Assistant.

Each test reads the current value, changes it with an entity or action,
checks that Home Assistant reports the charger's read-back, and restores
the original in ``finally``. The last test compares everything with the
state found before the first one. Values the charger cannot report back as
they were (a schedule slot never set) are skipped rather than changed.
Nothing irreversible runs: the energy reset stays disabled, and an own
picture is uploaded and deleted again without being shown.
"""

from datetime import datetime, timedelta

import pytest

from ankerprime.model import ClockPicture, OutputId, ScheduleSlot

from hardware.api import ServiceError
from hardware.charger import (
    OWN_PREFIX, ChargerUnderTest, Fingerprint, Snapshot,
    own_picture_ids, schedule_fields, weekday_names)
from hardware.conftest import PICTURE_FILE


pytestmark = pytest.mark.asyncio(loop_scope='session')

COUNTDOWN = '01:00:00'
PROFILE_NAME = 'HW test'
RENAMED_PROFILE = 'HW test 2'
BUILTIN_STYLES = ('style_1', 'style_2', 'style_3')
REDACTED = '**REDACTED**'


async def test_baseline_recorded(baseline: Fingerprint) -> None:
    """Records the starting state before any change."""

    assert baseline


# Setup.

async def test_entities_and_diagnostics(charger: ChargerUnderTest) -> None:
    snapshot = await charger.need('refresh', 'total_power')
    power = snapshot.state('total_power')
    assert power is not None and float(power) >= 0, f'total power {power}'
    assert snapshot.charger['available']
    diagnostics = await charger.api.diagnostics(charger.entry_id)
    data = diagnostics['entry']['data']
    for key in ('email', 'password', 'authentication', 'serials'):
        assert data[key] == REDACTED, f'{key} not redacted'
    assert diagnostics['entry']['options'] == {'update_interval': 0}


async def test_invalid_actions_are_refused(charger: ChargerUnderTest) -> None:
    """Checked by Home Assistant or the integration; nothing is sent."""

    snapshot = await charger.need('clock_picture')
    with pytest.raises(ServiceError, match='allows'):
        await charger.action('upload_clock_picture', 'clock_picture',
                             file='/etc/hostname')
    with pytest.raises(ServiceError, match='does not support'):
        await charger.action('delete_clock_picture', 'charging_mode',
                             picture_id=1)
    rules = charger.product.custom_mode
    assert rules is not None
    free = [number for number in rules.numbers
            if snapshot.profile(number) is None]
    if free and 'custom_profile' in charger.entities:
        with pytest.raises(ServiceError, match='no stored profile'):
            await charger.action('delete_custom_profile', 'custom_profile',
                                 number=free[0])


# Outputs.

async def test_output_switch(charger: ChargerUnderTest) -> None:
    snapshot = await charger.need('c1_output')
    output = charger.idle_output(snapshot)
    key = f'{output.value}_output'
    try:
        await charger.turn(key, False)
        await charger.expect(lambda s: s.state(key) == 'off'
                             and not s.output(output)['is_on'],
                             f'{output.value} off')
    finally:
        await charger.turn(key, True)
    await charger.expect(lambda s: s.state(key) == 'on'
                         and s.output(output)['is_on'],
                         f'{output.value} on again')


async def test_countdown(charger: ChargerUnderTest) -> None:
    snapshot = await charger.need('c1_output', 'c1_countdown_end')
    output = charger.idle_output(snapshot)
    key = f'{output.value}_output'
    sensor = f'{output.value}_countdown_end'
    try:
        await charger.action('start_countdown', key, duration=COUNTDOWN)
        await charger.expect(lambda s: s.state(sensor) not in (None,
                                                               'unknown')
                             and s.output(output)['countdown'] is not None,
                             f'a countdown on {output.value}')
    finally:
        await charger.action('cancel_countdown', key)
    await charger.expect(lambda s: s.state(sensor) == 'unknown'
                         and s.output(output)['countdown'] is None,
                         f'the countdown on {output.value} cancelled')


@pytest.mark.parametrize('slot', list(ScheduleSlot))
async def test_schedule(charger: ChargerUnderTest, slot: ScheduleSlot
                        ) -> None:
    snapshot = await charger.need('c1_output')
    output = charger.idle_output(snapshot)
    key = f'{output.value}_output'
    attribute = f'{slot.value}_schedule'
    original = snapshot.output(output)[attribute]
    if original is None:
        pytest.skip(f'{output.value} {slot.value} never set: the charger has '
                    'no "unset" value to restore')
    # Twelve hours away, on a single weekday three days ahead: it cannot
    # fire while the test runs.
    when = datetime.now() + timedelta(hours=12)
    day = weekday_names(1 << ((datetime.now().weekday() + 3) % 7))
    target = {'enabled': True, 'time': f'{when.hour:02d}:{when.minute:02d}',
              'weekdays': day}
    if target == snapshot.attributes(key)[attribute]:
        target['time'] = f'{when.hour:02d}:{(when.minute + 1) % 60:02d}'

    def reported(s: Snapshot) -> object:
        return s.attributes(key).get(attribute)

    try:
        await charger.action('set_schedule', key, slot=slot.value,
                             time=f'{target["time"]}:00',
                             weekdays=target['weekdays'], enabled=True)
        await charger.expect(lambda s: reported(s) == target,
                             f'the new {slot.value} schedule')
    finally:
        await charger.action('set_schedule', key, slot=slot.value,
                             **schedule_fields(original))
    await charger.expect(lambda s: s.output(output)[attribute] == original,
                         f'the original {slot.value} schedule')


# Charging mode and priority.

async def test_charging_mode(charger: ChargerUnderTest) -> None:
    snapshot = await charger.need('charging_mode')
    original = snapshot.state('charging_mode')
    if original in (None, 'unknown', 'custom'):
        pytest.skip('custom mode in use; covered by the custom mode test')
    modes = [mode for mode in snapshot.options('charging_mode')
             if mode not in (original, 'custom')]
    target = 'ai' if 'ai' in modes else modes[0]
    try:
        await charger.select('charging_mode', target)
        await charger.expect(lambda s: s.state('charging_mode') == target,
                             f'mode {target}')
    finally:
        await charger.select('charging_mode', original)
    await charger.expect(lambda s: s.state('charging_mode') == original,
                         f'mode {original} again')


async def test_preferred_output(charger: ChargerUnderTest) -> None:
    """Switching one on also selects port priority: both restored."""

    snapshot = await charger.need('charging_mode')
    mode = snapshot.state('charging_mode')
    if mode in (None, 'unknown', 'custom'):
        pytest.skip('custom mode in use; the mode could not be restored')
    keys = [f'{output.value}_preferred'
            for output in charger.product.priority_outputs]
    snapshot = await charger.need(*keys)
    original = {key: snapshot.state(key) == 'on' for key in keys}
    key = next((key for key in keys if not original[key]), keys[0])
    target = not original[key]
    try:
        await charger.turn(key, target)
        await charger.expect(lambda s: (s.state(key) == 'on') is target,
                             f'{key} {target}')
    finally:
        await charger.turn(key, original[key])
        state = await charger.settled()
        if state.state('charging_mode') != mode:
            await charger.select('charging_mode', mode)
    await charger.expect(lambda s: all((s.state(other) == 'on') is preferred
                                       for other, preferred
                                       in original.items())
                         and s.state('charging_mode') == mode,
                         'the original preferred outputs and mode')


# Display.

async def test_brightness(charger: ChargerUnderTest) -> None:
    snapshot = await charger.need('brightness')
    original = float(snapshot.state('brightness') or 'nan')
    attributes = snapshot.attributes('brightness')
    target = original + attributes['step']
    if target > attributes['max']:
        target = original - attributes['step']
    try:
        await charger.set_number('brightness', target)
        await charger.expect(
            lambda s: float(s.state('brightness') or 'nan') == target,
            f'brightness {target:g}')
    finally:
        await charger.set_number('brightness', original)
    await charger.expect(
        lambda s: float(s.state('brightness') or 'nan') == original,
        f'brightness {original:g} again')


@pytest.mark.parametrize('key', ['screen_timeout', 'knob_direction',
                                 'hour_format'])
async def test_display_select(charger: ChargerUnderTest, key: str) -> None:
    snapshot = await charger.need(key)
    original = snapshot.state(key)
    if original in (None, 'unknown'):
        pytest.skip(f'{key} not reported')
    target = next(option for option in snapshot.options(key)
                  if option != original)
    try:
        await charger.select(key, target)
        await charger.expect(lambda s: s.state(key) == target,
                             f'{key} {target}')
    finally:
        await charger.select(key, original)
    await charger.expect(lambda s: s.state(key) == original,
                         f'{key} {original} again')


# Clock.

async def test_clock_switch(charger: ChargerUnderTest) -> None:
    snapshot = await charger.need('clock')
    original = snapshot.clock
    assert original is not None
    try:
        await charger.turn('clock', not original['enabled'])
        await charger.expect(lambda s: s.clock is not None
                             and s.clock['enabled'] != original['enabled']
                             and (s.state('clock') == 'on')
                             is not original['enabled'],
                             'the clock switched')
    finally:
        await charger.restore_clock(original)
    await charger.expect(lambda s: s.clock == original, 'the original clock')


async def test_clock_theme(charger: ChargerUnderTest) -> None:
    snapshot = await charger.need('clock_theme')
    original = snapshot.clock
    assert original is not None
    target = next(style for style in BUILTIN_STYLES
                  if style != original['theme'])
    try:
        await charger.select('clock_theme', target)
        await charger.expect(lambda s: s.state('clock_theme') == target
                             and s.clock is not None
                             and s.clock['enabled'] == original['enabled'],
                             f'clock {target}, switched as before')
    finally:
        await charger.restore_clock(original)
    await charger.expect(lambda s: s.clock == original, 'the original clock')


async def test_clock_schedule(charger: ChargerUnderTest) -> None:
    snapshot = await charger.need('clock')
    original = snapshot.clock
    assert original is not None
    schedule = original['schedule']
    if schedule is None or not schedule['weekdays']:
        pytest.skip('clock schedule not reported')
    start_hour, start_minute = map(int, schedule['start'].split(':'))
    end_hour, end_minute = map(int, schedule['end'].split(':'))
    target = {'start': f'{(start_hour + 1) % 24:02d}:{start_minute:02d}',
              'end': f'{(end_hour + 1) % 24:02d}:{end_minute:02d}',
              'weekdays': weekday_names(schedule['weekdays'])}
    try:
        await charger.action('set_clock_schedule', 'clock',
                             start=f'{target["start"]}:00',
                             end=f'{target["end"]}:00',
                             weekdays=target['weekdays'])
        await charger.expect(
            lambda s: s.attributes('clock').get('schedule') == target,
            'the new clock schedule')
    finally:
        await charger.restore_clock(original)
    await charger.expect(lambda s: s.clock == original, 'the original clock')


async def test_holiday_theme(charger: ChargerUnderTest) -> None:
    snapshot = await charger.need('holiday_theme')
    original = snapshot.clock
    assert original is not None
    if not original['enabled'] or original['holiday_theme'] is None:
        pytest.skip('the clock is off: holiday themes are not reported')
    target = not original['holiday_theme']
    try:
        await charger.turn('holiday_theme', target)
        await charger.expect(
            lambda s: (s.state('holiday_theme') == 'on') is target,
            'holiday themes switched')
    finally:
        await charger.restore_clock(original)
    await charger.expect(lambda s: s.clock == original, 'the original clock')


async def test_catalogue_picture(charger: ChargerUnderTest) -> None:
    snapshot = await charger.need('clock_picture')
    original = snapshot.clock
    assert original is not None
    shown = (original['picture_id'] if original['theme'] == 'picture'
             else None)
    catalogue = [option for option in await charger.picture_options()
                 if not option.startswith(OWN_PREFIX)]
    assert catalogue, 'the catalogue is empty'
    target = next(option for option in catalogue
                  if shown is None or not option.endswith(f'({shown})'))
    try:
        await charger.select('clock_picture', target)
        await charger.expect(lambda s: s.state('clock_picture') == target
                             and s.clock is not None
                             and s.clock['theme'] == 'picture',
                             f'catalogue picture {target}')
    finally:
        await charger.restore_clock(original)
    await charger.expect(lambda s: s.clock == original, 'the original clock')


async def test_own_picture_upload_and_delete(charger: ChargerUnderTest
                                             ) -> None:
    """Uploads to the account and deletes again; never shown on the charger.

    The file is staged in the configuration folder's ``www``, which Home
    Assistant allows.
    """

    await charger.need('clock_picture')
    before = own_picture_ids(await charger.picture_options())
    if len(before) >= ClockPicture.OWN_LIMIT:
        pytest.skip('the account keeps the maximum of own pictures')
    added: set[int] = set()
    try:
        await charger.action('upload_clock_picture', 'clock_picture',
                             file=PICTURE_FILE)
        added = own_picture_ids(await charger.picture_options()) - before
        assert len(added) == 1, f'{len(added)} new own pictures'
    finally:
        for picture_id in added:
            await charger.action('delete_clock_picture', 'clock_picture',
                                 picture_id=picture_id)
    after = own_picture_ids(await charger.picture_options())
    assert after == before


async def test_picture_time(charger: ChargerUnderTest) -> None:
    snapshot = await charger.need('picture_time')
    original = snapshot.clock
    assert original is not None
    if original['picture_time'] is None:
        pytest.skip('the firmware does not report the time over pictures')
    target = not original['picture_time']
    try:
        await charger.turn('picture_time', target)
        await charger.expect(
            lambda s: (s.state('picture_time') == 'on') is target,
            'the time over own pictures switched')
    finally:
        await charger.restore_clock(original)
    await charger.expect(lambda s: s.clock == original, 'the original clock')


# Switches.

@pytest.mark.parametrize('key', ['max_compatibility',
                                 'device_identification'])
async def test_exclusive_switch(charger: ChargerUnderTest, key: str) -> None:
    snapshot = await charger.need(key)
    settings = snapshot.settings
    compatibility = settings['max_compatibility']
    identification = settings['device_identification']
    if compatibility is None or identification is None:
        pytest.skip('switches not reported')
    target = not settings[key]
    try:
        await charger.turn(key, target)
        await charger.expect(lambda s: (s.state(key) == 'on') is target,
                             f'{key} {target}', account=True)
    finally:
        await charger.restore_switches(compatibility, identification)
    await charger.expect(
        lambda s: s.settings['max_compatibility'] == compatibility
        and s.settings['device_identification'] == identification,
        'the original switches', account=True)


async def test_ufcs(charger: ChargerUnderTest) -> None:
    snapshot = await charger.need('ufcs')
    original = snapshot.settings['ufcs']
    if original is None:
        pytest.skip('UFCS not reported')
    try:
        await charger.turn('ufcs', not original)
        await charger.expect(lambda s: (s.state('ufcs') == 'on')
                             is not original, f'UFCS {not original}')
    finally:
        await charger.turn('ufcs', original)
    await charger.expect(lambda s: (s.state('ufcs') == 'on') is original,
                         f'UFCS {original} again')


# Custom mode.

async def test_labs_switch(charger: ChargerUnderTest) -> None:
    snapshot = await charger.need('custom_mode_setting')
    original = snapshot.settings['custom_mode_enabled']
    if original is None:
        pytest.skip('the account setting is not reported')
    if original and snapshot.settings['charging_mode'] == 'custom':
        pytest.skip('custom mode in use: switching Labs off would leave it')
    try:
        await charger.turn('custom_mode_setting', not original)
        await charger.expect(
            lambda s: (s.state('custom_mode_setting') == 'on')
            is not original, f'Labs {not original}', account=True)
    finally:
        await charger.turn('custom_mode_setting', original)
    await charger.expect(
        lambda s: s.settings['custom_mode_enabled'] is original,
        f'Labs {original} again', account=True)


async def test_profile_save_edit_delete(charger: ChargerUnderTest) -> None:
    """Stores a profile in a free slot, changes it, deletes it."""

    snapshot = await charger.need('custom_profile')
    rules = charger.product.custom_mode
    assert rules is not None
    free = [number for number in rules.numbers
            if snapshot.profile(number) is None]
    if not free:
        pytest.skip('every profile slot is in use')
    number = free[-1]
    template = rules.template(number, PROFILE_NAME)
    default = template.watts(OutputId.C1)
    watts = 60 if default != 60 else 45

    def c1(s: Snapshot) -> int | None:
        profile = s.profile(number)
        return None if profile is None else profile['ports']['c1']['watts']

    try:
        await charger.action('save_custom_profile', 'custom_profile',
                             number=number, name=PROFILE_NAME)
        await charger.expect(
            lambda s: f'{number}: {PROFILE_NAME}'
            in s.options('custom_profile') and c1(s) == default,
            f'profile {number} stored', account=True)
        await charger.action('save_custom_profile', 'custom_profile',
                             number=number, name=RENAMED_PROFILE, c1=watts)
        await charger.expect(
            lambda s: f'{number}: {RENAMED_PROFILE}'
            in s.options('custom_profile') and c1(s) == watts,
            f'profile {number} changed', account=True)
    finally:
        if (await charger.settled(account=True)).profile(number) is not None:
            await charger.action('delete_custom_profile', 'custom_profile',
                                 number=number)
    await charger.expect(lambda s: s.profile(number) is None
                         and not any(option.startswith(f'{number}: ')
                                     for option in s.options('custom_profile')),
                         f'profile {number} deleted', account=True)


async def test_custom_limits_and_exit(charger: ChargerUnderTest) -> None:
    """Applies the default limits unstored, then leaves custom mode."""

    snapshot = await charger.need('charging_mode')
    original = snapshot.state('charging_mode')
    if original in (None, 'unknown', 'custom'):
        pytest.skip('custom mode already in use')
    if snapshot.settings['custom_mode_enabled'] is False:
        pytest.skip("the account's Labs setting is off")
    try:
        await charger.action('set_custom_limits', 'charging_mode')
        # Not an option of the select: its state is unknown meanwhile.
        await charger.expect(
            lambda s: s.settings['charging_mode'] == 'custom'
            and s.state('charging_mode') == 'unknown', 'custom mode')
    finally:
        await charger.select('charging_mode', original)
    await charger.expect(lambda s: s.state('charging_mode') == original,
                         f'mode {original} again')


# Everything back.

async def test_state_restored(charger: ChargerUnderTest,
                              baseline: Fingerprint) -> None:
    """Runs last: every value the tests touched is as found."""

    now = (await charger.settled(account=True)).fingerprint()
    changed = {key: (baseline[key], value) for key, value in now.items()
               if key in baseline and baseline[key] != value}
    assert not changed, f'not restored (before, now): {changed}'
