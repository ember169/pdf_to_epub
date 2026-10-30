# Publier une version · Releasing

Notes pour les mainteneurs (le [README](README.md) s'adresse aux utilisateurs et aux contributeurs). ·
Maintainer notes (the [README](README.md) is for users and contributors).

**[Français](#français)** · **[English](#english)**

---

## Français

### Build local, sans CI

Il n'y a pas de CI : tout est construit et testé sur un Mac (Docker pour Linux, Wine dans Docker pour Windows), puis
envoyé.

```bash
packaging/build.sh mac-arm64 mac-x86_64 linux-arm64 linux-x86_64 windows   # tous les binaires dans dist/
packaging/smoke.sh                       # teste chaque binaire en environnement vierge, réécrit dist/SHA256SUMS
packaging/release.sh v0.2.0              # simulation : vérifie dist/, écrit SHA256SUMS, affiche la commande gh
packaging/release.sh v0.2.0 --publish    # crée la version sur GitHub (nécessite `gh auth login`)
```

- macOS nécessite `uv`, cmake et les outils en ligne de commande Xcode. Lancez d'abord une fois
  `packaging/build_tesseract_macos.sh` : il compile Tesseract, Leptonica et libpng depuis des sources épinglées et
  vérifiées (sha256) pour les deux types de puce Mac (macOS 11 et plus).
- Le build Mac Intel tourne sous Rosetta et utilise `packaging/macos-x86_64.lock` ; les builds Mac épinglent
  pypdfium2 5.9.0 (le PDFium plus récent exige macOS 13). Le build échoue si un binaire exige un macOS plus récent que
  12.0 (mesuré par `packaging/audit_minos.sh`).
- Linux est construit sur Debian 11 dans Docker et testé dans des conteneurs vierges `debian:11-slim` et
  `ubuntu:20.04`. Windows est construit et testé sous Wine, jamais sur un vrai Windows ; `packaging/build.ps1` (build
  Windows natif) n'a jamais été lancé.
- Toutes les dépendances sont installées depuis des fichiers verrouillés avec empreintes (`requirements.lock`,
  `packaging/*.lock` ; `packaging/relock.sh` les régénère). Les binaires ne contiennent pas PyMuPDF (le build échoue
  s'il est présent).
- Les listes de fréquence wordfreq (données CC BY-SA 4.0) sont téléchargées par
  `python -m pdftoepub.core.lexicon fetch` (versions épinglées, sha256 vérifié) avant le build ; leur notice est
  ajoutée à `THIRD_PARTY_LICENSES`.

### Signature (prête, pas encore utilisée)

Les versions actuelles ont une signature locale (ad hoc). Les scripts de vraie signature sont prêts et ont été validés
de bout en bout avec des certificats auto-signés jetables ; il ne leur manque que les certificats.

| | Ce qui supprime l'avertissement | Script |
|---|---|---|
| macOS | Certificat **Developer ID Application** (Apple Developer Program, 99 USD/an) + notarisation | `packaging/sign_macos.sh` (appelé par `build.sh` ; runtime renforcé, horodatage, notarisation, agrafage) |
| Windows | Certificat **Authenticode** (OV environ 100 à 300 USD/an ; EV ou Azure Trusted Signing possibles) | `packaging/sign_windows.sh` (osslsigncode, horodatage RFC 3161) |

```bash
xcrun notarytool store-credentials pdftoepub-notary --apple-id vous@example.com --team-id TEAMID   # une fois
APPLE_SIGN_IDENTITY="Developer ID Application: Votre Nom (TEAMID)" APPLE_NOTARY_PROFILE=pdftoepub-notary \
  packaging/build.sh mac-arm64 mac-x86_64
WIN_SIGN_PFX=~/certs/codesign.pfx WIN_SIGN_PASSWORD=... packaging/sign_windows.sh
```

Vérifié avec des certificats auto-signés : macOS `codesign --verify --deep --strict` OK, l'application et l'outil en
ligne de commande signés fonctionnent, OCR compris, sans exception de droits ; Windows `osslsigncode verify` OK et le
`.exe` signé fonctionne sous Wine. La notarisation nécessite des identifiants Apple et n'a pas été testée.

### Site web (prévu)

Un site GitHub Pages est prévu à l'adresse <https://ember169.github.io/pdf_to_epub/> : présentation, tableau de
téléchargement, captures d'écran et FAQ sur l'ouverture des applications non signées. Ses sources seront dans `docs/`
(qui contient déjà les illustrations ; la page `index.html` n'existe pas encore) et publiées avec le réglage Pages
« Deploy from a branch » (branche `main`, dossier `/docs`, le seul sous-dossier que ce réglage peut servir), sans
GitHub Actions.

---

## English

### Built locally, no CI

There is no CI: everything is built and tested on a Mac (Docker for Linux, Wine in Docker for Windows), then uploaded.

```bash
packaging/build.sh mac-arm64 mac-x86_64 linux-arm64 linux-x86_64 windows   # all binaries into dist/
packaging/smoke.sh                       # tests every binary in clean environments, rewrites dist/SHA256SUMS
packaging/release.sh v0.2.0              # dry run: checks dist/, writes SHA256SUMS, prints the gh command
packaging/release.sh v0.2.0 --publish    # creates the GitHub release (needs `gh auth login`)
```

- macOS needs `uv`, cmake and the Xcode command line tools. Run `packaging/build_tesseract_macos.sh` once first: it
  builds Tesseract, Leptonica and libpng from pinned, sha256-checked sources for both Mac chips (macOS 11 and newer).
- The Intel Mac build runs under Rosetta and uses `packaging/macos-x86_64.lock`; Mac builds pin pypdfium2 5.9.0
  (newer PDFium needs macOS 13). The build fails if any binary needs a newer macOS than 12.0 (measured by
  `packaging/audit_minos.sh`).
- Linux is built on Debian 11 in Docker and tested in clean `debian:11-slim` and `ubuntu:20.04` containers. Windows is
  built and tested under Wine, never on real Windows; `packaging/build.ps1` (native Windows build) has never been run.
- Every dependency is installed from hash-pinned lock files (`requirements.lock`, `packaging/*.lock`;
  `packaging/relock.sh` regenerates them). The binaries contain no PyMuPDF (the build fails if it is present).
- The wordfreq frequency lists (CC BY-SA 4.0 data) are downloaded by `python -m pdftoepub.core.lexicon fetch` (pinned,
  sha256-checked) before the build; their notice goes into `THIRD_PARTY_LICENSES`.

### Signing (ready, not used yet)

The current builds are ad-hoc signed. The scripts for real signatures are ready and were proven end to end with
throw-away self-signed certificates; they only need the certificates.

| | What removes the warning | Script |
|---|---|---|
| macOS | **Developer ID Application** certificate (Apple Developer Program, 99 USD/year) + notarization | `packaging/sign_macos.sh` (called by `build.sh`; hardened runtime, timestamp, notarize, staple) |
| Windows | **Authenticode** certificate (OV about 100–300 USD/year; EV or Azure Trusted Signing also possible) | `packaging/sign_windows.sh` (osslsigncode, RFC 3161 timestamp) |

```bash
xcrun notarytool store-credentials pdftoepub-notary --apple-id you@example.com --team-id TEAMID   # once
APPLE_SIGN_IDENTITY="Developer ID Application: Your Name (TEAMID)" APPLE_NOTARY_PROFILE=pdftoepub-notary \
  packaging/build.sh mac-arm64 mac-x86_64
WIN_SIGN_PFX=~/certs/codesign.pfx WIN_SIGN_PASSWORD=... packaging/sign_windows.sh
```

Verified with self-signed certificates: macOS `codesign --verify --deep --strict` OK, the signed app and command-line
tool run, OCR included, with no entitlement exceptions; Windows `osslsigncode verify` OK and the signed `.exe` runs
under Wine. Notarization needs Apple credentials and is untested.

### Website (planned)

A GitHub Pages site is planned at <https://ember169.github.io/pdf_to_epub/>: presentation, the download table,
screenshots and a FAQ on opening unsigned apps. Its sources will live in `docs/` (which already holds the
illustrations; the `index.html` page does not exist yet) and be published with the Pages "Deploy from a branch" setting
(branch `main`, folder `/docs`, the only sub-folder that setting can serve), with no GitHub Actions.
