---
description: Per-site action reference tables — action names, glue files, POMs used
globs:
  - "stepper/sites/**/*.py"
  - "stepper/sites/**/*.json"
---

## Site-Specific Actions

### OpenLibrary (`stepper/sites/openlibrary/pages/`)

| Action name | Glue file | POM(s) used |
|---|---|---|
| `ol_ensure_login` | `login_action.py` | `LoginPage` |
| `ol_collect_books` / `collect_items` | `search_page.py` | `BookSearchPage` |
| `ol_add_to_shelf` | `detail_page.py` | `BookDetailPage` |
| `ol_clear_reading_list` | `reading_list_action.py` | `ReadingListPage` + `BookDetailPage` |
| `ol_store_count` | `reading_list_action.py` | `ReadingListPage` |
| `ol_assert_count` | `reading_list_action.py` | `ReadingListPage` |
| `ol_ensure_count` | `reading_list_action.py` | `ReadingListPage` |

### SauceDemo (`stepper/sites/saucedemo/pages/`)

| Action name | Glue file | POM(s) used |
|---|---|---|
| `sd_login` | `login_action.py` | `LoginPage` |
| `sd_add_to_cart` | `inventory_action.py` | `InventoryPage` |
| `sd_sort_products` | `inventory_action.py` | `InventoryPage` |
| `sd_view_cart` | `cart_action.py` | `CartPage` |
| `sd_checkout` | `checkout_action.py` | `CartPage` + `CheckoutInfoPage` + `CheckoutOverviewPage` + `CheckoutCompletePage` |

### phpTravels (`stepper/sites/phptravels/pages/`) — in progress

| Action name | Glue file | POM(s) used |
|---|---|---|
| _(TBD)_ | _(TBD)_ | `LoginPage`, `HomePage`, `HotelResultsPage`, `HotelDetailPage` |

---

## Workflow Files

| Site | Workflow dir |
|---|---|
| OpenLibrary | `stepper/sites/openlibrary/workflows/` |
| SauceDemo | `stepper/sites/saucedemo/workflows/` |
| phpTravels | `stepper/sites/phptravels/workflows/` |

Run any workflow with:
```bash
python stepper/main.py --workflow stepper/sites/<site>/workflows/<file>.json
```
