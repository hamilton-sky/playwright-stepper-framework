def register(registry, screenshots_dir=None) -> None:
    from sites.pathly.pages.home_screen_action import PathlyHomeScreen
    from sites.pathly.pages.settings_action import PathlySettings
    from sites.pathly.pages.top_bar_action import PathlyTopBar

    PathlyHomeScreen.register(registry)
    PathlySettings.register(registry)
    PathlyTopBar.register(registry)
