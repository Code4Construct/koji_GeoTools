param(
    [string]$OutputDir = "dist"
)

$ErrorActionPreference = "Stop"

$pluginRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$pluginName = Split-Path $pluginRoot -Leaf
$outputRoot = Join-Path $pluginRoot $OutputDir
$stagingRoot = Join-Path $outputRoot "_staging"
$stagingPlugin = Join-Path $stagingRoot $pluginName
$zipPath = Join-Path $outputRoot "$pluginName.zip"

if (Test-Path $stagingRoot) {
    Remove-Item -LiteralPath $stagingRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $stagingPlugin | Out-Null

$excludeDirs = @(
    ".agents",
    ".git",
    ".github",
    ".qodo",
    "__pycache__",
    "dist",
    "tools"
)

$excludeFiles = @(
    ".gitignore",
    "*.pyc",
    "*.pyo",
    "*.zip",
    "improvement.md",
    "IMPLEMENTATION_PLAN.md",
    "KOJIQGIS_DEVELOPMENT_PLAN.md",
    "ChatGPT Image*.png"
)

Get-ChildItem -LiteralPath $pluginRoot -Force | ForEach-Object {
    $skip = $excludeDirs -contains $_.Name
    if (-not $skip -and -not $_.PSIsContainer) {
        foreach ($pattern in $excludeFiles) {
            if ($_.Name -like $pattern) {
                $skip = $true
                break
            }
        }
    }
    if (-not $skip) {
        Copy-Item -LiteralPath $_.FullName -Destination $stagingPlugin -Recurse -Force
    }
}

Get-ChildItem -LiteralPath $stagingPlugin -Recurse -Force | Where-Object {
    ($_.PSIsContainer -and $excludeDirs -contains $_.Name) -or
    (-not $_.PSIsContainer -and (
        $_.Name -like "*.pyc" -or
        $_.Name -like "*.pyo" -or
        $_.Name -like "ChatGPT Image*.png"
    ))
} | Sort-Object FullName -Descending | ForEach-Object {
    Remove-Item -LiteralPath $_.FullName -Recurse -Force
}

if (Test-Path $zipPath) {
    Remove-Item -LiteralPath $zipPath -Force
}
Compress-Archive -Path $stagingPlugin -DestinationPath $zipPath -Force
Remove-Item -LiteralPath $stagingRoot -Recurse -Force

Write-Host "Created $zipPath"
