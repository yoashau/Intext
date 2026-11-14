$ErrorActionPreference = "Stop"
$command = Get-Command uv.exe -ErrorAction SilentlyContinue
$uv = if ($command) { $command.Source } else { Join-Path $env:USERPROFILE ".local\bin\uv.exe" }
if (-not (Test-Path -LiteralPath $uv)) { throw "uv was not found. Install uv and try again." }

function Quote-ProcessArgument([string]$value) {
    if ($value.Length -gt 0 -and $value -notmatch '[\s"]') { return $value }
    $escaped = $value -replace '(\\*)"', '$1$1\"'
    $escaped = $escaped -replace '(\\+)$', '$1$1'
    return '"' + $escaped + '"'
}

$previousProjectEnvironment = $env:UV_PROJECT_ENVIRONMENT
$previousPythonDirectory = $env:UV_PYTHON_INSTALL_DIR
$previousCacheDirectory = $env:UV_CACHE_DIR
$previousHttpTimeout = $env:UV_HTTP_TIMEOUT
if (-not $previousPythonDirectory) { $env:UV_PYTHON_INSTALL_DIR = [Environment]::GetEnvironmentVariable("UV_PYTHON_INSTALL_DIR", "User") }
if (-not $previousCacheDirectory) { $env:UV_CACHE_DIR = [Environment]::GetEnvironmentVariable("UV_CACHE_DIR", "User") }
if (-not $previousHttpTimeout) { $env:UV_HTTP_TIMEOUT = [Environment]::GetEnvironmentVariable("UV_HTTP_TIMEOUT", "User") }
if (-not $previousProjectEnvironment -and $PSScriptRoot -match '^\\\\wsl(?:\.localhost|\$)\\') {
    # Keep the Windows venv on a local disk when the source is in WSL.
    $env:UV_PROJECT_ENVIRONMENT = Join-Path $env:USERPROFILE ".local\share\intext\venv"
}
$locationPushed = $false
try {
    Push-Location $PSScriptRoot
    $locationPushed = $true
    $arguments = @("run", "--locked", "--managed-python", "--extra", "windows", "python", "-m", "intext") + $args
    $argumentLine = ($arguments | ForEach-Object { Quote-ProcessArgument ([string]$_) }) -join ' '
    $process = Start-Process -FilePath $uv -ArgumentList $argumentLine -PassThru -Wait -NoNewWindow
    exit $process.ExitCode
} finally {
    if ($locationPushed) { Pop-Location }
    $env:UV_PROJECT_ENVIRONMENT = $previousProjectEnvironment
    $env:UV_PYTHON_INSTALL_DIR = $previousPythonDirectory
    $env:UV_CACHE_DIR = $previousCacheDirectory
    $env:UV_HTTP_TIMEOUT = $previousHttpTimeout
}
