# TrackIST canlı eval — tek komut: powershell -File evals\calistir.ps1
# 1) PostgreSQL çalışmıyorsa başlatır
# 2) Eval fixture'larını yükler (yereldeki flights tablosunu SİLER — sadece dev DB!)
# 3) 27 soruluk canlı eval'i koşar ve skor kartını basar

$pgbin = "C:\Program Files\PostgreSQL\16\bin"
$data  = "$env:LOCALAPPDATA\TrackIST\pgdata"

& "$pgbin\pg_ctl.exe" -D $data status *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "PostgreSQL baslatiliyor..."
    # Start-Process: pg_ctl'yi ayri proseste bekle — dogrudan cagirmak daemon'un
    # stdout'unu miras aldigi icin PowerShell'i sonsuza kadar bekletir
    Start-Process -FilePath "$pgbin\pg_ctl.exe" `
        -ArgumentList "-D", "`"$data`"", "-l", "`"$env:LOCALAPPDATA\TrackIST\pg.log`"", "-w", "start" `
        -WindowStyle Hidden -Wait
}

Set-Location "$PSScriptRoot\.."
python evals/run_evals.py --seed
python evals/run_evals.py --sleep 30
