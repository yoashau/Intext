$ErrorActionPreference = "Stop"
$py = "C:\Users\lycoris\AppData\Local\Programs\Python\Python313\python.exe"
$work = "C:\Users\lycoris\AppData\Local\Temp\intext-src"
$log = "C:\Users\lycoris\AppData\Local\Temp\intext-probe\build.log"
$downloads = "C:\Users\lycoris\Downloads"
New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null
function Log($m) { $line = "$(Get-Date -Format o) $m"; Add-Content -Path $log -Value $line; Write-Output $line }

Log "copy source"
if (Test-Path $work) { Remove-Item -Recurse -Force $work }
New-Item -ItemType Directory -Force -Path $work | Out-Null
$origin = "\\wsl.localhost\Ubuntu-24.04\home\lycoris\work\Intext"
Copy-Item -Recurse "$origin\src" "$work\src"
Copy-Item -Recurse "$origin\packaging" "$work\packaging"
Copy-Item "$origin\pyproject.toml" "$work\pyproject.toml"
Get-ChildItem -Recurse $work -Directory -Filter __pycache__ | Remove-Item -Recurse -Force

Set-Location $work
Log "install application dependencies"
$deps = Start-Process -FilePath $py -ArgumentList @("-m", "pip", "install", ".[windows]") -PassThru -Wait -WindowStyle Hidden -RedirectStandardOutput "$work\dependencies.stdout.log" -RedirectStandardError "$work\dependencies.stderr.log"
if ($deps.ExitCode -ne 0) {
  Get-Content "$work\dependencies.stdout.log", "$work\dependencies.stderr.log" | Write-Output
  throw "application dependency installation failed $($deps.ExitCode)"
}
Log "pyinstaller"
$models = Start-Process -FilePath $py -ArgumentList @("$work\packaging\prepare_ocr.py") -PassThru -Wait -WindowStyle Hidden -RedirectStandardOutput "$work\ocr-models.stdout.log" -RedirectStandardError "$work\ocr-models.stderr.log"
if ($models.ExitCode -ne 0) {
  Get-Content "$work\ocr-models.stdout.log", "$work\ocr-models.stderr.log" | Write-Output
  throw "OCR model verification failed $($models.ExitCode)"
}
$build = Start-Process -FilePath $py -ArgumentList "-m", "PyInstaller", "--noconfirm", "--clean", "$work\packaging\intext.spec" -PassThru -Wait -WindowStyle Hidden -RedirectStandardOutput "$work\pyinstaller.stdout.log" -RedirectStandardError "$work\pyinstaller.stderr.log"
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
$ocr = Start-Process -FilePath $py -ArgumentList @("$work\packaging\check_ocr.py", $exe) -PassThru -Wait -WindowStyle Hidden -RedirectStandardOutput "$work\ocr.stdout.log" -RedirectStandardError "$work\ocr.stderr.log"
Get-Content "$work\ocr.stdout.log", "$work\ocr.stderr.log" | Write-Output
if ($ocr.ExitCode -ne 0) { throw "frozen OCR check failed $($ocr.ExitCode)" }

$iscc = "C:\Users\lycoris\AppData\Local\Programs\Inno Setup 6\ISCC.exe"
if (-not (Test-Path $iscc)) {
  $installer = "C:\Users\lycoris\AppData\Local\Temp\intext-probe\innosetup.exe"
  Log "download inno"
  Invoke-WebRequest -Uri "https://github.com/jrsoftware/issrc/releases/download/is-6_7_4/innosetup-6.7.4.exe" -OutFile $installer
  Log "install inno"
  Start-Process -FilePath $installer -ArgumentList "/VERYSILENT","/NORESTART","/DIR=C:\Users\lycoris\AppData\Local\Programs\Inno Setup 6" -Wait
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
$icons = Start-Process -FilePath $py -ArgumentList @("$work\packaging\check_installer.py", $exe, $setup) -PassThru -Wait -WindowStyle Hidden -RedirectStandardOutput "$work\icons.stdout.log" -RedirectStandardError "$work\icons.stderr.log"
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
