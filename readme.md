# Anker Prime for Home Assistant

Home Assistant integration for Anker Prime chargers, built on the
[anker-prime-driver](https://github.com/didim99/anker-prime-driver) library.

> **Status: pre-alpha, under development.** The 250W works through the Anker
> cloud; the 160W (Bluetooth) is not done yet.

This is an unofficial project, not affiliated with or endorsed by Anker.

## Supported chargers

| Model | Name                     | Connection                              | Notes                                       |
|-------|--------------------------|-----------------------------------------|------------------------------------------|
| A2345 | Anker Prime Charger 250W | Anker cloud (account + MQTT over Wi-Fi) | needs the charger bound in the Anker app    |
| A2687 | Anker Prime 160W         | Bluetooth LE (local)                    | planned; not tested on real hardware        |

Requires Home Assistant 2026.1 or later.

## Features

- **Setup in the UI:** sign in with an Anker account, choose the chargers;
  one device per charger. All chargers of an account share one connection.
  A second Anker account, with the chargers shared to it, keeps the Anker
  app's own login untouched.
- **Sensors:** power, voltage, current and status (idle, active, charging;
  cable, protocol and device as attributes) per port; total power; energy per
  port and in total for the energy dashboard; when each output's countdown
  ends.
- **Switches:** power per output; preferred outputs of the port-priority mode;
  clock screensaver, holiday themes, max compatibility, device
  identification, UFCS.
- **Selects and numbers:** charging mode, screen timeout, knob direction, hour
  format, clock theme, display brightness.
- **Buttons:** refresh the settings; reset the energy counters (disabled by
  default).
- **Binary sensors:** over-temperature and output faults; "port charging"
  (disabled by default).
- **Actions** on the output switches: `anker_prime.set_schedule`,
  `anker_prime.disable_schedule`, `anker_prime.start_countdown`,
  `anker_prime.cancel_countdown`; on the clock screensaver switch:
  `anker_prime.set_clock_schedule`. Output switches show their schedules and
  countdown as attributes.
- **Options:** the minimum interval between entity updates (default 5 s; 0
  updates on every reading, about once a second). Energy is counted from
  every reading either way and kept across restarts.
- Re-authentication when Anker stops accepting the login, a repair notice
  when a charger stays offline for 30 minutes, and diagnostics with secrets
  removed.

Features the library has not confirmed on real hardware yet are disabled by
default; enable them on the entity page to try them.

## Dashboard examples

Two ready-made port monitors for a 250W. Paste a file into a dashboard
(Edit dashboard → Add card → Manual). Entity IDs follow the device name; the
examples use a device named "250W Prime", so replace the `250w_prime_`
prefix with yours (see any entity's settings for its ID).

### Port cards with button-card

[`docs/cards/ports-button-card.yaml`](docs/cards/ports-button-card.yaml)
needs [button-card](https://github.com/custom-cards/button-card) (HACS,
version 4). One card per port shows its status, power, voltage, current and
energy, with a bar for power against the port's maximum; color shows the
state (charging, active, idle, output off). Tap a port for its power history,
hold it for the output switch with schedules and countdown. Above them: total
power, total energy and a reset button (it asks before resetting).

![Port cards with button-card](docs/images/ports-button-card.png)

### Core cards only

[`docs/cards/ports-core-cards.yaml`](docs/cards/ports-core-cards.yaml) needs
nothing extra: tiles for total power, energy and whether the charger is live,
a button per output, a table of all ports and a power graph.

![Core cards only](docs/images/ports-core-cards.png)

## Installation (development)

Until the library is published, Home Assistant installs it from a wheel file:

1. Build the library wheel (`python -m build` in `anker-prime-driver`) and copy
   it to `/config/wheels/`.
2. Make sure the wheel name in
   `custom_components/anker_prime/manifest.json` matches it. Every rebuilt
   wheel needs a new version (`0.1.0.dev1`, ...): Home Assistant hands the
   requirement to `uv` on every start, and `uv` skips a version that is
   already installed.
3. Copy `custom_components/anker_prime/` to `/config/custom_components/` and
   restart Home Assistant.
4. Add it under Settings → Devices & services → Add integration → Anker
   Prime.

## Development

Tests run in Docker, against the oldest supported and the newest Home
Assistant. The library working copy is expected next to this repository
(`../anker-prime-driver`); set `LIBRARY_PATH` to use another location.

```bash
docker compose build
docker compose run --rm test-min        # Home Assistant 2026.1, Python 3.13
docker compose run --rm test-latest     # newest Home Assistant, Python 3.14
docker compose run --rm library-latest  # library test suite on Python 3.14
```

Each run installs the library from a fresh copy of its working tree, then runs
`ruff check`, `mypy` and `pytest`; extra arguments go to pytest
(`docker compose run --rm test-min -k flow`). Both repositories are mounted
read-only, so runs leave no files behind. `test-latest` follows the newest
`pytest-homeassistant-custom-component` release each time its image is rebuilt
(`docker compose build --no-cache test-latest`); the first line of every run
shows the versions in use.

Formatting and import order follow the project codestyle by hand; `ruff check`
verifies line length and common lint rules.

## Credits

The protocol knowledge comes from [Charker](https://github.com/qzz0518/Charker)
by qzz0518 (MIT), through the `anker-prime-driver` library.

## License

MIT — see [LICENSE](LICENSE). Anker trademarks belong to their owner.
