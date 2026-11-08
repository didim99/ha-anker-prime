"""Building the library's cloud account from user input or entry data."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from homeassistant.const import CONF_COUNTRY, CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import STORAGE_DIR

from ankerprime.api.cloud import (
    AccountOptions, AuthenticationListener, CloudAccount)
from ankerprime.cloud.auth import (
    AccountClient, AccountCredentials, Authentication)
from ankerprime.cloud.http import AiohttpClient
from ankerprime.model import AuthenticationError

from .const import CONF_AUTHENTICATION, DOMAIN, is_phone_account
from .storage import HomeAssistantStore


async def async_login(hass: HomeAssistant,
                      credentials: AccountCredentials) -> CloudAccount:
    """Sign in with the credentials; raises the library's errors."""

    options = AccountOptions(tls_directory=tls_directory(hass))
    return await CloudAccount.login(_http(hass), credentials, options=options)


async def async_request_phone_code(hass: HomeAssistant, phone: str) -> None:
    """Have Anker send a sign-in code by SMS (mainland China)."""

    await AccountClient(_http(hass)).request_phone_code(phone)


async def async_login_phone(hass: HomeAssistant, phone: str,
                            code: str) -> CloudAccount:
    """Sign in a mainland China account with the SMS code."""

    options = AccountOptions(tls_directory=tls_directory(hass))
    return await CloudAccount.login_phone(_http(hass), phone, code,
                                          options=options)


async def async_create_account(hass: HomeAssistant, data: Mapping[str, Any],
                               on_authentication: AuthenticationListener
                               ) -> CloudAccount:
    """The account of a config entry, from its stored token when usable.

    Credentials are kept, so an expired token is replaced by signing in
    again; every new token goes to ``on_authentication``. A mainland China
    (SMS) entry has no credentials: without a usable token it raises
    ``AuthenticationError`` and needs a new code.
    """

    stored = data.get(CONF_AUTHENTICATION)
    authentication = (Authentication.from_document(stored)
                      if isinstance(stored, dict) else None)
    options = AccountOptions(tls_directory=tls_directory(hass),
                             energy_store=HomeAssistantStore(hass),
                             on_authentication=on_authentication)
    if is_phone_account(data):
        if authentication is None:
            raise AuthenticationError('a new SMS code is needed')
        return CloudAccount(_http(hass), authentication, options=options)
    credentials = credentials_from(data)
    if authentication is None:
        account = await CloudAccount.login(_http(hass), credentials,
                                           options=options)
        on_authentication(account.authentication)
        return account
    return CloudAccount(_http(hass), authentication, credentials=credentials,
                        options=options)


def credentials_from(data: Mapping[str, Any]) -> AccountCredentials:
    return AccountCredentials(data[CONF_EMAIL], data[CONF_PASSWORD],
                              data[CONF_COUNTRY])


def tls_directory(hass: HomeAssistant) -> Path:
    """Where the MQTT client identity exists while it loads (moments only)."""

    return Path(hass.config.path(STORAGE_DIR, DOMAIN))


def _http(hass: HomeAssistant) -> AiohttpClient:
    return AiohttpClient(async_get_clientsession(hass))
