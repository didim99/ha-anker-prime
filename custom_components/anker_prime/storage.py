"""The library's ``DocumentStore`` on Home Assistant's ``Store`` helper."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from ankerprime.interfaces.storage import DocumentStore, JsonDocument

from .const import DOMAIN, STORAGE_VERSION


class HomeAssistantStore(DocumentStore):
    """One private ``.storage`` file per key, named ``anker_prime.<key>``."""

    _hass: HomeAssistant
    _stores: dict[str, Store[JsonDocument]]

    def __init__(self, hass: HomeAssistant):
        self._hass = hass
        self._stores = {}

    async def load(self, key: str) -> JsonDocument | None:
        return await self._store(key).async_load()

    async def save(self, key: str, document: JsonDocument) -> None:
        await self._store(key).async_save(document)

    async def delete(self, key: str) -> None:
        await self._store(key).async_remove()

    def _store(self, key: str) -> Store[JsonDocument]:
        store = self._stores.get(key)
        if store is None:
            store = Store(self._hass, STORAGE_VERSION, f'{DOMAIN}.{key}',
                          private=True)
            self._stores[key] = store
        return store
