"""Diagnostics with secrets redacted."""

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from tests.fakes import EMAIL, PASSWORD, SERIAL


async def test_diagnostics_are_redacted(hass: HomeAssistant,
                                        hass_client: ClientSessionGenerator,
                                        loaded: MockConfigEntry) -> None:
    result = await get_diagnostics_for_config_entry(hass, hass_client, loaded)
    text = str(result)
    for secret in (EMAIL, PASSWORD, SERIAL, 'token-1'):
        assert secret not in text
    assert result['entry']['data']['email'] == '**REDACTED**'
    charger = result['chargers'][0]
    assert charger['product_code'] == 'A2345'
    assert charger['state']['ports']['c1']['power'] == 30.0
    assert charger['state']['info']['serial'] == '**REDACTED**'
