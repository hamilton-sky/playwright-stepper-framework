"""
sites/pathly/register.py — Registers the Pathly Studio actions.

Pathly is an Electron app, so it is the **web** domain reached a
different way: start the app with --remote-debugging-port and set
STEPPER_ELECTRON_CDP_PORT, and the web session attaches over CDP
instead of launching a browser. Nothing here launches Pathly.

Imports are inside the function so register_all_sites does not pull the
POM layer, and Playwright with it, into runs that never touch a browser.
"""
from __future__ import annotations

def register(registry, screenshots_dir=None) -> None:
    from stepper.sites.pathly.pages.home_screen_action import PathlyHomeScreen
    from stepper.sites.pathly.pages.settings_action import PathlySettings
    from stepper.sites.pathly.pages.top_bar_action import PathlyTopBar
    from stepper.sites.pathly.pages.wizard_action import PathlyWizard

    PathlyHomeScreen.register(registry)
    PathlySettings.register(registry)
    PathlyTopBar.register(registry)
    PathlyWizard.register(registry)
