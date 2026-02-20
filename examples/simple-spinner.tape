Output examples/simple-spinner.gif

Require bat
Require uv

Set Shell "bash"
Set FontSize 16
Set Width 1200
Set Height 800

Sleep 500ms
Type "bat examples/simple-spinner.py" Sleep 500ms  Enter

Sleep 3s

Type "uv run python examples/simple-spinner.py" Sleep 500ms Enter

Sleep 10s
