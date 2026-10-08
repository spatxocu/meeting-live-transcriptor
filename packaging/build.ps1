# Builds the standalone app into dist\MeetingTranscriptor and zips it.
# Run from the project folder:  powershell -File packaging\build.ps1
$root = Split-Path $PSScriptRoot -Parent
$work = Join-Path $root "build"
$dist = Join-Path $root "dist"

& "$root\.venv\Scripts\python.exe" -m PyInstaller "$root\launcher.py" --name MeetingTranscriptor `
    --windowed --noconfirm --clean --icon "$root\assets\icon.ico" `
    --add-data "$root\ui;ui" --add-data "$root\assets;assets" `
    --collect-all faster_whisper --collect-all ctranslate2 --collect-all onnxruntime `
    --collect-all webview --collect-all clr_loader --collect-all pythonnet `
    --collect-all av --collect-all soxr --collect-all tokenizers --hidden-import pyaudiowpatch `
    --distpath $dist --workpath $work --specpath $work --log-level ERROR
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Copy-Item "$PSScriptRoot\READ ME FIRST.txt" "$dist\MeetingTranscriptor\"
$zip = Join-Path $dist "MeetingTranscriptor.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path "$dist\MeetingTranscriptor" -DestinationPath $zip -CompressionLevel Optimal
"Built $zip"
