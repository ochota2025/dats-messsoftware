# Holt die neueste Version der DATS-Messsoftware von GitHub und entpackt sie in diesen Ordner.
# Die installierte Python-Umgebung (.venv) bleibt erhalten. (Nur ASCII - fuer Windows PowerShell 5.1.)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$tmp = Join-Path $env:TEMP ('datsmess-update-' + [guid]::NewGuid())
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
    Write-Host ' Update fertig. Jetzt Start-Windows.bat doppelklicken.' -ForegroundColor Green
    $code = 0
} catch {
    Write-Host ''
    Write-Host (' Update fehlgeschlagen: ' + $_.Exception.Message) -ForegroundColor Red
    $code = 1
} finally {
    Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
}
exit $code
