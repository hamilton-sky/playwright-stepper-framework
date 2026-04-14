#!/usr/bin/env node
/**
 * PostToolUse hook: After writing/editing a POM file, reminds about the cfg list rule.
 *
 * Triggers on any Write or Edit to poms/*/pages/*.py
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
          '  1. Every fill() / click() call → locator must be a cfg list (list of dicts with "priority")',
          '  2. Plain CSS strings are only OK for read-only checks (query_selector, locator_count)',
          '  3. No imports from stepper/sites/ — POMs must not depend on the glue layer',
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
