# Thin shim: all logic lives in dev.py
python "$PSScriptRoot\dev.py" @args
exit $LASTEXITCODE
