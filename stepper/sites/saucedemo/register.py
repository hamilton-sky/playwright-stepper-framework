def register(registry, screenshots_dir=None) -> None:
    from stepper.sites.saucedemo.pages.login_action import SDLoginPage
    from stepper.sites.saucedemo.pages.inventory_action import SDInventoryPage
    from stepper.sites.saucedemo.pages.cart_action import SDCartPage
    from stepper.sites.saucedemo.pages.checkout_action import SDCheckoutPage

    SDLoginPage.register(registry)
    SDInventoryPage.register(registry)
    SDCartPage.register(registry)
    SDCheckoutPage.register(registry)
