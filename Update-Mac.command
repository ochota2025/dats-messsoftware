#!/bin/bash
# Holt die neueste Version der DATS-Messsoftware von GitHub und entpackt sie in diesen Ordner.
# Die installierte Python-Umgebung (.venv) bleibt erhalten.
# Alles steckt in einer Funktion: bash liest sie vollständig ein, bevor diese Datei beim Update ersetzt wird.
main() {
    cd "$(dirname "$0")" || return 1
    local url tmp src
    url=$(grep -Eo '^[[:space:]]*(https?|file)://[^[:space:]]+' update-quelle.txt 2>/dev/null | head -1 | tr -d '[:space:]')
    url=${url%/}; url=${url%.git}
    if [ -z "$url" ]; then
        echo "  In update-quelle.txt steht keine GitHub-Adresse."; return 1
    fi
    tmp=$(mktemp -d)
    echo
    echo "  Lade neueste Version von $url …"
    if curl -fsSL "$url/archive/refs/heads/main.zip" -o "$tmp/u.zip" && unzip -q "$tmp/u.zip" -d "$tmp/x" 2>/dev/null; then
        src=$(find "$tmp/x" -mindepth 1 -maxdepth 1 -type d | head -1)
        if cp -R "$src"/. ./; then
            rm -f .venv/datsmess-editable.flag
            echo; echo "  Update fertig. Jetzt Start-Mac.command doppelklicken."
        else
            echo "  Kopieren fehlgeschlagen."
        fi
    else
        echo; echo "  Update fehlgeschlagen – ist das Projekt auf GitHub öffentlich und die Adresse in update-quelle.txt richtig?"
    fi
    rm -rf "$tmp"
}
main "$@"; echo; read -r -p "  Enter zum Schließen …"; exit
