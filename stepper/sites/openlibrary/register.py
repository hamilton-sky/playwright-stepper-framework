from pathlib import Path


def register(registry, screenshots_dir=None) -> None:
    from sites.openlibrary.pages.search_page import OLSearchPage
    from sites.openlibrary.pages.detail_page import OLDetailPage
    from sites.openlibrary.pages.reading_list_action import OLReadingListPage
    from sites.openlibrary.pages.login_action import OLLoginPage

    OLSearchPage.register(registry)
    OLDetailPage.register(registry, screenshots_dir=screenshots_dir or Path("artifacts/screenshots"))
    OLReadingListPage.register(registry)
    OLLoginPage.register(registry)
