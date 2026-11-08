"""Config flow: cloud accounts and Bluetooth chargers, reauth, options.

Cloud: Anker account sign-in and charger selection; one entry per account.
Mainland China accounts sign in with a phone number and an SMS code; their
token cannot be renewed without a new code, so reauth asks for one.
Bluetooth: a discovered or picked 160W, confirmed by connecting once (which
also reads its serial); one entry per charger, unique by address.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak, async_discovered_service_info)
from homeassistant.config_entries import (
    ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlowWithReload)
from homeassistant.const import (
    CONF_ADDRESS, CONF_COUNTRY, CONF_EMAIL, CONF_PASSWORD)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector, NumberSelector, NumberSelectorConfig,
    NumberSelectorMode, SelectOptionDict, SelectSelector,
    SelectSelectorConfig, SelectSelectorMode, TextSelector,
    TextSelectorConfig, TextSelectorType)

from ankerprime.api.ble import advertisement_match, new_client_id
from ankerprime.api.cloud import CLOUD_PRODUCTS, CloudAccount
from ankerprime.cloud.auth import AccountCredentials
from ankerprime.cloud.client import BoundDevice
from ankerprime.cloud.regions import REGIONS, PHONE_REGIONS
from ankerprime.model import (
    AccountRefusedError, AnkerPrimeError, AuthenticationError,
    InvalidParameterError)

from .account import (
    async_login, async_login_phone, async_request_phone_code, credentials_from)
from .ble import create_charger
from .const import (
    BLUETOOTH_NAME, CONF_AUTHENTICATION, CONF_CLIENT_ID, CONF_CONNECTION,
    CONF_OWNER_ID, CONF_PHONE, CONF_SERIAL, CONF_SERIALS,
    CONNECTION_BLUETOOTH, DEFAULT_COUNTRY, DEFAULT_KEEP_CONNECTION,
    DEFAULT_READ_INTERVAL, DEFAULT_UPDATE_INTERVAL, DOMAIN,
    MAINLAND_COUNTRY, MAX_READ_INTERVAL, MAX_UPDATE_INTERVAL,
    MIN_READ_INTERVAL, OPTION_KEEP_CONNECTION, OPTION_READ_INTERVAL,
    OPTION_UPDATE_INTERVAL, is_bluetooth, is_phone_account)


logger = logging.getLogger(__name__)

# Home Assistant country codes that Anker spells differently.
COUNTRY_ALIASES = {'GB': 'UK', 'GR': 'EL'}
CONF_CODE = 'code'


class AnkerPrimeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Unique IDs: the Anker user ID (cloud), the address (Bluetooth)."""

    VERSION = 1

    _data: dict[str, Any]
    _title: str
    _chargers: list[BoundDevice]
    _address: str | None
    _client_id: str
    _phone: str | None

    def __init__(self) -> None:
        self._data = {}
        self._title = ''
        self._chargers = []
        self._address = None
        self._client_id = new_client_id()
        self._phone = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None
                              ) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id='user',
            menu_options=['cloud', 'cloud_phone', 'bluetooth_pick'])

    async def async_step_cloud(self, user_input: dict[str, Any] | None = None
                               ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            credentials = credentials_from(user_input)
            account, error = await self._async_sign_in(credentials)
            if account is None:
                errors['base'] = error
            elif result := await self._async_account_found(
                    account, _credential_data(credentials),
                    credentials.email):
                return result
            else:
                errors['base'] = 'cannot_connect'
        return self.async_show_form(
            step_id='cloud', errors=errors,
            data_schema=self.add_suggested_values_to_schema(
                _user_schema(), user_input or {
                    CONF_COUNTRY: _default_country(self.hass.config.country)}))

    async def async_step_cloud_phone(
            self, user_input: dict[str, Any] | None = None
            ) -> ConfigFlowResult:
        """Mainland China: the account's phone number; an SMS code follows."""

        errors: dict[str, str] = {}
        if user_input is not None:
            phone = str(user_input[CONF_PHONE]).strip()
            error = await self._async_send_code(phone)
            if not error:
                self._phone = phone
                return await self.async_step_phone_code()
            errors['base'] = error
        return self.async_show_form(
            step_id='cloud_phone', errors=errors,
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema({vol.Required(CONF_PHONE): _phone_selector()}),
                user_input or {}))

    async def async_step_phone_code(
            self, user_input: dict[str, Any] | None = None
            ) -> ConfigFlowResult:
        assert self._phone is not None
        errors: dict[str, str] = {}
        if user_input is not None:
            account, error = await self._async_sign_in_phone(
                self._phone, user_input[CONF_CODE])
            data = {CONF_PHONE: self._phone, CONF_COUNTRY: MAINLAND_COUNTRY}
            if account is None:
                errors['base'] = error
            elif result := await self._async_account_found(account, data,
                                                           self._phone):
                return result
            else:
                errors['base'] = 'cannot_connect'
        return self.async_show_form(
            step_id='phone_code', errors=errors, data_schema=_code_schema(),
            description_placeholders={'phone': self._phone})

    async def async_step_chargers(self, user_input: dict[str, Any] | None = None
                                  ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            selected = user_input[CONF_SERIALS]
            if selected:
                return self.async_create_entry(
                    title=self._title,
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

    async def async_step_bluetooth(
            self, discovery_info: BluetoothServiceInfoBleak
            ) -> ConfigFlowResult:
        address = discovery_info.address.upper()
        await self.async_set_unique_id(address)
        self._abort_if_unique_id_configured()
        self._address = address
        self.context['title_placeholders'] = {
            'name': discovery_info.name or BLUETOOTH_NAME}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_pick(
            self, user_input: dict[str, Any] | None = None
            ) -> ConfigFlowResult:
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            self._address = address
            return await self.async_step_bluetooth_confirm()
        configured = self._async_current_ids(include_ignore=False)
        found: dict[str, str] = {}
        for info in async_discovered_service_info(self.hass, connectable=True):
            address = info.address.upper()
            if address in configured or address in found:
                continue
            if advertisement_match(info.name, info.service_uuids,
                                   info.service_data, info.manufacturer_data):
                found[address] = f'{info.name} ({address})'
        if not found:
            return self.async_abort(reason='no_devices_found')
        schema = vol.Schema({vol.Required(CONF_ADDRESS): SelectSelector(
            SelectSelectorConfig(
                options=[SelectOptionDict(value=address, label=label)
                         for address, label in found.items()],
                mode=SelectSelectorMode.LIST))})
        return self.async_show_form(step_id='bluetooth_pick',
                                    data_schema=schema)

    async def async_step_bluetooth_confirm(
            self, user_input: dict[str, Any] | None = None
            ) -> ConfigFlowResult:
        assert self._address is not None
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {CONF_CONNECTION: CONNECTION_BLUETOOTH,
                    CONF_ADDRESS: self._address,
                    CONF_OWNER_ID: _owner_id(user_input),
                    CONF_COUNTRY: user_input[CONF_COUNTRY],
                    CONF_CLIENT_ID: self._client_id}
            serial, error = await self._async_probe(data)
            if serial is not None:
                return self.async_create_entry(
                    title=f'{BLUETOOTH_NAME} {serial[-4:]}',
                    data={**data, CONF_SERIAL: serial})
            errors['base'] = error
        suggested = user_input or {
            CONF_OWNER_ID: self._cloud_user_id(),
            CONF_COUNTRY: (_default_country(self.hass.config.country)
                           or DEFAULT_COUNTRY)}
        return self.async_show_form(
            step_id='bluetooth_confirm', errors=errors,
            data_schema=self.add_suggested_values_to_schema(
                _bluetooth_schema(), suggested),
            description_placeholders={'address': self._address})

    async def async_step_reauth(self, entry_data: Mapping[str, Any]
                                ) -> ConfigFlowResult:
        if is_bluetooth(entry_data):
            return await self.async_step_reauth_owner()
        if is_phone_account(entry_data):
            return await self.async_step_reauth_phone()
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_phone(
            self, user_input: dict[str, Any] | None = None
            ) -> ConfigFlowResult:
        """The token of a mainland China account ended: send a new code."""

        entry = self._get_reauth_entry()
        phone = entry.data[CONF_PHONE]
        errors: dict[str, str] = {}
        if user_input is not None:
            error = await self._async_send_code(phone)
            if not error:
                self._phone = phone
                return await self.async_step_reauth_code()
            errors['base'] = error
        return self.async_show_form(
            step_id='reauth_phone', errors=errors,
            data_schema=vol.Schema({}),
            description_placeholders={'phone': phone})

    async def async_step_reauth_code(
            self, user_input: dict[str, Any] | None = None
            ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        assert self._phone is not None
        errors: dict[str, str] = {}
        if user_input is not None:
            account, error = await self._async_sign_in_phone(
                self._phone, user_input[CONF_CODE])
            if account is not None:
                await account.close()
                await self.async_set_unique_id(account.user_id)
                self._abort_if_unique_id_mismatch(reason='wrong_account')
                return self.async_update_reload_and_abort(
                    entry, data_updates={
                        CONF_AUTHENTICATION:
                            account.authentication.to_document(),
                    })
            errors['base'] = error
        return self.async_show_form(
            step_id='reauth_code', errors=errors, data_schema=_code_schema(),
            description_placeholders={'phone': self._phone})

    async def async_step_reauth_owner(
            self, user_input: dict[str, Any] | None = None
            ) -> ConfigFlowResult:
        """A 160W refused the identity: ask for its owner's account ID."""

        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            owner_id = _owner_id(user_input)
            data = {**entry.data, CONF_OWNER_ID: owner_id}
            serial, error = await self._async_probe(data)
            if serial is not None:
                if serial != entry.data[CONF_SERIAL]:
                    return self.async_abort(reason='wrong_charger')
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_OWNER_ID: owner_id})
            errors['base'] = error
        suggested = user_input or {
            CONF_OWNER_ID: entry.data.get(CONF_OWNER_ID)
            or self._cloud_user_id()}
        schema = vol.Schema({vol.Optional(CONF_OWNER_ID): TextSelector()})
        return self.async_show_form(
            step_id='reauth_owner', errors=errors,
            data_schema=self.add_suggested_values_to_schema(schema,
                                                            suggested),
            description_placeholders={'name': entry.title})

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

    async def _async_account_found(self, account: CloudAccount,
                                   data: dict[str, Any], title: str
                                   ) -> ConfigFlowResult | None:
        """Keep a signed-in account's data and offer its chargers.

        None when its devices could not be listed.
        """

        try:
            await self.async_set_unique_id(account.user_id)
            self._abort_if_unique_id_configured()
            devices = await account.bound_devices()
        except AnkerPrimeError as failure:
            logger.debug('device list failed: %s', failure)
            return None
        finally:
            await account.close()
        self._chargers = [device for device in devices
                          if device.product_code.upper() in CLOUD_PRODUCTS]
        if not self._chargers:
            return self.async_abort(reason='no_chargers')
        self._data = {**data, CONF_AUTHENTICATION:
                      account.authentication.to_document()}
        self._title = title
        return await self.async_step_chargers()

    async def _async_send_code(self, phone: str) -> str:
        """Have Anker send an SMS code; an error key, or '' when sent."""

        try:
            await async_request_phone_code(self.hass, phone)
        except InvalidParameterError:
            return 'invalid_phone'
        except AuthenticationError as error:
            logger.debug('SMS code refused: %s', error)
            return 'phone_refused'
        except AnkerPrimeError as error:
            logger.debug('SMS code request failed: %s', error)
            return 'cannot_connect'
        except Exception:
            logger.exception('unexpected SMS code error')
            return 'unknown'
        return ''

    async def _async_sign_in_phone(self, phone: str, code: str
                                   ) -> tuple[CloudAccount | None, str]:
        """The account signed in with an SMS code, or None and an error key."""

        try:
            return await async_login_phone(self.hass, phone, code), ''
        except (AuthenticationError, InvalidParameterError):
            return None, 'invalid_code'
        except AnkerPrimeError as error:
            logger.debug('phone sign-in failed: %s', error)
            return None, 'cannot_connect'
        except Exception:
            logger.exception('unexpected phone sign-in error')
            return None, 'unknown'

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

    async def _async_probe(self, data: Mapping[str, Any]
                           ) -> tuple[str | None, str]:
        """Connect once; the charger's serial, or None and an error key."""

        try:
            charger = create_charger(self.hass, data, {},
                                     keep_connection=False, linger=0.0,
                                     energy=False)
        except AnkerPrimeError as error:
            logger.debug('charger not available: %s', error)
            return None, 'not_in_range'
        try:
            await charger.connect()
            serial = charger.state.info.serial
        except AccountRefusedError:
            return None, 'owner_refused'
        except AnkerPrimeError as error:
            logger.debug('Bluetooth connection failed: %s', error)
            return None, 'cannot_connect'
        except Exception:
            logger.exception('unexpected Bluetooth error')
            return None, 'unknown'
        finally:
            await charger.disconnect()
        if serial is None:
            return None, 'cannot_connect'
        return serial, ''

    def _cloud_user_id(self) -> str | None:
        """The Anker user ID of a configured account, if any."""

        for entry in self._async_current_entries(include_ignore=False):
            if not is_bluetooth(entry.data) and entry.unique_id:
                return entry.unique_id
        return None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry
                               ) -> AnkerPrimeOptionsFlow:
        return AnkerPrimeOptionsFlow()


class AnkerPrimeOptionsFlow(OptionsFlowWithReload):
    """Entity update interval; for Bluetooth also the connection mode."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None
                              ) -> ConfigFlowResult:
        bluetooth = is_bluetooth(self.config_entry.data)
        if user_input is not None:
            options: dict[str, Any] = {
                OPTION_UPDATE_INTERVAL:
                    int(user_input[OPTION_UPDATE_INTERVAL])}
            if bluetooth:
                options[OPTION_KEEP_CONNECTION] = bool(
                    user_input[OPTION_KEEP_CONNECTION])
                options[OPTION_READ_INTERVAL] = int(
                    user_input[OPTION_READ_INTERVAL])
            return self.async_create_entry(data=options)
        current = self.config_entry.options
        fields: dict[Any, Any] = {
            vol.Required(OPTION_UPDATE_INTERVAL, default=current.get(
                OPTION_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)):
                _seconds(0, MAX_UPDATE_INTERVAL),
        }
        if bluetooth:
            fields[vol.Required(OPTION_KEEP_CONNECTION, default=current.get(
                OPTION_KEEP_CONNECTION, DEFAULT_KEEP_CONNECTION))] = (
                BooleanSelector())
            fields[vol.Required(OPTION_READ_INTERVAL, default=current.get(
                OPTION_READ_INTERVAL, DEFAULT_READ_INTERVAL))] = _seconds(
                MIN_READ_INTERVAL, MAX_READ_INTERVAL)
        return self.async_show_form(
            step_id='bluetooth' if bluetooth else 'init',
            data_schema=vol.Schema(fields))

    async def async_step_bluetooth(
            self, user_input: dict[str, Any] | None = None
            ) -> ConfigFlowResult:
        return await self.async_step_init(user_input)


def _user_schema() -> vol.Schema:
    return vol.Schema({
        vol.Required(CONF_EMAIL): TextSelector(
            TextSelectorConfig(type=TextSelectorType.EMAIL,
                               autocomplete='username')),
        vol.Required(CONF_PASSWORD): _password(),
        vol.Required(CONF_COUNTRY): _country_selector(),
    })


def _country_selector() -> SelectSelector:
    regions = sorted(((code, name) for code, name in REGIONS.items()
                      if code not in PHONE_REGIONS),
                     key=lambda item: item[1])
    return SelectSelector(SelectSelectorConfig(
        options=[SelectOptionDict(value=code, label=f'{name} ({code})')
                 for code, name in regions],
        mode=SelectSelectorMode.DROPDOWN))


def _bluetooth_schema() -> vol.Schema:
    return vol.Schema({
        vol.Optional(CONF_OWNER_ID): TextSelector(),
        vol.Required(CONF_COUNTRY): _country_selector(),
    })


def _phone_selector() -> TextSelector:
    return TextSelector(TextSelectorConfig(type=TextSelectorType.TEL,
                                           autocomplete='tel'))


def _code_schema() -> vol.Schema:
    return vol.Schema({vol.Required(CONF_CODE): TextSelector(
        TextSelectorConfig(autocomplete='one-time-code'))})


def _owner_id(user_input: Mapping[str, Any]) -> str | None:
    return str(user_input.get(CONF_OWNER_ID) or '').strip() or None


def _seconds(minimum: int, maximum: int) -> NumberSelector:
    return NumberSelector(NumberSelectorConfig(
        min=minimum, max=maximum, step=1, unit_of_measurement='s',
        mode=NumberSelectorMode.BOX))


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
    if code in REGIONS and code not in PHONE_REGIONS:
        return code
    return None
