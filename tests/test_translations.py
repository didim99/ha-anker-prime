"""Every translation matches the English one: same keys, same placeholders."""

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.translation import async_get_translations

from custom_components.anker_prime.const import DOMAIN


TRANSLATIONS = (Path(__file__).parent.parent / 'custom_components' / DOMAIN
                / 'translations')
PLACEHOLDER = re.compile(r'\{\w+\}')
LANGUAGES = sorted(path.stem for path in TRANSLATIONS.glob('*.json')
                   if path.stem != 'en')


def flatten(document: dict[str, Any], prefix: str = ''
            ) -> Iterator[tuple[str, str]]:
    for key, value in document.items():
        if isinstance(value, dict):
            yield from flatten(value, f'{prefix}{key}.')
        else:
            yield f'{prefix}{key}', value


def load(language: str) -> dict[str, str]:
    path = TRANSLATIONS / f'{language}.json'
    return dict(flatten(json.loads(path.read_text(encoding='utf-8'))))


def test_there_are_other_languages() -> None:
    assert 'ru' in LANGUAGES


@pytest.mark.parametrize('language', LANGUAGES)
def test_keys_and_placeholders_match_english(language: str) -> None:
    english = load('en')
    other = load(language)
    assert sorted(other) == sorted(english)
    for key, text in english.items():
        assert set(PLACEHOLDER.findall(other[key])) == set(
            PLACEHOLDER.findall(text)), key
        assert other[key].strip(), key


@pytest.mark.parametrize('language', LANGUAGES)
async def test_home_assistant_loads_the_translation(
        hass: HomeAssistant, language: str) -> None:
    strings = await async_get_translations(hass, language, 'entity',
                                           [DOMAIN])
    english = await async_get_translations(hass, 'en', 'entity', [DOMAIN])
    key = f'component.{DOMAIN}.entity.sensor.total_power.name'
    assert strings[key] != english[key]
