"""A throwaway Home Assistant container, driven with the ``docker`` command.

Nothing is mounted from the host: the staged configuration folder is copied
into the container's own ``/config`` volume, which goes with the container.
"""

import asyncio
import secrets
import socket
from dataclasses import dataclass
from pathlib import Path


CONFIG_DIRECTORY = '/config'
DEFAULT_HTTP_PORT = 8123
LOCALHOST = '127.0.0.1'
HOST_NETWORK = 'host'
CONTAINER_NETWORK = 'container:'
# Networks whose containers get no published ports: the host reaches them by
# their own address, or not at all.
UNPUBLISHED_DRIVERS = frozenset({'macvlan', 'ipvlan', 'none', 'null'})
NAME_PREFIX = 'anker-prime-hardware'
# Characters of the log shown when the container stops.
LOG_TAIL = 2000
# Extras the integration's requirement names.
LIBRARY_EXTRAS = '[ble,pictures]'
# Installs a library copy the way Home Assistant installs requirements:
# ``python3 -m uv`` within its pins, pip when the image has no uv.
INSTALL_SCRIPT = '''
set -e
constraints=$(python3 -c "import homeassistant, os; print(os.path.join(
    os.path.dirname(homeassistant.__file__), 'package_constraints.txt'))")
if python3 -m uv --version > /dev/null 2>&1; then
    python3 -m uv pip install --python "$(command -v python3)" --quiet \\
        --index-strategy unsafe-first-match --constraint "$constraints" "$1"
else
    python3 -m pip install --quiet --constraint "$constraints" "$1"
fi
'''


class DockerError(Exception):
    """A ``docker`` command failed."""


async def docker(*arguments: str) -> str:
    """Run ``docker`` with the arguments; its output, stderr included."""

    try:
        process = await asyncio.create_subprocess_exec(
            'docker', *arguments, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT)
    except FileNotFoundError:
        raise DockerError('the docker command is not installed') from None
    output, _ = await process.communicate()
    text = output.decode(errors='replace')
    if process.returncode:
        raise DockerError(f'docker {arguments[0]} failed '
                          f'({process.returncode}): {text.strip()}')
    return text


@dataclass(init=False)
class HomeAssistantContainer:
    """One Home Assistant container and how to reach it from the host.

    Without a network, Docker's default bridge with the port published on
    localhost. ``network`` is any ``docker create --network`` value:
    - a user-defined network: bridges publish on localhost too; on macvlan
      and ipvlan networks the container's own address is used;
    - ``host``: Home Assistant listens on a free localhost port;
    - ``container:NAME``: the other container's network (a VPN container,
      say), reached at that container's address.
    """

    _image: str
    _network: str | None
    _name: str
    _http_port: int
    _created: bool
    _url: str | None

    def __init__(self, image: str, network: str | None = None):
        self._image = image
        self._network = network
        self._name = f'{NAME_PREFIX}-{secrets.token_hex(4)}'
        self._http_port = (_free_port() if network == HOST_NETWORK
                           else DEFAULT_HTTP_PORT)
        self._created = False
        self._url = None

    @property
    def name(self) -> str:
        return self._name

    @property
    def http_port(self) -> int:
        """The port Home Assistant must listen on (``http: server_port``)."""

        return self._http_port

    @property
    def started(self) -> bool:
        return self._url is not None

    @property
    def url(self) -> str:
        """Base URL of Home Assistant; set once started."""

        if self._url is None:
            raise DockerError(f'{self._name} is not started')
        return self._url

    async def start(self, config: Path) -> None:
        """Create the container with ``config`` as ``/config``, then start it.

        The image is pulled when missing.
        """

        publish = await self._publishes()
        arguments = ['create', '--name', self._name]
        if self._network is not None:
            arguments += ['--network', self._network]
        if publish:
            arguments += ['--publish', f'{LOCALHOST}::{self._port_spec()}']
        await docker(*arguments, self._image)
        self._created = True
        await docker('cp', f'{config}/.', f'{self._name}:{CONFIG_DIRECTORY}')
        await docker('start', self._name)
        if not await self.running():
            raise DockerError(f'{self._name} stopped at once: '
                              f'{(await self.logs()).strip()[-LOG_TAIL:]}')
        if publish:
            published = await docker('port', self._name, self._port_spec())
            self._url = f'http://{published.split()[0]}'
        else:
            self._url = f'http://{await self._address()}:{self._http_port}'

    def _port_spec(self) -> str:
        return f'{self._http_port}/tcp'

    async def _publishes(self) -> bool:
        """Whether the network takes published ports."""

        network = self._network
        if network is None:
            return True
        if network == HOST_NETWORK or network.startswith(CONTAINER_NETWORK):
            return False
        driver = await docker('network', 'inspect', '--format',
                              '{{.Driver}}', network)
        return driver.strip() not in UNPUBLISHED_DRIVERS

    async def _address(self) -> str:
        """The host's way to Home Assistant without a published port."""

        network = self._network
        if network == HOST_NETWORK:
            return LOCALHOST
        owner = self._name
        if network is not None and network.startswith(CONTAINER_NETWORK):
            owner = network[len(CONTAINER_NETWORK):]
        addresses = (await docker(
            'inspect', '--format',
            '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}',
            owner)).split()
        # A container sharing the host's network has no address of its own.
        return addresses[0] if addresses else LOCALHOST

    async def running(self) -> bool:
        if not self._created:
            return False
        state = await docker('inspect', '--format', '{{.State.Running}}',
                             self._name)
        return state.strip() == 'true'

    async def install_library(self, relative: str) -> None:
        """Install the library copied to ``/config/<relative>``."""

        await docker('exec', self._name, 'sh', '-c', INSTALL_SCRIPT, 'install',
                     f'{CONFIG_DIRECTORY}/{relative}{LIBRARY_EXTRAS}')

    async def logs(self) -> str:
        """Everything Home Assistant printed; empty before creation."""

        if not self._created:
            return ''
        return await docker('logs', '--timestamps', self._name)

    async def remove(self) -> None:
        """Stop and remove the container with its volumes, if created."""

        if self._created:
            await docker('rm', '--force', '--volumes', self._name)
            self._created = False


def _free_port() -> int:
    """A localhost port free right now."""

    with socket.socket() as probe:
        probe.bind((LOCALHOST, 0))
        port: int = probe.getsockname()[1]
        return port
