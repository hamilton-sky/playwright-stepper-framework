**Glue Architecture (Stepper Integration)**

Three layers — each with a single responsibility:

```
shared_poms/pages/          POM layer — owns selectors + raw page interactions
                            No framework coupling. No flow logic.
                            LoginPage, BookSearchPage, BookDetailPage, ReadingListPage

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
shared_poms/pages/*  (POMs — selectors live here and nowhere else)
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
ol_ensure_count  →  context.counts["gap"] = N     (set when top-up needed)
ol_collect_books →  reads gap from context as limit fallback
                    when: context_key_exists: gap  (skipped if already at target)
ol_add_to_shelf  →  when: context_key_exists: collected_items
ol_assert_count  →  when: context_key_exists: gap
```
