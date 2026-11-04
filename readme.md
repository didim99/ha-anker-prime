# Anker Prime for Home Assistant

Home Assistant integration for Anker Prime chargers, built on the
[anker-prime-driver](https://github.com/didim99/anker-prime-driver) library.

> **Status: pre-alpha, under development.** The repository skeleton and test
> setup exist; configuration, entities and actions are being built.

This is an unofficial project, not affiliated with or endorsed by Anker.

## Supported chargers

| Model | Name                     | Connection                              | Notes                                    |
|-------|--------------------------|-----------------------------------------|------------------------------------------|
| A2345 | Anker Prime Charger 250W | Anker cloud (account + MQTT over Wi-Fi) | needs the charger bound in the Anker app |
| A2687 | Anker Prime 160W         | Bluetooth LE (local)                    | planned; not tested on real hardware     |

Requires Home Assistant 2026.1 or later.

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
