#!/bin/bash
# DATS-Messsoftware starten (macOS/Linux). Beim ersten Start wird alles Nötige installiert.
cd "$(dirname "$0")" || exit 1

if [ ! -x .venv/bin/python ]; then
    echo
    echo "  Erste Einrichtung – dauert einige Minuten (einmaliger Download der Programmbibliotheken) …"
    echo
    PY=""
    for c in python3.13 python3.12 python3.11 python3.10 python3; do
        if command -v "$c" >/dev/null 2>&1 && \
           "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
            PY="$c"; break
        fi
    done
    if [ -z "$PY" ]; then
        echo "  Python 3.10 oder neuer wurde nicht gefunden."
        echo "  Bitte installieren: https://www.python.org/downloads/"
        echo "  Danach diese Datei erneut doppelklicken."
        read -r -p "  Enter zum Schließen …"
        exit 1
    fi
    if ! { "$PY" -m venv .venv && .venv/bin/python -m pip install --upgrade pip \
           && .venv/bin/python -m pip install -e . ; }; then
        rm -rf .venv
        echo "  Die Einrichtung ist fehlgeschlagen."
        read -r -p "  Enter zum Schließen …"
        exit 1
    fi
    touch .venv/datsmess-editable.flag
fi

# Neue Version über den alten Ordner entpackt: einmalig neu einbinden (kein großer Download)
if [ ! -f .venv/datsmess-editable.flag ]; then
    echo "  Neue Version wird eingerichtet …"
    .venv/bin/python -m pip install -e . && touch .venv/datsmess-editable.flag
fi

exec .venv/bin/python -m datsmess
