# Anker Prime for Home Assistant

Home Assistant integration for Anker Prime chargers, built on the
[anker-prime-driver](https://github.com/didim99/anker-prime-driver) library.

> [!NOTE]
> **Status: alpha.** The 250W works through the Anker cloud, tested on real
> hardware and used daily. The 160W works over Bluetooth in tests but has not
> been tried on a real charger yet. Entities and options may still change
> before 1.0; see the [changelog](changelog.md).

This is an unofficial project, not affiliated with or endorsed by Anker.

## Supported chargers

| Model | Name                     | Connection                              | Verified on hardware                                             |
|-------|--------------------------|-----------------------------------------|------------------------------------------------------------------|
| A2345 | Anker Prime Charger 250W | Anker cloud (account + MQTT over Wi-Fi) | everything except the UFCS switch and showing own clock pictures |
| A2687 | Anker Prime 160W         | Bluetooth LE (local adapter or proxy)   | not tested on real hardware                                      |

The 250W must be bound to an Anker account in the Anker app. Accounts of
mainland China sign in with the phone number and an SMS code (not tested
with a real account).

## Installation

Requires Home Assistant 2026.1 or later. Home Assistant installs the
[anker-prime-driver](https://pypi.org/project/anker-prime-driver/) library
itself, in the exact version the integration pins.

**HACS (custom repository):**

1. HACS → ⋮ → Custom repositories: add
   `https://github.com/didim99/ha-anker-prime`, type **Integration**.
2. Find **Anker Prime** in HACS, download it and restart Home Assistant.
3. Add it under Settings → Devices & services → Add integration → Anker
   Prime.

**Manually:** copy `custom_components/anker_prime/` to
`/config/custom_components/`, restart Home Assistant and add the integration
as above.

The integration also loads Home Assistant's Bluetooth integration, which the
160W needs; without a Bluetooth adapter it simply stays idle. Its icon and logo
appear from Home Assistant 2026.3 on.

## Features

- **Setup in the UI**, three ways (Add integration → Anker Prime):
  - **Anker account** (250W): sign in, choose the chargers; one device per
    charger, all sharing one connection. A second Anker account, with the
    chargers shared to it, keeps the Anker app's own login untouched.
  - **Anker account in mainland China** (250W): the phone number and a code
    sent by SMS. Without a password the login cannot be renewed: when it
    ends, Home Assistant asks for a new code.
  - **Bluetooth** (160W): discovered automatically, or picked from the
    chargers nearby; one entry per charger. See [160W over
    Bluetooth](#160w-over-bluetooth).
- **Sensors:** power, voltage, current and status (idle, active, charging;
  cable, protocol and device as attributes) per port; total power; energy per
  port and in total for the energy dashboard; when each output's countdown
  ends; the picture the 160W's screen shows.
- **Switches:** power per output; preferred outputs of the port-priority mode;
  clock screensaver, holiday themes, max compatibility, device
  identification, UFCS; the account's custom mode setting (Labs, 250W); the
  time over own clock pictures (250W); display auto-rotation (160W).
- **Selects and numbers:** charging mode, screen timeout, knob direction, hour
  format, clock theme, display brightness; on the 250W a custom profile
  select that applies a profile stored in the Anker account (leave custom
  mode with the charging mode select) and a clock picture select (the Anker
  catalogue and the account's own pictures); on the 160W also fixed
  allocation, screen orientation and display language (the charger does not
  report the last two, so they read unknown until set from Home Assistant).
- **Buttons:** refresh the settings; reset the energy counters (disabled by
  default).
- **Binary sensors:** over-temperature and output faults; "port charging"
  (disabled by default).
- **Actions** on the output switches: `anker_prime.set_schedule`,
  `anker_prime.disable_schedule`, `anker_prime.start_countdown`,
  `anker_prime.cancel_countdown`; on the clock screensaver switch:
  `anker_prime.set_clock_schedule`; on the charging mode select:
  `anker_prime.set_custom_limits` (custom mode without storing a profile;
  the only way on the 160W); on the custom profile select:
  `anker_prime.save_custom_profile` (a new profile starts from the Anker
  app's defaults) and `anker_prime.delete_custom_profile`; on the clock
  picture select: `anker_prime.upload_clock_picture` and
  `anker_prime.delete_clock_picture`; on the 160W's screen picture sensor:
  `anker_prime.upload_screen_picture` and
  `anker_prime.select_screen_picture` (see [Pictures](#pictures)). Output
  switches show their schedules and countdown as attributes.
- **Options:** the minimum interval between entity updates (default 5 s; 0
  updates on every reading, about once a second). Energy is counted from
  every reading either way and kept across restarts.
- Re-authentication when Anker stops accepting the login, a repair notice
  when a charger stays offline for 30 minutes, and diagnostics with secrets
  removed.
- **Languages:** English and Russian.

Features the library has not confirmed on real hardware yet are disabled by
default; enable them on the entity page to try them. Entities appear only for
what the charger model offers.

## Pictures

Picture actions read an image file from a folder Home Assistant allows: the
media folders, `www`, or one listed in `allowlist_external_dirs`. Relative
paths start at the configuration folder. Any image works; it is cropped to
fill the charger's format.

- **250W clock pictures:** the clock picture select lists the Anker
  catalogue and the account's own pictures (`Own <id>`). Choosing one waits
  until the charger has downloaded it and switches the clock on.
  `upload_clock_picture` adds an own picture to the account (480×200; at
  most eight); choose it in the select to show it.
- **160W screen picture** (disabled by default):
  `upload_screen_picture` writes a 240×240 picture to the charger and shows
  it. **This cannot be undone**: no command removes a picture from the
  charger, so the action needs `acknowledge_irreversible: true`. It returns
  the picture's ID and CRC-32 (also kept as attributes of the sensor), which
  `select_screen_picture` takes to show it again later.

## 160W over Bluetooth

Needs Home Assistant's Bluetooth integration with a connectable adapter, or an
ESPHome Bluetooth proxy, in range of the charger. Home Assistant offers newly
seen chargers on the integrations page; otherwise add one by hand and choose
**Bluetooth**.

- **Access check:** setup connects once and reads the charger's serial. Newer
  firmware only accepts the Anker account the charger is bound to: enter that
  account's user ID as the owner account ID (prefilled from a configured
  Anker account; the library's CLI prints it after `ankerprime login`).
  Without it such a charger refuses the session and setup says so. If the
  charger starts refusing later, Home Assistant asks for the owner ID again.
- **One connection at a time:** while Home Assistant holds the connection,
  the Anker app cannot reach the charger. Close the app before setting it up.
- **Options:** keep the connection open (default; live readings about once a
  second), or connect only for each read (every 60 s by default, 30–3600 s)
  and each command, which leaves room for the app in between. Energy between
  reads up to two minutes apart is interpolated; longer gaps count nothing.
- **Offline notice:** a repair notice appears when no readings arrive for 30
  minutes.

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
power, total energy and a reset button (it asks before resetting); below:
output switches and a power graph.

![Port cards with button-card](docs/images/ports-button-card.png)

### Core cards only

[`docs/cards/ports-core-cards.yaml`](docs/cards/ports-core-cards.yaml) needs
nothing extra: tiles for total power, energy and whether the charger is live,
a button per output, a table of all ports and a power graph.

![Core cards only](docs/images/ports-core-cards.png)

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
shows the versions in use. A test checks that the manifest pins exactly the
library version under test: after changing the library, publish it and move
the pin together.

Formatting and import order follow the project codestyle by hand; `ruff check`
verifies line length and common lint rules.

Before a release, run Home Assistant's `hassfest` and the HACS checks on
GitHub: Actions → Validate → Run workflow. Changes are listed in
[changelog.md](changelog.md).

### Tests on a real 250W

`hardware/` tests the integration end to end, in a real Home Assistant. It
starts a Home Assistant container, installs this working copy of the
integration, adds the charger with the email and password stored by the
library's `ankerprime login`, and enables every entity except the energy
reset. Then it changes each setting that can be put back, through the
integration's entities and actions, checks what Home Assistant reports after
a refresh and restores the original value. The last test compares every
touched value with the state found at the start. At the end the entry and
the container are removed, its volume included.

Run it on the host, next to Docker. The library's development environment
has everything it needs (or install `hardware/requirements.txt`):

```bash
pytest hardware -rs
```

Writes that cannot be undone are never made. No own picture is shown on the
charger: an uploaded test picture is deleted from the account again. Schedule
slots that were never set are skipped, since the charger has no "unset" value
to restore. Outputs are switched only when one is on and powers nothing.
Settings stored in the Anker account are read back by reloading the entry, so
a run takes several minutes. Mainland China (SMS) accounts and the 160W are
not covered.

| Option                       | Default                                        | Meaning                                                                          |
|------------------------------|------------------------------------------------|----------------------------------------------------------------------------------|
| `--hardware-serial=SERIAL`   | the CLI's default charger, else the only one   | Charger to test                                                                  |
| `--hardware-image=IMAGE`     | `ghcr.io/home-assistant/home-assistant:stable` | Home Assistant image, pulled when missing (`docker pull` for a newer one)        |
| `--hardware-library=PATH`    | the released version                           | Library working copy to install in the container instead                         |
| `--hardware-settle=SECONDS`  | 5                                              | Wait for a read-back after a refresh                                             |
| `--hardware-timeout=SECONDS` | 300                                            | Limit for Home Assistant to start and for the entry to load                      |
| `--hardware-keep`            | off                                            | Keep the container and the entry afterwards; the address and sign-in are printed |

Write option values with `=`: pytest reads a separate value as a path to
collect tests from. Home Assistant's log, with the integration and the
library at debug level, is saved in pytest's temporary folder; its path is
printed at the end. The container connects to the Anker cloud directly, with
its own sign-in; the CLI's login stays valid.

### Unreleased library versions

To try library changes before they are on PyPI, build a wheel
(`python -m build` in `anker-prime-driver`), copy it to `/config/wheels/` and
point the manifest's requirement at it, locally only:

```json
"requirements": ["anker-prime-driver[ble] @ file:///config/wheels/anker_prime_driver-0.7.4-py3-none-any.whl"]
```

Every rebuilt wheel needs a new version: Home Assistant hands the requirement
to `uv` on every start, and `uv` skips a version that is already installed.
Pre-releases (`0.7.4rc1`) published to PyPI work with an exact pin as well.
Commit only exact pins of published versions.

## Credits

The protocol knowledge comes from [Charker](https://github.com/qzz0518/Charker)
by qzz0518 (MIT), through the `anker-prime-driver` library.

## License

MIT — see [LICENSE](LICENSE). Anker trademarks belong to their owner.
