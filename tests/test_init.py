"""Integration package checks: manifest, library and Home Assistant versions."""

import json
import re
from importlib.metadata import version
from pathlib import Path

from homeassistant.const import __version__ as HA_VERSION
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

import ankerprime
from custom_components.anker_prime.const import DOMAIN


ROOT = Path(__file__).parent.parent
WHEEL_PATTERN = re.compile(
    r'anker-prime-driver @ file:///config/wheels/'
    r'anker_prime_driver-(?P<version>[^-]+)-py3-none-any\.whl')


def test_versions_in_use() -> None:
    """Prints what the run is testing against (visible with -s or -v)."""

    print(f'Home Assistant {HA_VERSION}, anker-prime-driver '
          f'{ankerprime.__version__}')


async def test_manifest_loads(hass: HomeAssistant) -> None:
    integration = await async_get_integration(hass, DOMAIN)
    assert integration.domain == DOMAIN
    assert integration.version is not None
    assert integration.iot_class == 'cloud_push'


def test_manifest_requires_the_tested_library() -> None:
    """The wheel named in the manifest is the version these tests ran with."""

    manifest = json.loads(
        (ROOT / 'custom_components' / DOMAIN / 'manifest.json').read_text())
    matches = [WHEEL_PATTERN.fullmatch(requirement)
               for requirement in manifest['requirements']]
    versions = [match['version'] for match in matches if match]
    assert versions == [version('anker-prime-driver')]


def test_minimum_home_assistant_version() -> None:
    hacs = json.loads((ROOT / 'hacs.json').read_text())
    minimum = tuple(int(part) for part in hacs['homeassistant'].split('.'))
    current = tuple(int(part) for part in
                    re.findall(r'\d+', HA_VERSION)[:3])
    assert current >= minimum
