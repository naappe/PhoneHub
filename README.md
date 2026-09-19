# PhoneHub

PhoneHub is being rebuilt from a clean architecture.

The previous codebase is preserved on branch:

`legacy-before-fresh-rebuild-2026-09-19`

## New direction

- Python 3.12+
- PySide6 desktop UI
- typed domain models
- isolated device/ADB services
- explicit connection state machine
- no hidden background services
- no legacy compatibility code
- one application process, one media session owner
- tests run only against the current architecture

## Run

```bat
RUN_PHONEHUB.bat
```

This first clean baseline intentionally focuses on architecture and UI. Device transport will be reintroduced service-by-service after each layer has tests.
