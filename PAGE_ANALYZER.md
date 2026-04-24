# PageAnalyzer Component

**Location:** `brightsky-ai/frontend/src/components/PageAnalyzer/`

A comprehensive DOM analysis system that detects, categorizes, and understands page elements for browser automation and AI-driven page comprehension.

---

## Directory Structure

```
PageAnalyzer/
├── analyzers/               # Specialized per-element-type analyzers
├── extractors/              # Data extraction utilities
├── factories/               # Element creation and classification
├── hooks/                   # React hooks (intent routing)
├── observers/               # DOM mutation observers
├── services/                # Orchestration + page understanding
├── store/                   # Zustand state management
├── utils/                   # Visibility, caching, standalone analysis
├── validators/              # Relevance validation
├── index.tsx                # Public exports
└── PageAnalyzer.tsx         # Main React component (periodic analysis)
```

---

## Core Component

### `PageAnalyzer.tsx`
Periodic analysis React component. Runs on a configurable interval (default: 5 minutes) and on page navigation events (`popstate`, history API interception). Broadcasts current page location to Redux and a background service.

---

## Analyzers

| File | Responsibility |
|---|---|
| `ButtonAnalyzer.ts` | Classifies buttons (submit / navigation / action / toggle), generates interaction hints with confidence scores, identifies primary action buttons |
| `FormAnalyzer.ts` | Extracts forms and fields, detects purpose (login / checkout / registration), tracks completion state, detects validation errors |
| `LinkAnalyzer.ts` | Classifies links (internal / external / email / phone / download / social), scores importance, identifies nav paths (main nav, breadcrumbs, footer) |
| `TextAnalyzer.ts` | Extracts headings, paragraphs, lists; computes word count, reading time, readability score, and content structure |
| `DialogAnalyzer.ts` | Detects native dialogs, ARIA dialogs, and modal classes; determines open/closed state and backdrop presence |
| `DOMAnalyzer2.ts` | Orchestrator — runs all analyzers, manages cache, tracks performance, detects page-level issues, generates interaction workflows |
| `PriceAnalyzer.ts` | Extracts prices using pattern matching + meta tags + structured data; supports 15+ currencies |
| `ProductPageDetector.ts` | 100-point scoring system — schema.org detection, buy-button detection in 15+ languages, image dimensions, price presence |
| `StructuredDataAnalyzer.ts` | Parses JSON-LD schema.org data; extracts product name, price, brand, SKU, condition, availability, breadcrumb categories |

---

## Extractors

| File | Responsibility |
|---|---|
| `AttributeExtractor.ts` | Collects element attributes, text content, ARIA compliance, keyboard navigability, color contrast, input errors, importance scoring |
| `PositionExtractor.ts` | Calculates bounding boxes with caching; classifies layer type (modal / tooltip / dropdown / overlay / content / background); detects overlaps |
| `TextExtractor.ts` | Produces clean, deduplicated text snapshots of headings, interactive elements, navigation, and body content for AI consumption |
| `ContextExtractor.ts` | Identifies semantic landmarks, section/article boundaries, heading hierarchy, and form associations |

---

## Factories

### `ElementFactory.ts`
Creates typed element objects (`ButtonElement`, `InputElement`, `LinkElement`, `ImageElement`, `VideoElement`, `AudioElement`, `AnimationElement`) from raw DOM nodes. Uses an LRU cache to avoid re-processing unchanged elements. Handles label association for inputs and classifies button/link roles.

---

## Hooks

### `useIntentRouter.ts`
Maps user intent (from selection rectangles or text) to tool calls via WebSocket. Modifier keys (Ctrl / Shift / Alt) alter the resolved action. Supports `analyze`, `watch`, `wait`, and `click` intents.

---

## Observers

### `MutationObserver.ts`
Wraps the native `MutationObserver` with:
- Noise filtering (ignores script/style-only mutations)
- Significance detection (buttons, forms, dialogs trigger priority processing)
- Debounced callback to avoid thrashing

---

## Services

### `AnalyzerService.ts`
Caching facade over the individual analyzers. Supports area filtering (top / middle / bottom / left / right / center) and result-count limiting. Exposes cache statistics.

### `PageUnderstandingService.ts`
Hybrid heuristic + LLM page comprehension:
- Builds an accessibility tree snapshot
- Generates a semantic DOM representation
- Falls back to LLM-enhanced understanding when heuristics are insufficient
- Exposes a Stagehand-style `act(description)` interface for natural-language element finding

### `TranslationService.ts`
Thin wrapper around the Google Translate free endpoint. Batch-translates with separator handling and graceful network-error fallback.

---

## Store

### `pageAnalysisStore.ts`
Zustand store holding the full analysis state:
- Categorized elements: buttons, forms, links, text, dialogs
- Product detection result + signals
- Analysis metadata: element count, last-updated timestamp, active status
- History log
- Memoized selectors for performance

### `pageAnalysisService.ts`
Coordinates the store with live DOM changes:
- Initial full-page scan on load
- Periodic cache-aware updates
- Incremental updates triggered by the mutation observer
- Detects language, platform, and tracker presence

---

## Utils

| File | Responsibility |
|---|---|
| `VisibilityUtils.ts` | Checks display/visibility/opacity, clickability, viewport presence, interaction blocking; batch-filters element lists |
| `CacheManager.ts` | Generic LRU cache with time-based expiration, size limits, entry count limits, and hit-rate tracking |
| `analyzePageDirect.ts` | Standalone (no React/store dependency) full-page analysis; collects viewport metadata and returns a `PageContext` object |

---

## Key Types

| Type | Description |
|---|---|
| `SimpleElement` | Base element: position, visibility, attributes, confidence score |
| `ButtonElement` / `InputElement` / `LinkElement` / `ImageElement` | Specialised subtypes of `SimpleElement` |
| `FormElement` | Form with field array, purpose, completion state, validation errors |
| `PageContext` | Full analysis result: DOM structure, metadata, viewport, language |
| `DOMStructure` | Categorised collections of all element types |
| `ProductDetectionResult` | Detection signals, score (0–100), extracted product data |

---

## Key Capabilities

- **Multi-type element detection** — buttons, forms, links, text, dialogs, prices, products
- **Accessibility analysis** — ARIA compliance, keyboard navigation, contrast checking
- **Product page detection** — 100-point scoring, schema.org + visual signals, 15+ languages
- **Price extraction** — 15+ currencies, pattern matching + structured data
- **Caching** — LRU at factory, analyzer, and service levels
- **DOM monitoring** — debounced mutation observer with significance filtering
- **Page understanding** — heuristic-first, LLM fallback, natural-language element finding
- **Multilingual support** — buy-button detection and translation in 15+ languages
