**Glue Architecture (Stepper Integration)**

Three layers — each with a single responsibility:

```
poms/openLibrary/pages/     POM layer — owns selectors + raw page interactions
                            No framework coupling. No flow logic.
                            LoginPage, BookSearchPage, BookDetailPage, ReadingListPage
                            collect_books_under_year() returns list[dict{url, year}]

sites/openlibrary/pages/    Glue layer — wraps POM methods into named Stepper behaviors
                            No selectors. No flow logic. Calls POM methods only.
                            login_action.py    → ol_ensure_login
                            search_page.py     → ol_collect_books
                            detail_page.py     → ol_add_to_shelf
                            reading_list_action.py → ol_clear_reading_list
                                                     ol_store_count
                                                     ol_assert_count
                                                     ol_ensure_count

workflows/*.json            Flow layer — controls order, conditions, variables
                            No selectors. Calls named actions only.
                            when: guards drive conditional execution via context.
```

**Connection diagram**
```
workflow JSON  (declares what + order)
      │
      ▼
StepRunner  (evaluates when-guards, dispatches actions)
      │
      ▼
Glue pages/*  (named behaviors — one action, one job)
      │
      ▼
poms/*/pages/*  (POMs — selectors live here and nowhere else)
      │
      ▼
Playwright Page
```

**Three rules**
```
1. Selectors live only in POMs — never in glue, never in JSON.
2. Flow logic lives only in JSON — never in glue, never in POMs.
3. Actions do one job — if two behaviors exist, they are two actions.
```

**Context as the signal between steps**
```
ol_ensure_count  →  context.counts["gap"] = N          (set when top-up needed)

ol_collect_books →  when: { context_greater_than: { key: gap, value: 0 } }
                    extra.limit = "{{gap}}"             (resolved at runtime by StepRunner)
                    sets context.collected_items = list[dict{url, year}]
                    StepResult.output = {items: [{url, year}, …]}

ol_add_to_shelf  →  when: { context_key_exists: collected_items }
                    StepResult.output = {books: [{url, year, shelf}, …]}

ol_assert_count  →  when: { context_greater_than: { key: gap, value: 0 } }
```

**Two-phase variable resolution**
```
Plan time  — JsonFilePlanner substitutes variables{} into all step fields
             e.g.  "{{target_count}}" → 5  before StepRunner ever sees the step

Runtime    — StepRunner._resolve_context_vars() substitutes context.counts keys
             e.g.  "{{gap}}" → 3  right before executing each step
             Pure "{{key}}" references preserve the original type (int/bool).
```

**when condition operators (full set)**
```
context_equals        { key, value }          exact equality
context_key_exists    "key_name"              set + non-empty
context_greater_than  { key, value }          numeric >
context_less_than     { key, value }          numeric <
context_between       { key, min, max }       inclusive range
url_contains          "fragment"              current page URL
element_exists        "css selector"          live DOM check
not / all / any       composable              invert / AND / OR
```
