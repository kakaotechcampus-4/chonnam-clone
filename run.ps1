param(
    [switch]$week1,
    [switch]$install
)

if ($install) {
    Write-Host "Installing dependencies using uv..."
    uv sync
}

Write-Host "Setting environment variables for Week 1..."
$env:KANANA_ACTIVE_WEEK = "1"
$env:PYTHONNOUSERSITE = "1"

Write-Host "Running app.py with uv..."
uv run python app.py
