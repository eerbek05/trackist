# TrackIST'i baslatir:  powershell -File baslat.ps1
# PostgreSQL + AirLabs poller + OpenSky pozisyon worker'i + web uygulamasi.
# Her bilesen kendi minimize penceresinde calisir; durdurmak icin: durdur.ps1

$root  = $PSScriptRoot
$pgbin = "C:\Program Files\PostgreSQL\16\bin"
$data  = "$env:LOCALAPPDATA\TrackIST\pgdata"

# 1) PostgreSQL
& "$pgbin\pg_ctl.exe" -D $data status *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "PostgreSQL baslatiliyor..."
    Start-Process -FilePath "$pgbin\pg_ctl.exe" `
        -ArgumentList "-D", "`"$data`"", "-l", "`"$env:LOCALAPPDATA\TrackIST\pg.log`"", "-w", "start" `
        -WindowStyle Hidden -Wait
} else {
    Write-Host "PostgreSQL zaten calisiyor."
}

# 2) Worker'lar + web (zaten calisiyorlarsa ikinci kopya acma)
$running = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match [regex]::Escape($root) }

function Start-IfMissing($script) {
    # Absolute script path: the command line must contain the project root so
    # both this duplicate check and durdur.ps1's filter can find the process.
    $full = Join-Path $root $script
    if ($running | Where-Object { $_.CommandLine -match [regex]::Escape($full) }) {
        Write-Host "$script zaten calisiyor."
    } else {
        Start-Process -FilePath "python" -ArgumentList "-u", "`"$full`"" `
            -WorkingDirectory $root -WindowStyle Minimized
        Write-Host "$script baslatildi."
    }
}

Start-IfMissing "workers\poller.py"
Start-IfMissing "workers\opensky_position.py"
Start-IfMissing "app.py"

Write-Host ""
Write-Host "TrackIST hazir -> http://localhost:5001  (ilk uydu verisi ~30 sn)"
