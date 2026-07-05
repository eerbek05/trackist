# TrackIST'i durdurur:  powershell -File durdur.ps1
# Poller, OpenSky worker'i ve web uygulamasini kapatir.
# PostgreSQL'e dokunmaz (zararsizdir); onu da kapatmak icin -Db ekleyin.
param([switch]$Db)

$root = $PSScriptRoot

$procs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match [regex]::Escape($root) }

if ($procs) {
    $procs | ForEach-Object {
        Write-Host "Durduruluyor: PID $($_.ProcessId)"
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
} else {
    Write-Host "Calisan TrackIST sureci yok."
}

if ($Db) {
    & "C:\Program Files\PostgreSQL\16\bin\pg_ctl.exe" -D "$env:LOCALAPPDATA\TrackIST\pgdata" -w stop
    Write-Host "PostgreSQL durduruldu."
}
