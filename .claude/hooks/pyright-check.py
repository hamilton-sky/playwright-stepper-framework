import sys
import json
import subprocess

data = json.load(sys.stdin)
file_path = data.get("tool_input", {}).get("file_path", "")

if not file_path.endswith(".py"):
    sys.exit(0)

result = subprocess.run(
    f'npx pyright "{file_path}"',
    capture_output=True, text=True, shell=True
)
output = (result.stdout + result.stderr).strip()

feedback = {
    "hookSpecificOutput": {
        "hookEventName": "PostToolUse",
        "additionalContext": f"Pyright on {file_path}:\n{output}"
    }
}
print(json.dumps(feedback))
