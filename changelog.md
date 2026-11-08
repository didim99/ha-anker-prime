# Changelog

All notable changes to the Anker Prime integration (`ha-anker-prime`). The
format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

Versioning while in development (major version 0): the minor version grows
with big changes (a new platform, charger model or entry type), the patch
version with every other change to the integration itself. Documentation,
examples, test tooling and changes that only move the library pin keep the
version.

## [0.3.0] - 2026-11-08

The remaining features of the library's 0.8.0 release.

### Added
- 250W custom charging: a custom profile select applies a profile stored in
  the Anker account; actions `save_custom_profile` and
  `delete_custom_profile` on it; a switch for the account's custom mode
  setting (Labs).
- Custom limits without a stored profile: action `set_custom_limits` on the
  charging mode select, for both models (the 160W's only custom mode; C1–C3,
  experimental).
- 250W clock pictures: a clock picture select with the Anker catalogue and
  the account's own pictures; actions `upload_clock_picture` and
  `delete_clock_picture` on it; a switch for the time over own pictures
  (experimental, disabled by default).
- 160W screen picture (experimental, disabled by default): a sensor with the
  picture shown; actions `upload_screen_picture` (irreversible, needs
  `acknowledge_irreversible: true`, returns the picture's ID and CRC-32) and
  `select_screen_picture`.
- Mainland China accounts: setup with the phone number and an SMS code;
  re-authentication asks for a new code, as such a login cannot be renewed
  otherwise. Custom profiles use the mainland limits.
- Picture actions read image files from folders Home Assistant allows.

### Changed
- Requires `anker-prime-driver[ble,pictures]==0.8.1`: the account is built
  with the library's `AccountOptions`; country choices follow its
  `PHONE_REGIONS`; Pillow (shipped with Home Assistant) prepares pictures.
  0.8.1 makes the time over own pictures switch reliable.
- Diagnostics also redact the phone number.

## [0.2.3] - 2026-11-07

### Added
- Manifest categories (energy meters and monitoring; plugs and switches) for
  HACS and Home Assistant's integration lists.

## [0.2.2] - 2026-11-07

### Added
- Russian translation.
- Brand images (icon and logo) in the integration; shown by Home Assistant
  2026.3 and later.

## [0.2.1] - 2026-11-07

### Changed
- The library is installed from PyPI (`anker-prime-driver[ble]==0.7.3`)
  instead of a local wheel; installation through HACS (custom repository) or
  by copying the folder.

## [0.2.0] - 2026-11-07

### Added
- Anker Prime 160W over Bluetooth, through Home Assistant's Bluetooth stack
  (local adapters or ESPHome proxies):
  - discovery, or a pick list of chargers nearby; setup checks access once
    and reads the serial;
  - owner account ID for firmware that only accepts the bound Anker
    account, prefilled from a configured Anker account; asked again when the
    charger starts refusing;
  - options: keep the connection open, or connect only to read (interval
    30–3600 s) and for commands, leaving room for the Anker app;
  - entities for fixed allocation, screen orientation, display language and
    display auto-rotation;
  - offline notice worded for Bluetooth.

### Changed
- Adding the integration starts with a choice: Anker account or Bluetooth.
- The integration depends on Home Assistant's Bluetooth integration.

## [0.1.0] - 2026-11-04

### Added
- Anker Prime Charger 250W through the Anker cloud:
  - setup with an Anker account, charger selection, re-authentication;
  - sensors (power, voltage, current, status, energy, totals, countdown
    end), binary sensors, switches, selects, display brightness, buttons;
  - actions for output schedules, countdowns and the clock schedule;
  - option for the minimum interval between entity updates;
  - offline repair notice and redacted diagnostics.

### Documentation
- Dashboard examples with core cards and with button-card.

## [0.0.1] - 2026-11-04

### Added
- Integration skeleton and Docker test setup (oldest supported and newest
  Home Assistant).
