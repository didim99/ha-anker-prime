"""Constants of the Anker Prime integration."""

from datetime import timedelta

from ankerprime.model import OutputId, PortId


DOMAIN = 'anker_prime'

CONF_AUTHENTICATION = 'authentication'
CONF_SERIALS = 'serials'

OPTION_UPDATE_INTERVAL = 'update_interval'
DEFAULT_UPDATE_INTERVAL = 5
MAX_UPDATE_INTERVAL = 300

OFFLINE_ISSUE_AFTER = timedelta(minutes=30)
HEALTH_CHECK_INTERVAL = timedelta(minutes=1)

STORAGE_VERSION = 1

MANUFACTURER = 'Anker'

# Labels used in entity names, as printed on the charger.
OUTPUT_LABELS = {OutputId.C1: 'C1', OutputId.C2: 'C2', OutputId.C3: 'C3',
                 OutputId.C4: 'C4', OutputId.USB_A: 'USB-A'}
PORT_LABELS = {PortId.C1: 'C1', PortId.C2: 'C2', PortId.C3: 'C3',
               PortId.C4: 'C4', PortId.A1: 'A1', PortId.A2: 'A2'}
