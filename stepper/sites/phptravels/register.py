def register(registry, screenshots_dir=None) -> None:
    from stepper.sites.phptravels.pages.login_action import PTLoginPage
    from stepper.sites.phptravels.pages.hotel_search_action import PTHotelSearchPage
    from stepper.sites.phptravels.pages.hotel_results_action import PTHotelResultsPage
    from stepper.sites.phptravels.pages.hotel_detail_action import PTHotelDetailPage

    PTLoginPage.register(registry)
    PTHotelSearchPage.register(registry)
    PTHotelResultsPage.register(registry)
    PTHotelDetailPage.register(registry)
