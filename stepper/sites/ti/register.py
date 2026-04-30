def register(registry, screenshots_dir=None) -> None:
    from sites.ti.pages.login_action import TiLoginPage
    from sites.ti.pages.secure_action import TiSecurePage

    TiLoginPage.register(registry)
    TiSecurePage.register(registry)
