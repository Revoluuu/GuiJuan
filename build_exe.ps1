$ErrorActionPreference = "Stop"

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    python -m venv .venv
}

.\.venv\Scripts\python.exe -c "import PyInstaller, PyPDF2" 2>$null
if ($LASTEXITCODE -ne 0) {
    .\.venv\Scripts\python.exe -m pip install ".[build]"
}
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onefile --windowed `
    --name GuiJuan `
    --icon assets\guijuan-scroll-hd-v3.ico `
    --add-data "assets\guijuan-scroll-hd-v3.ico;assets" `
    --add-data "assets\guijuan-scroll-sidebar-v3.png;assets" `
    --add-data "assets\parchment-bamboo-banner-v2.png;assets" `
    --add-data "assets\parchment-bamboo-side-v2.png;assets" `
    paper_folder_gui.py

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed with exit code $LASTEXITCODE"
}

Write-Host "Built: dist\GuiJuan.exe"
