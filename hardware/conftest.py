"""A real 250W through a real Home Assistant, signed in with the CLI's login.

The session starts a Home Assistant container, installs this repository's
integration, adds the charger with the email and password the CLI keeps,
runs the tests and removes the entry and the container again. See the
readme's development section.
"""

import os
import shutil
import struct
import zlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import pytest
import pytest_asyncio

from ankerprime.cli.aliases import Connection
from ankerprime.cli.config import CliConfig, default_config_dir
from ankerprime.cloud.auth import AccountCredentials

from hardware.api import USER_NAME, USER_PASSWORD, HomeAssistantApi
from hardware.charger import ChargerUnderTest, Fingerprint, add_cloud_entry
from hardware.container import DockerError, HomeAssistantContainer


REPOSITORY = Path(__file__).parent.parent
INTEGRATION = REPOSITORY / 'custom_components' / 'anker_prime'
IMAGE_REPOSITORY = 'ghcr.io/home-assistant/home-assistant'
DEFAULT_TAG = 'stable'
DEFAULT_SETTLE = 5.0
DEFAULT_TIMEOUT = 300.0
LIBRARY_FOLDER = 'anker-prime-driver'
UNPINNED_REQUIREMENT = 'anker-prime-driver[ble,pictures]'
# Relative to the configuration folder, which Home Assistant allows.
PICTURE_FILE = 'www/anker-prime-hardware.png'
COPY_IGNORED = shutil.ignore_patterns(
    '.git', '.venv', 'venv', 'build', 'dist', '*.egg-info', '__pycache__',
    '.*_cache')
CONFIGURATION = '''\
homeassistant:
  name: Anker Prime hardware tests
  language: en
  country: US
  unit_system: metric
  time_zone: UTC
http:
  server_port: {port}
api:
config:
onboarding:
diagnostics:
logger:
  default: warning
  logs:
    custom_components.anker_prime: debug
    ankerprime: debug
'''
LOG_KEY = pytest.StashKey[Path]()


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup('hardware', 'tests on a real 250W in Home Assistant')
    group.addoption('--hardware-serial', metavar='SERIAL',
                    help="charger serial (default: the CLI's default cloud "
                         'charger, else the only one)')
    group.addoption('--hardware-settle', metavar='SECONDS', type=float,
                    default=DEFAULT_SETTLE,
                    help='seconds to wait for a read-back after a refresh '
                         f'(default {DEFAULT_SETTLE:g})')
    group.addoption('--hardware-tag', metavar='TAG',
                    help=f'tag of {IMAGE_REPOSITORY} (default {DEFAULT_TAG}; '
                         'e.g. 2026.10.4, beta)')
    group.addoption('--hardware-image', metavar='IMAGE',
                    help='another Home Assistant image, in place of the tag')
    group.addoption('--hardware-network', metavar='NETWORK',
                    help='Docker network of the container: a network name, '
                         'host, or container:NAME to share the network of '
                         "another container (default Docker's bridge)")
    group.addoption('--hardware-library', metavar='PATH', type=Path,
                    help='install this library working copy in Home '
                         'Assistant instead of the released version')
    group.addoption('--hardware-timeout', metavar='SECONDS', type=float,
                    default=DEFAULT_TIMEOUT,
                    help='seconds for Home Assistant to start and for the '
                         f'entry to load (default {DEFAULT_TIMEOUT:g})')
    group.addoption('--hardware-keep', action='store_true',
                    help='keep the container and the entry afterwards, for a '
                         'look at them (remove with docker rm --force '
                         '--volumes NAME)')


def pytest_configure(config: pytest.Config) -> None:
    _image(config)  # option errors before anything starts


def pytest_terminal_summary(terminalreporter: pytest.TerminalReporter,
                            config: pytest.Config) -> None:
    log = config.stash.get(LOG_KEY, None)
    if log is not None:
        terminalreporter.write_line(f'Home Assistant log: {log}')


@dataclass(init=False)
class CliLogin:
    """What the CLI keeps: the password login and the default charger."""

    _credentials: AccountCredentials
    _serial: str | None

    def __init__(self, credentials: AccountCredentials, serial: str | None):
        self._credentials = credentials
        self._serial = serial

    @property
    def credentials(self) -> AccountCredentials:
        return self._credentials

    @property
    def serial(self) -> str | None:
        return self._serial


@pytest_asyncio.fixture(scope='session', loop_scope='session')
async def cli_login(request: pytest.FixtureRequest) -> CliLogin:
    config = CliConfig(default_config_dir())
    credentials = await config.credentials()
    if credentials is None:
        pytest.exit('the CLI keeps no password: run "ankerprime login" with '
                    'email and password first (Home Assistant signs in '
                    'itself; mainland China SMS accounts are not supported '
                    'here)', 2)
    serial = request.config.getoption('hardware_serial')
    if serial is None:
        default = (await config.aliases()).default
        if default is not None and default.connection == Connection.CLOUD:
            serial = default.serial
    return CliLogin(credentials, serial)


@pytest_asyncio.fixture(scope='session', loop_scope='session')
async def home_assistant(request: pytest.FixtureRequest,
                         tmp_path_factory: pytest.TempPathFactory,
                         cli_login: CliLogin
                         ) -> AsyncIterator[HomeAssistantApi]:
    """A started, onboarded Home Assistant with the integration installed.

    The container is removed afterwards; its log is kept next to pytest's
    temporary files.
    """

    options = request.config
    library: Path | None = options.getoption('hardware_library')
    timeout: float = options.getoption('hardware_timeout')
    container = HomeAssistantContainer(
        _image(options), options.getoption('hardware_network'))
    stage = tmp_path_factory.mktemp('config')
    _stage_configuration(stage, library, container.http_port)
    try:
        await container.start(stage)
        if library is not None:
            await container.install_library(LIBRARY_FOLDER)
        async with HomeAssistantApi(container.url) as api:
            await api.wait_until_up(timeout, container.running)
            await api.onboard()
            yield api
    finally:
        shutil.rmtree(stage, ignore_errors=True)
        try:
            await _save_log(container, stage.parent / 'home-assistant.log',
                            options)
        finally:
            if options.getoption('hardware_keep') and container.started:
                print(f'\nkept {container.name} at {container.url} (user '
                      f'{USER_NAME}, password {USER_PASSWORD})')
            else:
                await container.remove()


@pytest_asyncio.fixture(scope='session', loop_scope='session')
async def charger(request: pytest.FixtureRequest,
                  home_assistant: HomeAssistantApi,
                  cli_login: CliLogin) -> AsyncIterator[ChargerUnderTest]:
    """The charger's entry, every entity enabled, updates unthrottled.

    The entry is removed afterwards, unless the container is kept.
    """

    timeout: float = request.config.getoption('hardware_timeout')
    entry_id, serial = await add_cloud_entry(
        home_assistant, cli_login.credentials, cli_login.serial)
    try:
        await home_assistant.wait_for_entry(entry_id, timeout)
        await home_assistant.set_options(entry_id, {'update_interval': 0})
        charger = ChargerUnderTest(
            home_assistant, entry_id, serial, timeout=timeout,
            settle=request.config.getoption('hardware_settle'))
        await home_assistant.wait_for_entry(entry_id, timeout)
        if await charger.discover(enable=True):
            await charger.reload()
        await charger.wait_available()
        yield charger
    finally:
        if not request.config.getoption('hardware_keep'):
            await home_assistant.remove_entry(entry_id)


@pytest_asyncio.fixture(scope='session', loop_scope='session')
async def baseline(charger: ChargerUnderTest) -> Fingerprint:
    """Everything the tests change, as found before the first one."""

    return (await charger.settled(account=True)).fingerprint()


async def _save_log(container: HomeAssistantContainer, log: Path,
                    config: pytest.Config) -> None:
    """Keep Home Assistant's output for the summary; best effort."""

    try:
        output = await container.logs()
    except DockerError as error:
        output = f'no log: {error}'
    if output:
        log.write_text(output)
        config.stash[LOG_KEY] = log


def _image(config: pytest.Config) -> str:
    image: str | None = config.getoption('hardware_image')
    tag: str | None = config.getoption('hardware_tag')
    if image is not None and tag is not None:
        raise pytest.UsageError(
            '--hardware-image and --hardware-tag exclude each other')
    return image or f'{IMAGE_REPOSITORY}:{tag or DEFAULT_TAG}'


def _stage_configuration(stage: Path, library: Path | None,
                         port: int) -> None:
    """The configuration folder copied into the container."""

    (stage / 'configuration.yaml').write_text(CONFIGURATION.format(port=port))
    target = stage / 'custom_components' / 'anker_prime'
    shutil.copytree(INTEGRATION, target, ignore=COPY_IGNORED)
    if library is not None:
        shutil.copytree(library, stage / LIBRARY_FOLDER, ignore=COPY_IGNORED)
        # Any installed version satisfies the requirement: Home Assistant
        # keeps the copy instead of installing the release.
        manifest = target / 'manifest.json'
        text = manifest.read_text()
        pinned = next(line.strip().strip('",') for line in text.splitlines()
                      if UNPINNED_REQUIREMENT in line)
        manifest.write_text(text.replace(pinned, UNPINNED_REQUIREMENT))
    picture = stage / PICTURE_FILE
    picture.parent.mkdir()
    picture.write_bytes(noise_png())


def noise_png(width: int = 640, height: int = 480) -> bytes:
    """A detailed picture, so the JPEG reaches the official size window."""

    rows = b''.join(b'\x00' + os.urandom(width * 3) for _ in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack('>I', len(data)) + kind + data
                + struct.pack('>I', zlib.crc32(kind + data)))

    header = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header)
            + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b''))
