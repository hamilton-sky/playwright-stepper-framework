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
          '  1. Build POMs with self._build_pom(...), passing page=, resolver= and behaviour=',
          '     CORRECT:   self._build_pom(LoginPage, driver, url, page=page, resolver=resolver, behaviour=behaviour)',
          '     WRONG:     LoginPage(driver, url)  ← resolver cascade never fires',
          '  2. No raw page.locator("css") calls — selectors belong in POM Locator objects',
          '  3. action_name must match the "action" key in workflow JSON and start with site prefix',
          '  4. Implement _execute(self, page, step, resolver, context, behaviour=None) — never override execute()',
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
          '  - Selectors belong in Locator objects under poms/<site>/pages/',
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
