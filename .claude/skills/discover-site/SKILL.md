---
name: discover-site
description: Navigate a website using Playwright MCP, follow a flow described in plain English, and write a11y trace data to .stepper/ for downstream POM generation.
argument-hint: "--url <url> --flow <description> [--output <dir>]"
---

You are an intelligent browser agent. Your job is to navigate a website following a plain-English flow description, capture accessibility tree data at each page state, and write structured output files to the output directory for use by `/generate-poms`.

## Argument Parsing

Parse `$ARGUMENTS` as follows:

- `--url <url>` (required): The starting URL to navigate to.
- `--flow <description>` (required): A plain-English description of the user flow to execute (e.g., "log in and add the first item to cart").
- `--output <dir>` (optional, default: `.stepper/`): Directory to write output files.

If `--url` or `--flow` is missing, print an error and exit non-zero:
```
Error: --url and --flow are required.
Usage: /discover-site --url <url> --flow <description> [--output <dir>]
```

Assign variables:
- `TARGET_URL` = value of `--url`
- `FLOW_DESC` = value of `--flow`
- `OUTPUT_DIR` = value of `--output`, or `.stepper/` if not provided

Create `OUTPUT_DIR` and `OUTPUT_DIR/snapshots/` if they do not exist.

Record `started_at` as current ISO-8601 UTC timestamp.

---

## Navigation Strategy

### Step 0 — Prerequisite: credentials

Before opening the browser, check if the flow description mentions login, sign in, or authentication. If it does:

- Look for `SD_USER`, `SD_PASS`, `APP_USER`, `APP_PASS` or similar env vars using `Bash("env | grep -i user; env | grep -i pass")`.
- If none are found, print:
  ```
  Error: Flow requires login but no credential env vars found.
  Set SD_USER and SD_PASS (or APP_USER / APP_PASS) before running.
  ```
  Exit non-zero immediately. Do NOT open the browser.
- If found, store them internally as `CRED_USER` and `CRED_PASS`. **Never write actual credential values to disk.** Use placeholders `${env.SD_USER}` and `${env.SD_PASS}` (or appropriate names) everywhere you record element values.

### Step 1 — Open browser and take initial snapshot

```
mcp__playwright__browser_navigate(url=TARGET_URL)
snapshot = mcp__playwright__browser_snapshot()
```

Derive a `slug` from the current URL path (lowercase, alphanumeric, hyphens only; use `"home"` if path is `/` or empty).

Save the snapshot to `OUTPUT_DIR/snapshots/<slug>.json` immediately (eager write).

### Step 2 — Navigation loop

Repeat until the flow description is fully satisfied or no further interactions are possible:

1. **Identify the next action** from the remaining flow keywords.
   - Parse the flow description into a sequence of intent tokens (e.g., "log in" → fill username, fill password, click submit; "add first item" → click first add-to-cart button).
   - Match intent tokens to elements in the current snapshot using `role` + `name` (prefer role+name over CSS or XPath).
   - If multiple candidates match, pick the element whose `name` or `label` has the highest lexical overlap with the flow keyword.
   - If zero candidates match, record `complete: false` and exit 1 (see Error Handling).

2. **Record the element** before interacting (see Output Contract for schema).
   - For fill actions: write the placeholder `${env.SD_USER}` (or `${env.SD_PASS}`) as the recorded value — never the actual credential.
   - For click actions: record role, name, landmark.

3. **Execute the interaction:**
   - Fill: `mcp__playwright__browser_fill(element=<selector>, value=<actual_credential_or_value>)`
   - Click: `mcp__playwright__browser_click(element=<selector>)`
   - Use `role` + `name` as the selector string where possible (e.g., `"textbox 'Username'"`).

4. **Re-snapshot** after the interaction:
   ```
   snapshot = mcp__playwright__browser_snapshot()
   ```

5. **Detect page change:** compare current URL to previous URL.
   - If URL changed: derive new slug, save `OUTPUT_DIR/snapshots/<slug>.json` eagerly, append a new page record.
   - If URL unchanged: update the current page's element list with any newly visible elements.

6. **Continue** with the next flow token.

### Decision rules

- Always prefer `role` + `name` resolution over CSS or XPath.
- If an element has a `label`, prefer label-matching over name-matching.
- For ambiguous matches (e.g., multiple buttons named "Add to cart"), pick the first one unless the flow description specifies an ordinal ("first", "second", etc.).
- Record `landmark` as the ARIA landmark region containing the element (`"main"`, `"navigation"`, `"dialog"`, `"form"`, etc.). Use `"unknown"` if not determinable.
- If a modal or dialog appears: record its elements with `landmark: "dialog"`. Continue the flow inside the dialog.
- If an iframe is encountered: record elements with `landmark: "iframe:<name>"`. Continue if accessible; skip if sandboxed.

---

## Output Contract

### Directory layout

```
<output_dir>/
  trace.json              ← ordered page visits + all recorded elements
  snapshots/
    <slug>.json           ← full a11y snapshot for one page
```

### trace.json schema

```json
{
  "url": "<TARGET_URL>",
  "flow": "<FLOW_DESC>",
  "started_at": "<ISO-8601 UTC>",
  "complete": true,
  "pages": [
    {
      "slug": "login",
      "url": "https://www.saucedemo.com/",
      "title": "<page title>",
      "elements": [
        {
          "role": "textbox",
          "name": "Username",
          "label": "Username",
          "placeholder": "Username",
          "id": "user-name",
          "css": "#user-name",
          "landmark": "main"
        }
      ],
      "sections": [
        {
          "landmark": "main",
          "description": "Login form with username and password fields"
        }
      ]
    }
  ]
}
```

**Field rules:**
- `complete`: `true` if the full flow was executed; `false` if aborted early.
- `pages`: one entry per distinct URL visited (not per interaction).
- Element fields: omit a field entirely (do not write `null`) if the value is not present in the a11y tree.
- `css`: derive as `#<id>` when `id` is present; otherwise omit.
- `sections`: one entry per ARIA landmark region on the page. `description` is a one-sentence plain-English summary of what that region contains.
- Credential values: **never** appear in any element field. Replace with `${env.SD_USER}` / `${env.SD_PASS}` (or the appropriate env var name).

### snapshots/<slug>.json schema

Raw a11y snapshot for the page. Write the full output of `mcp__playwright__browser_snapshot()` for this page. This file is for debugging and downstream diffing — no credential values may appear.

### Write order

1. Write `snapshots/<slug>.json` **immediately after each page visit** (eager write — do not wait until the end).
2. Write `trace.json` **once at the very end**, after all interactions are complete.

This ensures partial data is preserved even if the run is interrupted.

---

## Error Handling

### Playwright MCP not available

Before navigating, verify Playwright MCP is available by attempting:
```
mcp__playwright__browser_snapshot()
```
If the tool does not exist or returns a tool-not-found error, print:
```
Error: Playwright MCP is not connected.
Run: claude mcp add playwright
Then restart Claude Code and retry.
```
Exit non-zero. Do not create any output files.

### Element not found

If no element in the current snapshot matches the next flow token:

1. Write `OUTPUT_DIR/trace.json` with `"complete": false` and all pages recorded so far.
2. Print:
   ```
   Error: Could not find element matching "<flow token>" on <current URL>.
   Partial trace written to <output_dir>/trace.json.
   ```
3. Exit 1.

### Network timeout

If a navigation or interaction times out:

1. Retry once after 30 seconds:
   ```
   mcp__playwright__browser_navigate(url=<current_url>)
   ```
2. If the retry also times out, write the partial trace with `"complete": false` and exit 1:
   ```
   Error: Navigation to <url> timed out after retry. Partial trace written.
   ```

### Login required but no credentials

Handled in Step 0 (pre-flight). Exit before opening the browser.

### Modal or iframe

- **Modal/dialog**: Record elements inside the dialog with `"landmark": "dialog"`. Continue the flow. If the dialog blocks the flow and cannot be dismissed, record `complete: false` and exit 1.
- **Iframe**: Record elements with `"landmark": "iframe:<name>"` where `<name>` is the iframe's `title` or `name` attribute. If the iframe is cross-origin/sandboxed and inaccessible, log a warning and skip:
  ```
  Warning: iframe "<name>" is inaccessible (cross-origin). Skipping.
  ```
  Continue the flow with remaining elements.

### Partial writes

Always prefer writing partial output over writing nothing. If an unhandled error occurs mid-run:
1. Attempt to write `trace.json` with whatever pages were collected and `"complete": false`.
2. Print the error with full context.
3. Exit 1.
