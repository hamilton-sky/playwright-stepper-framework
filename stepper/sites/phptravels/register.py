def register(registry, screenshots_dir=None) -> None:
    from sites.phptravels.pages.login_action import PTLoginPage
    from sites.phptravels.pages.hotel_search_action import PTHotelSearchPage
    from sites.phptravels.pages.hotel_results_action import PTHotelResultsPage
    from sites.phptravels.pages.hotel_detail_action import PTHotelDetailPage

    PTLoginPage.register(registry)
    PTHotelSearchPage.register(registry)
    PTHotelResultsPage.register(registry)
    PTHotelDetailPage.register(registry)
