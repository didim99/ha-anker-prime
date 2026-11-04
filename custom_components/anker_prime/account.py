"""Building the library's cloud account from user input or entry data."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from homeassistant.const import CONF_COUNTRY, CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import STORAGE_DIR

from ankerprime.api.cloud import AuthenticationListener, CloudAccount
from ankerprime.cloud.auth import AccountCredentials, Authentication
from ankerprime.cloud.http import AiohttpClient

from .const import CONF_AUTHENTICATION, DOMAIN
from .storage import HomeAssistantStore


async def async_login(hass: HomeAssistant,
                      credentials: AccountCredentials) -> CloudAccount:
    """Sign in with the credentials; raises the library's errors."""

    return await CloudAccount.login(_http(hass), credentials,
                                    tls_directory=tls_directory(hass))


async def async_create_account(hass: HomeAssistant, data: Mapping[str, Any],
                               on_authentication: AuthenticationListener
                               ) -> CloudAccount:
    """The account of a config entry, from its stored token when usable.

    Credentials are kept, so an expired token is replaced by signing in
    again; every new token goes to ``on_authentication``.
    """

    credentials = credentials_from(data)
    stored = data.get(CONF_AUTHENTICATION)
    authentication = (Authentication.from_document(stored)
                      if isinstance(stored, dict) else None)
    store = HomeAssistantStore(hass)
    if authentication is None:
        account = await CloudAccount.login(
            _http(hass), credentials, tls_directory=tls_directory(hass),
            energy_store=store, on_authentication=on_authentication)
        on_authentication(account.authentication)
        return account
    return CloudAccount(_http(hass), authentication, credentials=credentials,
                        tls_directory=tls_directory(hass), energy_store=store,
                        on_authentication=on_authentication)


def credentials_from(data: Mapping[str, Any]) -> AccountCredentials:
    return AccountCredentials(data[CONF_EMAIL], data[CONF_PASSWORD],
                              data[CONF_COUNTRY])


def tls_directory(hass: HomeAssistant) -> Path:
    """Where the MQTT client identity exists while it loads (moments only)."""

    return Path(hass.config.path(STORAGE_DIR, DOMAIN))


def _http(hass: HomeAssistant) -> AiohttpClient:
    return AiohttpClient(async_get_clientsession(hass))
