#!/usr/bin/env node
/**
 * PreToolUse hook: Guards against dangerous commands in the stepper framework.
 * Blocks: rm -rf on critical dirs, force push to main, DROP TABLE,
 *         git reset --hard without target.
 *
 * Exit codes:
 *   0 = allow
 *   2 = block (with reason on stderr)
 */

let input = '';

process.stdin.setEncoding('utf8');
process.stdin.on('data', (chunk) => { input += chunk; });
process.stdin.on('end', () => {
  try {
    const data = JSON.parse(input);
    const command = (data.tool_input && data.tool_input.command) || '';

    // Block rm -rf on critical project directories
    if (/rm\s+(-[a-zA-Z]*r[a-zA-Z]*f|--force.*--recursive|--recursive.*--force)\s+(\.|\.\/|poms|stepper|exam|\.claude)/i.test(command)) {
      process.stderr.write('BLOCKED: Destructive rm on critical project directories. Use specific file paths instead.\n');
      process.exit(2);
    }

    // Block force push to main/master
    if (/git\s+push.*(-f|--force).*\b(main|master)\b/i.test(command) ||
        /git\s+push.*\b(main|master)\b.*(-f|--force)/i.test(command)) {
      process.stderr.write('BLOCKED: Force push to main/master branch is not allowed.\n');
      process.exit(2);
    }

    // Block dropping database tables
    if (/DROP\s+(TABLE|DATABASE)/i.test(command)) {
      process.stderr.write('BLOCKED: Database destructive operations require manual execution.\n');
      process.exit(2);
    }

    // Block git reset --hard without specific target
    if (/git\s+reset\s+--hard\s*$/i.test(command.trim())) {
      process.stderr.write('BLOCKED: git reset --hard without a specific target can lose work. Specify a commit or branch.\n');
      process.exit(2);
    }

    process.exit(0);
  } catch {
    // If JSON parsing fails, allow the command (don't block on hook errors)
    process.exit(0);
  }
});
