#!/usr/bin/env node
/**
 * PostToolUse hook: After editing a glue file, reminds about the resolver injection contract.
 * After editing a workflow JSON, reminds that selectors do not belong there.
 *
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

    const normalized = filePath.replace(/\\/g, '/');

    // Glue layer edited
    if (/stepper\/sites\/[^/]+\/pages\/[^/]+\.py$/.test(normalized)) {
      const msg = JSON.stringify({
        systemMessage: [
          'Glue file edited. Self-check before proceeding:',
          '  1. Every POM construction must pass page=page, resolver=resolver',
          '     CORRECT:   LoginPage(driver, url, delays, page=page, resolver=resolver)',
          '     WRONG:     LoginPage(driver, url)  ← resolver cascade never fires',
          '  2. No raw page.locator("css") calls — selectors belong in POM cfg lists',
          '  3. Action name in register() must match the "action" key in workflow JSON',
          'See .claude/rules/glue-layer.md for the full rule set.'
        ].join('\n')
      });
      process.stdout.write(msg + '\n');
    }

    // Workflow JSON edited
    if (/stepper\/sites\/[^/]+\/workflows\/[^/]+\.json$/.test(normalized)) {
      const msg = JSON.stringify({
        systemMessage: [
          'Workflow JSON edited. Self-check:',
          '  - Workflow steps must NOT contain CSS selectors or XPath strings',
          '  - Selectors belong in poms/*/pages/ locator cfg lists',
          '  - Flows control order, conditions, and variables only',
          'See .claude/rules/three-layer-contract.md for the full rule set.'
        ].join('\n')
      });
      process.stdout.write(msg + '\n');
    }
  } catch {
    // Silently ignore parse errors
  }

  process.exit(0);
});
