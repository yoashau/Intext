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
Get-ChildItem -Recurse $work -Directory -Filter __pycache__ | Remove-Item -Recurse -Force

Set-Location $work
Log "pyinstaller"
$build = Start-Process -FilePath $py -ArgumentList "-m", "PyInstaller", "--noconfirm", "--clean", "$work\packaging\intext.spec" -PassThru -Wait -WindowStyle Hidden -RedirectStandardOutput "$work\pyinstaller.stdout.log" -RedirectStandardError "$work\pyinstaller.stderr.log"
Get-Content "$work\pyinstaller.stderr.log" | Write-Output
if ($build.ExitCode -ne 0) { throw "pyinstaller failed $($build.ExitCode)" }
$exe = Join-Path $work "dist\Intext\Intext.exe"
if (-not (Test-Path $exe)) { throw "missing $exe" }
Log "exe ready $((Get-Item $exe).Length)"

Log "check"
$proc = Start-Process -FilePath $exe -ArgumentList "--check" -PassThru -WindowStyle Hidden
if (-not $proc.WaitForExit(30000)) {
  Stop-Process -Id $proc.Id -Force
  throw "check timeout"
}
Log "check exit $($proc.ExitCode)"
if ($proc.ExitCode -ne 0) { throw "check failed" }

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
Log "compile installer"
$compiler = Start-Process -FilePath $iscc -ArgumentList @("`"/O$downloads`"", "`"$iss`"") -PassThru -Wait -WindowStyle Hidden -RedirectStandardOutput "$work\iscc.stdout.log" -RedirectStandardError "$work\iscc.stderr.log"
Log "iscc exit $($compiler.ExitCode)"
if ($compiler.ExitCode -ne 0) { throw "installer compilation failed $($compiler.ExitCode)" }
$icons = Start-Process -FilePath $py -ArgumentList @("$work\packaging\check_installer.py", $exe, "$downloads\Intext-Setup.exe") -PassThru -Wait -WindowStyle Hidden -RedirectStandardOutput "$work\icons.stdout.log" -RedirectStandardError "$work\icons.stderr.log"
Get-Content "$work\icons.stdout.log", "$work\icons.stderr.log" | Write-Output
if ($icons.ExitCode -ne 0) { throw "installer icon verification failed $($icons.ExitCode)" }
Get-Item "$downloads\Intext-Setup.exe" | Format-List FullName,Length,LastWriteTime | Out-String | ForEach-Object { Log $_ }
Log "done"
