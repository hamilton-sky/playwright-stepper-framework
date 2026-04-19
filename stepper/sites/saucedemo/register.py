def register(registry, screenshots_dir=None) -> None:
    from sites.saucedemo.pages.login_action import SDLoginPage
    from sites.saucedemo.pages.inventory_action import SDInventoryPage
    from sites.saucedemo.pages.cart_action import SDCartPage
    from sites.saucedemo.pages.checkout_action import SDCheckoutPage

    SDLoginPage.register(registry)
    SDInventoryPage.register(registry)
    SDCartPage.register(registry)
    SDCheckoutPage.register(registry)
