param(
    [Parameter(Mandatory = $true)][string[]]$Path,
    [Parameter(Mandatory = $true)][string]$ReportPath
)

$ErrorActionPreference = "Stop"
$status = Get-MpComputerStatus
if (-not $status.AntivirusEnabled -or -not $status.RealTimeProtectionEnabled) {
    throw "Defender antivirus and real-time protection must be enabled for release verification."
}
$mp = Get-ChildItem "$env:ProgramData\Microsoft\Windows Defender\Platform\*\MpCmdRun.exe" |
    Sort-Object FullName -Descending | Select-Object -First 1
$scanner = if ($mp) { $mp.FullName } else { "$env:ProgramFiles\Windows Defender\MpCmdRun.exe" }
$results = @()
foreach ($item in $Path) {
    $target = (Resolve-Path -LiteralPath $item).Path
    $stdout = [IO.Path]::GetTempFileName()
    $stderr = [IO.Path]::GetTempFileName()
    try {
        # Scan archives and ignore exclusions, retaining the evidence if detected.
        # This option changes only this scan's remediation, never protection settings.
        $process = Start-Process -FilePath $scanner -ArgumentList @(
            "-Scan", "-ScanType", "3", "-File", "`"$target`"", "-DisableRemediation"
        ) -PassThru -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr
        [void]$process.Handle
        if (-not $process.WaitForExit(120000)) {
            Stop-Process -Id $process.Id -Force
            throw "Defender scan timed out: $target"
        }
        $process.WaitForExit()
        $process.Refresh()
        $output = (Get-Content $stdout, $stderr -Raw) -join "`n"
        Write-Output $output
        $results += [ordered]@{ Path = $target; ExitCode = $process.ExitCode; Output = $output }
        $report = [ordered]@{
            ScannedAt = (Get-Date).ToString("o")
            AntivirusSignatureVersion = $status.AntivirusSignatureVersion
            AMEngineVersion = $status.AMEngineVersion
            AntivirusEnabled = $status.AntivirusEnabled
            RealTimeProtectionEnabled = $status.RealTimeProtectionEnabled
            Scans = $results
        }
        $report | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $ReportPath -Encoding UTF8
        if ($process.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $target)) {
            throw "Defender did not pass $target (exit $($process.ExitCode)). See $ReportPath"
        }
    } finally {
        Remove-Item -LiteralPath $stdout, $stderr -Force
    }
}
