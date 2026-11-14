param(
  [string]$WorkDirectory = (Join-Path $env:USERPROFILE ".cache\intext\build"),
  [string]$OutputDirectory = (Join-Path $env:USERPROFILE "Downloads")
)

$ErrorActionPreference = "Stop"
$command = Get-Command uv.exe -ErrorAction SilentlyContinue
$uv = if ($command) { $command.Source } else { Join-Path $env:USERPROFILE ".local\bin\uv.exe" }
if (-not (Test-Path -LiteralPath $uv)) { throw "uv was not found. Install uv and try again." }
$work = [IO.Path]::GetFullPath($WorkDirectory)
if ($work.StartsWith("\\")) { throw "The build work directory must be on a local Windows drive." }
$log = Join-Path $env:USERPROFILE ".cache\intext\build.log"
$downloads = [IO.Path]::GetFullPath($OutputDirectory)
$workPrefix = $work.TrimEnd('\') + '\'
if ($downloads.Equals($work, [StringComparison]::OrdinalIgnoreCase) -or $downloads.StartsWith($workPrefix, [StringComparison]::OrdinalIgnoreCase)) {
  throw "The output directory must be outside the build work directory."
}
New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null
New-Item -ItemType Directory -Force -Path $downloads | Out-Null
function Log($m) { $line = "$(Get-Date -Format o) $m"; Add-Content -Path $log -Value $line; Write-Output $line }

Log "copy source"
if (Test-Path -LiteralPath $work) {
  if (-not (Test-Path -LiteralPath (Join-Path $work ".intext-build-work"))) {
    throw "Refusing to remove an unmarked work directory: $work"
  }
  Remove-Item -LiteralPath $work -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $work | Out-Null
New-Item -ItemType File -Path (Join-Path $work ".intext-build-work") | Out-Null
$origin = Split-Path -Parent $PSScriptRoot
Copy-Item -Recurse "$origin\src" "$work\src"
Copy-Item -Recurse "$origin\packaging" "$work\packaging"
Copy-Item "$origin\pyproject.toml" "$work\pyproject.toml"
Copy-Item "$origin\uv.lock" "$work\uv.lock"
Copy-Item "$origin\.python-version" "$work\.python-version"
Get-ChildItem -Recurse $work -Directory -Filter __pycache__ | Remove-Item -Recurse -Force

Log "sync uv environment"
$previousProjectEnvironment = $env:UV_PROJECT_ENVIRONMENT
$previousPythonDirectory = $env:UV_PYTHON_INSTALL_DIR
$previousCacheDirectory = $env:UV_CACHE_DIR
$previousHttpTimeout = $env:UV_HTTP_TIMEOUT
try {
  if (-not $previousPythonDirectory) { $env:UV_PYTHON_INSTALL_DIR = [Environment]::GetEnvironmentVariable("UV_PYTHON_INSTALL_DIR", "User") }
  if (-not $previousCacheDirectory) { $env:UV_CACHE_DIR = [Environment]::GetEnvironmentVariable("UV_CACHE_DIR", "User") }
  if (-not $previousHttpTimeout) { $env:UV_HTTP_TIMEOUT = [Environment]::GetEnvironmentVariable("UV_HTTP_TIMEOUT", "User") }
  if (-not $previousProjectEnvironment -and $origin -match '^\\\\wsl(?:\.localhost|\$)\\') {
    $env:UV_PROJECT_ENVIRONMENT = Join-Path $env:USERPROFILE ".local\share\intext\venv"
  }
  $venv = $env:UV_PROJECT_ENVIRONMENT
  if (-not $venv) { $venv = Join-Path $origin ".venv" }
  elseif (-not [IO.Path]::IsPathRooted($venv)) { $venv = Join-Path $origin $venv }
  $py = Join-Path $venv "Scripts\python.exe"
  $deps = Start-Process -FilePath $uv -WorkingDirectory $origin -ArgumentList @("sync", "--locked", "--managed-python", "--extra", "windows", "--group", "build") -PassThru -Wait -WindowStyle Hidden -RedirectStandardOutput "$work\dependencies.stdout.log" -RedirectStandardError "$work\dependencies.stderr.log"
} finally {
  $env:UV_PROJECT_ENVIRONMENT = $previousProjectEnvironment
  $env:UV_PYTHON_INSTALL_DIR = $previousPythonDirectory
  $env:UV_CACHE_DIR = $previousCacheDirectory
  $env:UV_HTTP_TIMEOUT = $previousHttpTimeout
}
if ($deps.ExitCode -ne 0) {
  Get-Content "$work\dependencies.stdout.log", "$work\dependencies.stderr.log" | Write-Output
  throw "uv environment sync failed $($deps.ExitCode)"
}
if (-not (Test-Path -LiteralPath $py)) { throw "missing $py" }
Set-Location $work
Log "pyinstaller"
$models = Start-Process -FilePath $py -ArgumentList @('"{0}"' -f "$work\packaging\prepare_ocr.py") -PassThru -Wait -WindowStyle Hidden -RedirectStandardOutput "$work\ocr-models.stdout.log" -RedirectStandardError "$work\ocr-models.stderr.log"
if ($models.ExitCode -ne 0) {
  Get-Content "$work\ocr-models.stdout.log", "$work\ocr-models.stderr.log" | Write-Output
  throw "OCR model verification failed $($models.ExitCode)"
}
$build = Start-Process -FilePath $py -ArgumentList "-m", "PyInstaller", "--noconfirm", "--clean", ('"{0}"' -f "$work\packaging\intext.spec") -PassThru -Wait -WindowStyle Hidden -RedirectStandardOutput "$work\pyinstaller.stdout.log" -RedirectStandardError "$work\pyinstaller.stderr.log"
Get-Content "$work\pyinstaller.stderr.log" | Write-Output
if ($build.ExitCode -ne 0) { throw "pyinstaller failed $($build.ExitCode)" }
$exe = Join-Path $work "dist\Intext\Intext.exe"
if (-not (Test-Path $exe)) { throw "missing $exe" }
Log "exe ready $((Get-Item $exe).Length)"

Log "Defender scan application"
& "$work\packaging\scan.ps1" -Path (Split-Path $exe) -ReportPath "$work\defender-app.json"

Log "check"
$proc = Start-Process -FilePath $exe -ArgumentList "--check" -PassThru -WindowStyle Hidden
if (-not $proc.WaitForExit(30000)) {
  Stop-Process -Id $proc.Id -Force
  throw "check timeout"
}
Log "check exit $($proc.ExitCode)"
if ($proc.ExitCode -ne 0) { throw "check failed" }
Log "check frozen OCR"
$ocr = Start-Process -FilePath $py -ArgumentList @(('"{0}"' -f "$work\packaging\check_ocr.py"), ('"{0}"' -f $exe)) -PassThru -Wait -WindowStyle Hidden -RedirectStandardOutput "$work\ocr.stdout.log" -RedirectStandardError "$work\ocr.stderr.log"
Get-Content "$work\ocr.stdout.log", "$work\ocr.stderr.log" | Write-Output
if ($ocr.ExitCode -ne 0) { throw "frozen OCR check failed $($ocr.ExitCode)" }

$iscc = Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"
if (-not (Test-Path $iscc)) {
  $installer = Join-Path $env:TEMP "intext-probe\innosetup.exe"
  New-Item -ItemType Directory -Force -Path (Split-Path $installer) | Out-Null
  Log "download inno"
  Invoke-WebRequest -Uri "https://github.com/jrsoftware/issrc/releases/download/is-6_7_4/innosetup-6.7.4.exe" -OutFile $installer
  Log "install inno"
  Start-Process -FilePath $installer -ArgumentList "/VERYSILENT","/NORESTART",('"/DIR={0}"' -f (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6")) -Wait
}
if (-not (Test-Path $iscc)) { throw "iscc missing" }

$iss = Join-Path $work "packaging\installer.iss"
$setupDirectory = Join-Path $work "installer"
New-Item -ItemType Directory -Force -Path $setupDirectory | Out-Null
$setup = Join-Path $setupDirectory "Intext-Setup.exe"
Log "compile installer"
$compiler = Start-Process -FilePath $iscc -ArgumentList @("`"/O$setupDirectory`"", "`"$iss`"") -PassThru -Wait -WindowStyle Hidden -RedirectStandardOutput "$work\iscc.stdout.log" -RedirectStandardError "$work\iscc.stderr.log"
Log "iscc exit $($compiler.ExitCode)"
if ($compiler.ExitCode -ne 0) { throw "installer compilation failed $($compiler.ExitCode)" }
$icons = Start-Process -FilePath $py -ArgumentList @(('"{0}"' -f "$work\packaging\check_installer.py"), ('"{0}"' -f $exe), ('"{0}"' -f $setup)) -PassThru -Wait -WindowStyle Hidden -RedirectStandardOutput "$work\icons.stdout.log" -RedirectStandardError "$work\icons.stderr.log"
Get-Content "$work\icons.stdout.log", "$work\icons.stderr.log" | Write-Output
if ($icons.ExitCode -ne 0) { throw "installer icon verification failed $($icons.ExitCode)" }
Log "Defender scan installer"
& "$work\packaging\scan.ps1" -Path $setup -ReportPath "$work\defender-installer.json"
$verification = [ordered]@{
  GeneratedAt = (Get-Date).ToString("o")
  SHA256 = @(Get-FileHash -Algorithm SHA256 -LiteralPath $exe, $setup | Select-Object Path, Hash)
  ApplicationScan = Get-Content "$work\defender-app.json" -Raw | ConvertFrom-Json
  InstallerScan = Get-Content "$work\defender-installer.json" -Raw | ConvertFrom-Json
}
$verification | ConvertTo-Json -Depth 8 | Set-Content "$work\verification.json" -Encoding UTF8
Copy-Item -LiteralPath $setup -Destination "$downloads\Intext-Setup.exe" -Force
Copy-Item "$work\verification.json" "$downloads\Intext-Setup.verification.json" -Force
Get-Item "$downloads\Intext-Setup.exe" | Format-List FullName,Length,LastWriteTime | Out-String | ForEach-Object { Log $_ }
Log "done"
