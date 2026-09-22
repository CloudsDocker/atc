# atc demo recording
#
#   brew install vhs          # or: go install github.com/charmbracelet/vhs@latest
#   uv sync
#   vhs vhs/atc.tape          # writes figures/demo.gif
#
# Runs entirely on --fake: no AWS, no cluster, no network, nothing to redact.

Output figures/demo.gif

Set Shell       "bash"
Set FontSize    15
Set Width       1200
Set Height      640
Set Padding     18
Set Theme       "Catppuccin Mocha"
Set TypingSpeed 60ms
Set Framerate   24

Type "uv run atc --fake"
Sleep 400ms
Enter
Sleep 3s

# The watch list: connection path on top, starred DAGs with run-history strips.
Sleep 2s

# Flick between environments — each tab keeps its own connection and cursor.
Tab
Sleep 1500ms
Tab
Sleep 1500ms
Tab
Sleep 1s

# Drill into a failing DAG's run history.
Down
Sleep 400ms
Down
Sleep 600ms
Enter
Sleep 2500ms

# Into the task log — the empty-log finding.
Enter
Sleep 3s

Escape
Sleep 800ms
Escape
Sleep 1s

# Browse the full DAG list and star something.
Type "a"
Sleep 2s
Down
Sleep 300ms
Down
Sleep 500ms
Enter
Sleep 1500ms

Type "q"
Sleep 1s
