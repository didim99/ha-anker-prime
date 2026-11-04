"""Config flow: Anker account sign-in, charger selection, reauth, options."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlowWithReload)
from homeassistant.const import CONF_COUNTRY, CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector, NumberSelectorConfig, NumberSelectorMode, SelectOptionDict,
    SelectSelector, SelectSelectorConfig, SelectSelectorMode, TextSelector,
    TextSelectorConfig, TextSelectorType)

from ankerprime.api.cloud import CLOUD_PRODUCTS, CloudAccount
from ankerprime.cloud.auth import AccountCredentials
from ankerprime.cloud.client import BoundDevice
from ankerprime.cloud.regions import REGIONS, UNSUPPORTED_REGIONS
from ankerprime.model import (
    AnkerPrimeError, AuthenticationError, InvalidParameterError)

from .account import async_login, credentials_from
from .const import (
    CONF_AUTHENTICATION, CONF_SERIALS, DEFAULT_UPDATE_INTERVAL, DOMAIN,
    MAX_UPDATE_INTERVAL, OPTION_UPDATE_INTERVAL)


logger = logging.getLogger(__name__)

# Home Assistant country codes that Anker spells differently.
COUNTRY_ALIASES = {'GB': 'UK', 'GR': 'EL'}


class AnkerPrimeConfigFlow(ConfigFlow, domain=DOMAIN):
    """One entry per Anker account; the account's user ID is its unique ID."""

    VERSION = 1

    _data: dict[str, Any]
    _chargers: list[BoundDevice]

    def __init__(self) -> None:
        self._data = {}
        self._chargers = []

    async def async_step_user(self, user_input: dict[str, Any] | None = None
                              ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            credentials = credentials_from(user_input)
            account, error = await self._async_sign_in(credentials)
            if account is not None:
                try:
                    await self.async_set_unique_id(account.user_id)
                    self._abort_if_unique_id_configured()
                    devices = await account.bound_devices()
                except AnkerPrimeError as failure:
                    logger.debug('device list failed: %s', failure)
                    errors['base'] = 'cannot_connect'
                else:
                    self._chargers = [
                        device for device in devices
                        if device.product_code.upper() in CLOUD_PRODUCTS]
                    if not self._chargers:
                        return self.async_abort(reason='no_chargers')
                    self._data = {
                        **_credential_data(credentials),
                        CONF_AUTHENTICATION:
                            account.authentication.to_document(),
                    }
                    return await self.async_step_chargers()
                finally:
                    await account.close()
            else:
                errors['base'] = error
        return self.async_show_form(
            step_id='user', errors=errors,
            data_schema=self.add_suggested_values_to_schema(
                _user_schema(), user_input or {
                    CONF_COUNTRY: _default_country(self.hass.config.country)}))

    async def async_step_chargers(self, user_input: dict[str, Any] | None = None
                                  ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            selected = user_input[CONF_SERIALS]
            if selected:
                return self.async_create_entry(
                    title=self._data[CONF_EMAIL],
                    data={**self._data, CONF_SERIALS: selected})
            errors['base'] = 'no_selection'
        options = [SelectOptionDict(value=device.serial,
                                    label=_charger_label(device))
                   for device in self._chargers]
        schema = vol.Schema({
            vol.Required(CONF_SERIALS,
                         default=[device.serial for device in self._chargers]):
                SelectSelector(SelectSelectorConfig(
                    options=options, multiple=True,
                    mode=SelectSelectorMode.LIST)),
        })
        return self.async_show_form(step_id='chargers', data_schema=schema,
                                    errors=errors)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]
                                ) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
            self, user_input: dict[str, Any] | None = None
            ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            credentials = AccountCredentials(entry.data[CONF_EMAIL],
                                             user_input[CONF_PASSWORD],
                                             entry.data[CONF_COUNTRY])
            account, error = await self._async_sign_in(credentials)
            if account is not None:
                await account.close()
                await self.async_set_unique_id(account.user_id)
                self._abort_if_unique_id_mismatch(reason='wrong_account')
                return self.async_update_reload_and_abort(
                    entry, data_updates={
                        CONF_PASSWORD: credentials.password,
                        CONF_AUTHENTICATION:
                            account.authentication.to_document(),
                    })
            errors['base'] = error
        return self.async_show_form(
            step_id='reauth_confirm', errors=errors,
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): _password()}),
            description_placeholders={'email': entry.data[CONF_EMAIL]})

    async def _async_sign_in(self, credentials: AccountCredentials
                             ) -> tuple[CloudAccount | None, str]:
        """The signed-in account, or None and an error key."""

        try:
            return await async_login(self.hass, credentials), ''
        except AuthenticationError:
            return None, 'invalid_auth'
        except InvalidParameterError:
            return None, 'invalid_input'
        except AnkerPrimeError as error:
            logger.debug('sign-in failed: %s', error)
            return None, 'cannot_connect'
        except Exception:
            logger.exception('unexpected sign-in error')
            return None, 'unknown'

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry
                               ) -> AnkerPrimeOptionsFlow:
        return AnkerPrimeOptionsFlow()


class AnkerPrimeOptionsFlow(OptionsFlowWithReload):
    """The minimum interval between entity updates."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None
                              ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data={
                OPTION_UPDATE_INTERVAL:
                    int(user_input[OPTION_UPDATE_INTERVAL])})
        current = self.config_entry.options.get(OPTION_UPDATE_INTERVAL,
                                                DEFAULT_UPDATE_INTERVAL)
        schema = vol.Schema({
            vol.Required(OPTION_UPDATE_INTERVAL, default=current):
                NumberSelector(NumberSelectorConfig(
                    min=0, max=MAX_UPDATE_INTERVAL, step=1,
                    unit_of_measurement='s', mode=NumberSelectorMode.BOX)),
        })
        return self.async_show_form(step_id='init', data_schema=schema)


def _user_schema() -> vol.Schema:
    regions = sorted(((code, name) for code, name in REGIONS.items()
                      if code not in UNSUPPORTED_REGIONS),
                     key=lambda item: item[1])
    return vol.Schema({
        vol.Required(CONF_EMAIL): TextSelector(
            TextSelectorConfig(type=TextSelectorType.EMAIL,
                               autocomplete='username')),
        vol.Required(CONF_PASSWORD): _password(),
        vol.Required(CONF_COUNTRY): SelectSelector(SelectSelectorConfig(
            options=[SelectOptionDict(value=code, label=f'{name} ({code})')
                     for code, name in regions],
            mode=SelectSelectorMode.DROPDOWN)),
    })


def _password() -> TextSelector:
    return TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD,
                                           autocomplete='current-password'))


def _credential_data(credentials: AccountCredentials) -> dict[str, str]:
    return {CONF_EMAIL: credentials.email, CONF_PASSWORD: credentials.password,
            CONF_COUNTRY: credentials.country}


def _charger_label(device: BoundDevice) -> str:
    return (f'{device.display_name} ({device.product_code}, '
            f'...{device.serial[-4:]})')


def _default_country(country: str | None) -> str | None:
    if country is None:
        return None
    code = COUNTRY_ALIASES.get(country.upper(), country.upper())
    if code in REGIONS and code not in UNSUPPORTED_REGIONS:
        return code
    return None
