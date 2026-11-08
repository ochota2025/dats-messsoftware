# Anleitung: Projekt auf GitHub pflegen und Updates ausliefern

Für den Entwicklungs-Mac. Projekt: **https://github.com/ochota2025/dats-messsoftware** (öffentlich).

Auf diesem Mac ist die GitHub-Kommandozeile `gh` schon installiert und als `ochota2025`
angemeldet. Token und Passwortabfragen entfallen deshalb.

---

## Teil A – einmalige Einrichtung

Am einfachsten im Chat sagen: *„Richte das GitHub-Repository ein und lade alles hoch.“*
Claude führt dann die folgenden Schritte aus. Wer es selbst machen will, gibt im **Terminal**
(Programme → Dienstprogramme) ein:

### 1. Git sagen, wer du bist (nur für dieses Projekt)

```bash
cd ~/Claude/dats-messsoftware
git init -b main
git config user.name "ochota2025"
git config user.email "353366095+ochota2025@users.noreply.github.com"
```

Die `noreply`-Adresse sorgt dafür, dass keine private E-Mail-Adresse öffentlich in der
Versionsgeschichte erscheint.

### 2. Erste Version festhalten und hochladen

```bash
git add .
git commit -m "Erste Version der DATS-Messsoftware"
gh repo create ochota2025/dats-messsoftware --public --source=. --push \
  --description "Impedanz-, T/S- und LCR-Messsoftware für das Dayton Audio DATS V3"
```

Kontrolle: Auf <https://github.com/ochota2025/dats-messsoftware> erscheinen die Dateien und
darunter die README.

### 3. Freunden/Nutzern Bescheid geben

Link zur Projektseite schicken und auf `ANLEITUNG-Benutzer.md` hinweisen (auf GitHub
anklicken, dann wird sie schön dargestellt). Ab dann keine ZIPs mehr per Messenger.

Wer die Software schon per ZIP installiert hat, löscht den alten Ordner und installiert einmal
neu von GitHub (Anleitung, Schritt 2). Die alte ZIP-Version kennt die Update-Dateien noch nicht.

---

## Teil B – Routine: ein Update ausliefern

Nachdem Claude (oder du) etwas geändert hat:

**Variante 1 – Claude macht es:** im Chat *„Committe und pushe die Änderungen“*.

**Variante 2 – selbst im Terminal:**

```bash
cd ~/Claude/dats-messsoftware
.venv/bin/python -m pytest -q   # Tests müssen grün sein
git status                      # was hat sich geändert?
git add .
git commit -m "Kurz beschreiben, was neu ist"
git push
```

Dann kurz Bescheid geben: *„Neues Update – Update-Windows.bat bzw. Update-Mac.command
doppelklicken.“* Die Update-Datei holt immer den neuesten Stand des Zweigs `main`.

---

## Teil C – praktisch zu wissen

| Was | Wie |
|---|---|
| Versionsgeschichte ansehen | GitHub → **Commits** (Uhr-Symbol über der Dateiliste), oder `git log --oneline` |
| Eine Änderung rückgängig machen | `git revert <commit-nummer>` und `git push` – oder Claude bitten |
| Rückmeldungen sammeln | GitHub → **Issues**. Nutzer mit GitHub-Konto können dort Fehler und Wünsche eintragen, Fotos per Drag & Drop |
| Jemanden mitentwickeln lassen | **Settings → Collaborators → Add people** |
| Feste Versionen markieren (optional) | `gh release create v0.2 --generate-notes` – erscheint unter **Releases** |
| Projekt doch privat schalten | **Settings → General → Danger Zone → Change visibility**. Achtung: Dann funktionieren die Update-Dateien bei Nutzern ohne Zugang nicht mehr |

## Teil D – wenn etwas nicht klappt

- **`gh: not logged in`:** `gh auth login` ausführen und den Anweisungen folgen (Browser-Anmeldung).
- **`git push` → „rejected … fetch first“:** Auf GitHub wurde direkt etwas geändert
  (z. B. eine Datei im Browser bearbeitet). `git pull --rebase`, dann erneut `git push`.
- **„remote origin already exists“:** Das Repository ist schon verknüpft – einfach `git push`.
- **Update eines Nutzers meldet „keine ZIP-Datei“:** Projekt ist privat, oder die Adresse in
  `update-quelle.txt` stimmt nicht.

## Was wird hochgeladen, was nicht?

Hochgeladen: Quellcode, Tests, Anleitungen, Start- und Update-Dateien.
**Nicht** hochgeladen (siehe `.gitignore`): Python-Umgebung `.venv`, Zwischendateien, ZIP-Dateien.
Messprojekte (`.datsproj`) gehören nicht in den Projektordner – sie würden sonst öffentlich.
