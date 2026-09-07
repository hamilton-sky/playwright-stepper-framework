## Site-Specific Actions

Every action below is registered by the site's `register.py` at startup.
Verify against the code with:

```bash
grep -rn "action_name" stepper/sites/<site>/pages/
```

### OpenLibrary (`stepper/sites/openlibrary/pages/`)

| Action name | Glue file | POM(s) used |
|---|---|---|
| `ol_ensure_login` | `login_action.py` | `LoginPage` |
| `collect_items` (alias: `ol_collect_books`) | `search_page.py` | `BookSearchPage` |
| `ol_add_to_shelf` | `detail_page.py` | `BookDetailPage` |
| `ol_clear_reading_list` | `reading_list_action.py` | `ReadingListPage` + `BookDetailPage` |
| `ol_store_count` | `reading_list_action.py` | `ReadingListPage` |
| `ol_assert_count` | `reading_list_action.py` | `ReadingListPage` |
| `ol_ensure_count` | `reading_list_action.py` | `ReadingListPage` |

`collect_items` is the registered `action_name`; `ol_collect_books` is an alias bound to
the same instance in `OLSearchPage.register()`. Both work in workflow JSON — the shipped
workflows use `ol_collect_books`.

### SauceDemo (`stepper/sites/saucedemo/pages/`)

| Action name | Glue file | POM(s) used |
|---|---|---|
| `sd_login` | `login_action.py` | `LoginPage` |
| `sd_collect_products` | `inventory_action.py` | `InventoryPage` |
| `sd_add_to_cart` | `inventory_action.py` | `InventoryPage` |
| `sd_sort_products` | `inventory_action.py` | `InventoryPage` |
| `sd_view_cart` | `cart_action.py` | `CartPage` |
| `sd_checkout` | `checkout_action.py` | `CartPage` + `CheckoutInfoPage` + `CheckoutOverviewPage` + `CheckoutCompletePage` |

### phpTravels (`stepper/sites/phptravels/pages/`) — in progress

| Action name | Glue file | POM(s) used |
|---|---|---|
| `pt_login` | `login_action.py` | `LoginPage` |
| `pt_search_hotels` | `hotel_search_action.py` | `HomePage` |
| `pt_select_hotel` | `hotel_results_action.py` | `HotelResultsPage` |
| `pt_book_hotel` | `hotel_detail_action.py` | `HotelDetailPage` |

---

## Workflow Files

| Site | Workflow dir |
|---|---|
| OpenLibrary | `stepper/sites/openlibrary/workflows/` |
| SauceDemo | `stepper/sites/saucedemo/workflows/` |
| phpTravels | `stepper/sites/phptravels/workflows/` |

Run any workflow from the repo root:

```bash
python stepper/main.py --workflow stepper/sites/<site>/workflows/<file>.json
```
