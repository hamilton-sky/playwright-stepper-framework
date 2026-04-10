**Glue Architecture (Stepper Integration)**
```
ol_stepper
└─ pages/
   ├─ search_page.py
   │  └─ Stepper ActionStrategy
   │     └─ calls openlibrary_exam.pages.BookSearchPage
   │        (passes resolver + Playwright page)
   │
   ├─ detail_page.py
   │  └─ Stepper ActionStrategy
   │     └─ calls openlibrary_exam.pages.BookDetailPage
   │        (passes resolver + Playwright page)
   │
   └─ reading_list_action.py
      └─ Stepper ActionStrategy
         └─ calls openlibrary_exam.pages.ReadingListPage
            (passes resolver + Playwright page)
```

**Connection diagram**
```
Stepper Runner (src/runner)
      |
      v
ActionRegistry (src/actions)
      |
      v
ol_stepper/pages/*  (glue)
      |
      v
openlibrary_exam/pages/*  (POMs)
```

**Rule**
```
Glue does NOT own selectors.
Selectors live only in openlibrary_exam POMs.
```
