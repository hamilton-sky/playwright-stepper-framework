#!/usr/bin/env node
/**
 * PostToolUse hook: After writing/editing a POM file, reminds about the Locator rule.
 *
 * Triggers on any Write or Edit to a POM page file under poms/<site>/pages/.
 * Provides informational feedback only — does NOT block edits.
 * Exit code is always 0.
 */

let input = '';

process.stdin.setEncoding('utf8');
process.stdin.on('data', (chunk) => { input += chunk; });
process.stdin.on('end', () => {
  try {
    const data = JSON.parse(input);
    const filePath = (data.tool_input && (data.tool_input.file_path || data.tool_input.path)) || '';

    // Normalize path separators for Windows
    const normalized = filePath.replace(/\\/g, '/');

    if (/poms\/[^/]+\/pages\/[^/]+\.py$/.test(normalized)) {
      const msg = JSON.stringify({
        systemMessage: [
          'POM file edited. Self-check before proceeding:',
          '  1. Every fill() / click() target → a Locator object (poms/shared/locator.py), not a bare CSS string',
          '  2. Route interactions through _interact(locator, "fill"|"click") — not the driver directly',
          '  3. Give every Locator a description= — Phase 2 embeds it for semantic resolution',
          '  4. Plain CSS strings are only OK for read-only checks (query_selector, locator_count)',
          '  5. No imports from stepper/ — POMs must not depend on the glue layer',
          '  6. The POM must still work with resolver=None and behaviour=None',
          'See .claude/rules/pom-layer.md for the full rule set.'
        ].join('\n')
      });
      process.stdout.write(msg + '\n');
    }
  } catch {
    // Silently ignore parse errors
  }

  process.exit(0);
});
