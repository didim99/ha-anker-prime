"""Constants of the Anker Prime integration."""

from collections.abc import Mapping
from datetime import timedelta
from typing import Any

from ankerprime.model import OutputId, PortId


DOMAIN = 'anker_prime'

# Entry types: one per Anker account (cloud) or per 160W (Bluetooth).
# Entries without the key are cloud entries.
CONF_CONNECTION = 'connection'
CONNECTION_CLOUD = 'cloud'
CONNECTION_BLUETOOTH = 'bluetooth'

CONF_AUTHENTICATION = 'authentication'
CONF_SERIALS = 'serials'
CONF_SERIAL = 'serial'
CONF_OWNER_ID = 'owner_id'
CONF_CLIENT_ID = 'client_id'

OPTION_UPDATE_INTERVAL = 'update_interval'
DEFAULT_UPDATE_INTERVAL = 5
MAX_UPDATE_INTERVAL = 300

OPTION_KEEP_CONNECTION = 'keep_connection'
DEFAULT_KEEP_CONNECTION = True
OPTION_READ_INTERVAL = 'read_interval'
DEFAULT_READ_INTERVAL = 60
MIN_READ_INTERVAL = 30
MAX_READ_INTERVAL = 3600

DEFAULT_COUNTRY = 'US'
BLUETOOTH_NAME = 'Anker Prime 160W'

OFFLINE_ISSUE_AFTER = timedelta(minutes=30)
HEALTH_CHECK_INTERVAL = timedelta(minutes=1)

STORAGE_VERSION = 1

MANUFACTURER = 'Anker'

# Labels used in entity names, as printed on the charger.
OUTPUT_LABELS = {OutputId.C1: 'C1', OutputId.C2: 'C2', OutputId.C3: 'C3',
                 OutputId.C4: 'C4', OutputId.USB_A: 'USB-A'}
PORT_LABELS = {PortId.C1: 'C1', PortId.C2: 'C2', PortId.C3: 'C3',
               PortId.C4: 'C4', PortId.A1: 'A1', PortId.A2: 'A2'}


def is_bluetooth(data: Mapping[str, Any]) -> bool:
    """Whether entry data describes a Bluetooth (160W) entry."""

    return data.get(CONF_CONNECTION) == CONNECTION_BLUETOOTH
