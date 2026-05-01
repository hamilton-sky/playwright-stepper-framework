def register(registry, screenshots_dir=None) -> None:
    from sites.ti.pages.login_action import TiLoginPage
    from sites.ti.pages.secure_action import TiSecurePage
    from sites.ti.pages.logout_action import TiLogoutPage
    from sites.ti.pages.checkboxes_action import TiCheckboxesPage
    from sites.ti.pages.dropdown_action import TiDropdownPage
    from sites.ti.pages.windows_action import TiWindowsPage
    from sites.ti.pages.js_alerts_action import TiJsAlertsPage
    from sites.ti.pages.hovers_action import TiHoversPage
    from sites.ti.pages.drag_and_drop_action import TiDragAndDropPage

    TiLoginPage.register(registry)
    TiSecurePage.register(registry)
    TiLogoutPage.register(registry)
    TiCheckboxesPage.register(registry)
    TiDropdownPage.register(registry)
    TiWindowsPage.register(registry)
    TiJsAlertsPage.register(registry)
    TiHoversPage.register(registry)
    TiDragAndDropPage.register(registry)
