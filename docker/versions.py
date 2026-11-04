"""Prints the versions a test run uses."""

import sys
from importlib.metadata import version


print(f'Home Assistant {version("homeassistant")}, '
      f'Python {sys.version.split()[0]}, '
      f'anker-prime-driver {version("anker-prime-driver")}')
