# Holt die neueste Version der DATS-Messsoftware von GitHub und entpackt sie in diesen Ordner.
# Die installierte Python-Umgebung (.venv) bleibt erhalten. Nach erfolgreichem Update wird das
# Programm automatisch neu gestartet. (Nur ASCII - fuer Windows PowerShell 5.1.)
#
# -FromApp: aus dem Programm heraus aufgerufen ("Jetzt aktualisieren"). Dann wird das Programm
#           auch nach einem fehlgeschlagenen Update wieder gestartet (in der bisherigen Version).
param([switch]$FromApp)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$start = Join-Path $root 'Start-Windows.bat'
$tmp = Join-Path $env:TEMP ('datsmess-update-' + [guid]::NewGuid())

function Get-RunningApp {
    try {
        return @(Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" |
                 Where-Object { $_.CommandLine -and $_.CommandLine -match 'datsmess' })
    } catch {
        return @()
    }
}

function Start-App {
    if (Test-Path $start) {
        Start-Process -FilePath $start -WorkingDirectory $root
    }
}

# Laeuft das Programm noch? Dann erst schliessen lassen (max. 2 Minuten warten).
$waited = 0
while ((Get-RunningApp).Count -gt 0 -and $waited -lt 120) {
    if ($waited -eq 0) {
        Write-Host ''
        Write-Host ' Die DATS-Messsoftware ist noch geoeffnet - bitte schliessen, das Update wartet ...' -ForegroundColor Yellow
    }
    Start-Sleep -Seconds 1
    $waited++
}

try {
    $cfg = Join-Path $root 'update-quelle.txt'
    $line = Get-Content $cfg | Where-Object { $_ -match '^\s*https?://' } | Select-Object -First 1
    if (-not $line) { throw 'In update-quelle.txt steht keine GitHub-Adresse.' }
    $url = $line.Trim().TrimEnd('/')
    if ($url.EndsWith('.git')) { $url = $url.Substring(0, $url.Length - 4) }
    $zipUrl = "$url/archive/refs/heads/main.zip"

    Write-Host ''
    Write-Host " Lade neueste Version von $url ..."
    New-Item -ItemType Directory $tmp | Out-Null
    $zip = Join-Path $tmp 'update.zip'
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $zipUrl -OutFile $zip -UseBasicParsing
    try {
        Expand-Archive -Path $zip -DestinationPath (Join-Path $tmp 'x') -Force
    } catch {
        throw 'Der Download ist keine ZIP-Datei. Ist das Projekt auf GitHub oeffentlich und die Adresse richtig?'
    }
    $src = Get-ChildItem (Join-Path $tmp 'x') -Directory | Select-Object -First 1
    robocopy $src.FullName $root /E /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "Kopieren fehlgeschlagen (robocopy $LASTEXITCODE)." }
    Remove-Item (Join-Path $root '.venv\datsmess-editable.flag') -ErrorAction SilentlyContinue
    Write-Host ''
    Write-Host ' Update fertig. Das Programm wird gestartet ...' -ForegroundColor Green
    $code = 0
} catch {
    Write-Host ''
    Write-Host (' Update fehlgeschlagen: ' + $_.Exception.Message) -ForegroundColor Red
    $code = 1
} finally {
    Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
}

if ($code -eq 0) {
    Start-Sleep -Seconds 2
    Start-App
} elseif ($FromApp) {
    Write-Host ''
    Read-Host ' Enter druecken - das Programm startet in der bisherigen Version' | Out-Null
    Start-App
}
exit $code
