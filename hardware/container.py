"""A throwaway Home Assistant container, driven with the ``docker`` command.

Nothing is mounted from the host: the staged configuration folder is copied
into the container's own ``/config`` volume, which goes with the container.
"""

import asyncio
import secrets
from dataclasses import dataclass
from pathlib import Path


CONFIG_DIRECTORY = '/config'
HTTP_PORT = '8123/tcp'
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
    """One Home Assistant container, its port published on localhost."""

    _image: str
    _name: str
    _created: bool
    _url: str | None

    def __init__(self, image: str):
        self._image = image
        self._name = f'{NAME_PREFIX}-{secrets.token_hex(4)}'
        self._created = False
        self._url = None

    @property
    def name(self) -> str:
        return self._name

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

        await docker('create', '--name', self._name,
                     '--publish', f'127.0.0.1::{HTTP_PORT}', self._image)
        self._created = True
        await docker('cp', f'{config}/.', f'{self._name}:{CONFIG_DIRECTORY}')
        await docker('start', self._name)
        if not await self.running():
            raise DockerError(f'{self._name} stopped at once: '
                              f'{(await self.logs()).strip()[-LOG_TAIL:]}')
        published = (await docker('port', self._name, HTTP_PORT)).split()
        self._url = f'http://{published[0]}'

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
