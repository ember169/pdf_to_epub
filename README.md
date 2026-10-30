# pdftoepub

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**[Français](#français)** · **[English](#english)**

---

## Français

**Transformez un PDF en vrai livre numérique (EPUB) qui s'adapte à tous les écrans. Gratuit, libre, et tout se passe
sur votre ordinateur.**

![Une page scannée du « Roman expérimental » de Zola devient un texte EPUB qui se recompose sur téléphone, en petite et en grande police](docs/images/pdf-vers-epub.jpg)

*À gauche, une page scannée (Zola, 1902). À droite, le même texte dans l'EPUB produit, sur un téléphone en petite puis
en grande police. Résultat brut, sans retouche : les petites erreurs de reconnaissance de texte restent visibles.*

Un PDF fige la page : sur une liseuse ou un téléphone, il faut zoomer et faire défiler. pdftoepub en extrait le texte et
la structure pour produire un EPUB **recomposable** : la taille de police, les marges et la mise en page suivent votre
appareil. Il fonctionne aussi bien sur des documents nés numériques (romans, articles, manuels) que sur des **livres
scannés**, grâce à la reconnaissance de texte (OCR) intégrée.

### Ce que fait pdftoepub

**Un livre bien structuré**
- Chapitres et table des matières : depuis le sommaire du PDF quand il existe, sinon depuis les titres, la table des
  matières imprimée (« Sommaire », « Table des matières », « Contents » : parties, chapitres numérotés, sections) ou la
  mise en page des débuts de chapitre sur les livres scannés.
- Ouvrages collectifs : chaque chapitre a son titre numéroté et ses auteurs en signature, les parties regroupent leurs
  chapitres.
- Une vraie couverture en tête du livre, et les métadonnées retrouvées : titre, auteurs ou directeurs d'ouvrage,
  éditeur, année, ISBN, langue.

**Un texte propre**
- En-têtes et pieds de page courants, numéros de page retirés ; mots coupés en fin de ligne recollés ; paragraphes
  recousus d'une page à l'autre.
- Notes de bas de page et notes de fin de chapitre reliées à leur appel, avec retour au texte.
- Numéros de page imprimés conservés dans le livre (liste des pages), pour pouvoir citer une page.
- Listes, tableaux, images et légendes, liens ; articles en deux colonnes remis dans l'ordre de lecture ; formules
  mathématiques (formules en deux dimensions en image avec leur texte, indices et exposants en texte).

**Des livres scannés lisibles**
- OCR intégré (Tesseract, français et anglais) pour les pages qui ne sont que des images ; les pages blanches et les
  images sans contenu sont écartées, les pages en blanc sur noir sont lues aussi.
- Corrections prudentes des erreurs de reconnaissance courantes : lettres espacées, mots collés (« danslavie » →
  « dans la vie », en français et en anglais), confusions classiques.

**Privé et sûr**
- Tout se passe sur votre ordinateur : aucun fichier n'est envoyé à un service extérieur.
- Les EPUB produits sont valides (vérifiés avec epubcheck) et sans DRM.

Trois façons de l'utiliser : une **application** (une page s'ouvre dans votre navigateur), un outil en **ligne de
commande**, ou un **serveur** à héberger vous-même (Docker).

### Pour commencer

1. **Téléchargez** le fichier correspondant à votre ordinateur depuis la
   [dernière version](https://github.com/ember169/pdf_to_epub/releases/latest) :

   | Système | Fichier | Taille | Minimum |
   |---|---|---|---|
   | Mac avec puce Apple (M1 et suivantes) | `pdftoepub-macos-arm64.dmg` | ≈ 40 Mo | macOS 12 Monterey |
   | Mac avec processeur Intel | `pdftoepub-macos-x86_64.dmg` | ≈ 42 Mo | macOS 12 Monterey |
   | Mac, ligne de commande seule | `pdftoepub-macos-arm64` / `pdftoepub-macos-x86_64` | ≈ 37 / 38 Mo | macOS 12 |
   | Windows | `pdftoepub-windows-x86_64.exe` | ≈ 88 Mo | Windows 64 bits (testé sous Wine uniquement) |
   | Linux (PC) | `pdftoepub-linux-x86_64` | ≈ 73 Mo | glibc 2.31 (Debian 11, Ubuntu 20.04 ou plus récent) |
   | Linux (ARM) | `pdftoepub-linux-arm64` | ≈ 72 Mo | idem |

   Chaque fichier inclut l'OCR ; rien d'autre à installer (ni Python, ni Tesseract). Les empreintes sont dans
   `SHA256SUMS`. Sur Mac, choisissez selon la puce ( menu → À propos de ce Mac).
2. **Mac :** ouvrez le `.dmg`, glissez `pdftoepub.app` dans Applications, puis double-cliquez dessus.
   **Windows :** double-cliquez sur le `.exe`.
3. Au premier lancement, le système prévient que l'application n'est pas signée : voir
   [Premier lancement](#premier-lancement-dune-version-non-signée) (une seule fois).
4. Votre navigateur s'ouvre : déposez vos PDF, cliquez **Convertir**, puis **Télécharger**. Pour arrêter, cliquez
   **Quitter** dans la page (l'application s'arrête aussi seule après 15 minutes sans utilisation).

<p align="center"><img src="docs/images/interface-fr.jpg" alt="La page de pdftoepub après la conversion de deux PDF, dont un scan lu par OCR, avec les boutons Télécharger et Aperçu" width="460"></p>

Ouvrez ensuite le fichier `.epub` dans votre application de lecture (Apple Livres, Calibre, Kobo, Thorium, la plupart
des liseuses ; pour Kindle, passez par « Envoyer vers Kindle », qui accepte les EPUB).

### Premier lancement d'une version non signée

Les versions publiées ne sont **pas signées** par un certificat Apple ou Microsoft (c'est payant chaque année) : le
système avertit une seule fois. Ensuite, l'application s'ouvre directement.

**macOS 15 Sequoia et plus récent** (l'ancien clic droit → Ouvrir ne fonctionne plus) :

1. Double-cliquez sur `pdftoepub.app`. macOS affiche *« pdftoepub » n'a pas été ouvert*. Cliquez **Terminé** (pas
   *Placer dans la corbeille*).
2. Ouvrez **Réglages Système → Confidentialité et sécurité**, descendez jusqu'à *Sécurité* : à côté de
   *« pdftoepub » a été bloqué…*, cliquez **Ouvrir quand même**, puis confirmez avec **Ouvrir quand même** et votre mot
   de passe ou Touch ID.
3. Désormais, un double-clic suffit.

**macOS 12 à 14 :** clic droit (ou Contrôle-clic) sur `pdftoepub.app` → **Ouvrir** → **Ouvrir**.

**Windows :** à l'écran *Windows a protégé votre ordinateur*, cliquez **Informations complémentaires**, puis
**Exécuter quand même**.

**Fichiers en ligne de commande** (`pdftoepub-macos-*`) : retirez une fois la quarantaine de téléchargement dans le
Terminal :
`xattr -d com.apple.quarantine pdftoepub-macos-arm64 && chmod +x pdftoepub-macos-arm64`
(pour l'application : `xattr -dr com.apple.quarantine /Applications/pdftoepub.app`).

Le premier lancement sur Mac décompresse environ 100 Mo dans `~/Library/Caches/pdftoepub/` (une quinzaine de
secondes, une seule fois) ; supprimez ce dossier pour désinstaller.

### Ligne de commande

Chaque fichier téléchargé est aussi un outil en ligne de commande (sur Mac, l'exécutable de l'application est
`/Applications/pdftoepub.app/Contents/MacOS/pdftoepub`) :

```bash
pdftoepub livre.pdf -o livre.epub
pdftoepub serve --open        # la page web sur http://127.0.0.1:8000
pdftoepub                     # sans argument : lance la page web et ouvre le navigateur
```

| Option | Par défaut | Rôle |
|---|---|---|
| `--title`, `--author` | retrouvés dans le PDF | Remplacer le titre ou l'auteur |
| `--language` | détectée | Code BCP 47, par exemple `fr` |
| `--ocr` | `auto` | `auto` (pages sans texte), `off`, `force` |
| `--ocr-langs` | `fra+eng` | Langues Tesseract |
| `--keep-headers-footers` | non | Garder les en-têtes, pieds de page et numéros de page |
| `--no-columns` | non | Désactiver l'ordre de lecture en colonnes |
| `--no-images` | non | Ne pas inclure les images (ni la couverture) |
| `--timeout`, `--max-mem`, `--max-pages` | aucune | Arrêter les conversions trop longues, trop gourmandes ou trop volumineuses |

`pdftoepub --help` les liste toutes ; la page web propose les mêmes choix sous *Options avancées*. Pour l'OCR, les
variables `TESSERACT_CMD` / `TESSDATA_PREFIX`, ou un dossier `tesseract/` à côté de l'exécutable, remplacent la copie
intégrée (par exemple pour ajouter des langues).

### Héberger sur un serveur (Docker)

```bash
docker compose -f deploy/docker-compose.yml up --build
```

Ouvrez <http://localhost:8000>. Le port est publié sur **127.0.0.1 uniquement** ; le conteneur tourne en lecture seule,
sans droits root, avec une limite mémoire, et supprime les fichiers après `JOB_TTL_HOURS`. Pour un accès public,
définissez `AUTH_TOKEN` et `ALLOWED_HOSTS` et placez un proxy TLS devant
([`deploy/Caddyfile.example`](deploy/Caddyfile.example)). Toutes les variables sont décrites dans
[`src/pdftoepub/web/README.md`](src/pdftoepub/web/README.md).

### Qualité

Mesurée sur un corpus de 18 PDF du domaine public ou sous licence libre (3 362 pages : romans en français et en
anglais, articles arXiv, un manuel de 1 185 pages, livres de mathématiques, livres scannés d'Internet Archive), et sur
un livre scanné réel de 420 pages ; méthode et résultats détaillés dans [`tests/corpus/REPORT.md`](tests/corpus/REPORT.md) :

- **98,3 %** des mots retrouvés (les en-têtes courants et numéros de page sont retirés volontairement) et un score
  d'ordre de lecture de **0,95** (suites de 6 mots dans le bon ordre).
- **0 erreur epubcheck** sur tous les livres, avec les deux moteurs de lecture PDF.
- Livres scannés : 7 chapitres et 13 sections sur 7 et 13 retrouvés dans *Le Roman expérimental* de Zola ; sur le livre
  de 420 pages, les 21 parties et chapitres de la table des matières imprimée, et 316 appels de note reliés à leur note.

### Limites

- L'analyse de mise en page est heuristique : les mises en page complexes (magazines, tableaux imbriqués, notes en
  marge) peuvent demander une retouche.
- Mathématiques : pas de MathML ; les formules en deux dimensions sont des images (avec leur texte comme description).
- Livres scannés : le texte garde une partie des erreurs de reconnaissance, et ce que la couche OCR d'un PDF a manqué
  (une note, une ligne) reste manquant. Les corrections de mots collés ne concernent que le français et l'anglais.
- Les figures vectorielles deviennent des images ; les PDF protégés par mot de passe sont refusés.

### Droits d'usage

**Le logiciel** est sous [licence MIT](LICENSE) : vous pouvez l'utiliser, le copier, le modifier et le redistribuer,
y compris dans un cadre commercial, à condition de conserver la notice de copyright et de licence. Il est fourni sans
garantie.

**Vos documents** restent les vôtres : pdftoepub ne revendique aucun droit sur ce que vous convertissez et n'envoie rien
nulle part. La conversion ne change rien au droit d'auteur du contenu : convertissez les documents que vous avez le
droit d'utiliser (achetés, sous licence libre, du domaine public, ou les vôtres). Les EPUB produits ne contiennent pas
de DRM.

**Composants inclus.** Les applications et l'image Docker embarquent des logiciels et des données de tiers, chacun sous
sa licence (la liste complète est dans `THIRD_PARTY_LICENSES`, fourni avec chaque binaire) :
- Python (PSF), pdfminer.six (MIT), pypdfium2 et PDFium (Apache-2.0 / BSD-3), Pillow (HPND) ;
- Tesseract (Apache-2.0), Leptonica (BSD-2), libpng, et les données `tessdata_fast` française et anglaise
  (Apache-2.0) ;
- les listes de fréquence de mots [wordfreq](https://github.com/rspeer/wordfreq) 3.2 (`large_fr`, `large_en`, non
  modifiées), qui servent à séparer les mots collés par l'OCR. Ces **données** sont sous **CC BY-SA 4.0** (le code de
  wordfreq est sous Apache-2.0) : si vous les redistribuez, gardez leur attribution (`pdftoepub/core/data/wordfreq/NOTICE.txt`),
  et partagez-les sous la même licence si vous les modifiez.

Un moteur de lecture PDF optionnel utilise [PyMuPDF](https://pymupdf.readthedocs.io/), sous **AGPL-3.0** : une
installation qui l'inclut (`pip install ".[pymupdf]"`) relève de l'AGPL. Les applications et l'image Docker ne
l'incluent pas.

### Participer

Toute aide est bienvenue : signaler un problème, proposer une amélioration, tester sur vos documents.

**Signaler un problème** : ouvrez une [issue](https://github.com/ember169/pdf_to_epub/issues) en indiquant votre
système, la version, la commande ou les options utilisées et ce que vous attendiez. Si possible, joignez un PDF qui peut
être partagé publiquement (domaine public, licence libre, ou un document à vous). **Ne joignez jamais un document
protégé par le droit d'auteur** : décrivez plutôt le problème (une capture d'une page suffit souvent).

**Contribuer du code**

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"                    # inclut PyMuPDF (AGPL) pour tester les deux moteurs
python -m pdftoepub.core.lexicon fetch     # listes de fréquence wordfreq (facultatif, CC BY-SA 4.0)
pytest -q tests src                        # toute la suite, une fois par moteur PDF
```

- L'OCR depuis les sources nécessite `tesseract` (`brew install tesseract tesseract-lang`,
  `apt install tesseract-ocr-fra`) ; les tests epubcheck nécessitent `java` (le jar est téléchargé et vérifié une
  fois).
- Les tests créent leurs PDF à la volée (reportlab) : ajoutez un test pour chaque correction ou fonctionnalité, avec un
  PDF synthétique (jamais de texte d'un livre protégé).
- Toute modification de la conversion se mesure sur le corpus de documents réels, avant et après :
  ```bash
  python tests/corpus/fetch.py                     # télécharge le corpus (domaine public / licences libres, sha256)
  python tests/corpus/evaluate.py --label avant    # sur la branche principale
  python tests/corpus/evaluate.py --label apres    # avec votre modification
  python tests/corpus/evaluate.py --compare avant apres
  ```
  Une modification ne doit faire régresser aucun document, et epubcheck doit rester à 0 erreur. Vous pouvez y ajouter
  vos propres livres en local, sans jamais les publier (`tests/.corpus/private/`, ignoré par git).
- Où se trouve quoi : la conversion dans [`src/pdftoepub/core/`](src/pdftoepub/core/README.md) (chaque étape y est
  décrite), l'interface web et le serveur dans [`src/pdftoepub/web/`](src/pdftoepub/web/README.md), la ligne de
  commande dans `src/pdftoepub/cli.py`, l'API publique dans `src/pdftoepub/api.py`, les applications dans `packaging/`
  et le serveur Docker dans `deploy/`. La publication des versions est décrite dans [`RELEASING.md`](RELEASING.md).

En proposant une contribution, vous acceptez qu'elle soit publiée sous la licence MIT du projet.

---

## English

**Turn a PDF into a real e-book (EPUB) that adapts to any screen. Free, open source, and everything happens on your own
computer.**

![A scanned page of An Island Plant becomes EPUB text that reflows on a phone at a small and a large font size](docs/images/pdf-to-epub.jpg)

*Left: a scanned page (An Island Plant, 1896). Right: the same text in the generated EPUB, on a phone at a small then a
large font size. Raw output, not retouched: small text-recognition mistakes are still visible.*

A PDF freezes the page: on an e-reader or a phone you zoom and scroll. pdftoepub extracts the text and its structure to
build a **reflowable** EPUB: font size, margins and layout follow your device. It works on born-digital documents
(novels, papers, textbooks) as well as on **scanned books**, with built-in text recognition (OCR).

### What pdftoepub does

**A well-structured book**
- Chapters and table of contents: from the PDF outline when there is one, otherwise from the headings, from the printed
  table of contents ("Contents", "Sommaire", "Table des matières": parts, numbered chapters, sections), or from the
  layout of chapter openings in scanned books.
- Edited volumes: each chapter gets its numbered title and its authors as a byline; parts hold their chapters.
- A real cover at the start of the book, and the metadata recovered: title, authors or editors, publisher, year, ISBN,
  language.

**Clean text**
- Running headers, footers and page numbers removed; words hyphenated at line ends rejoined; paragraphs stitched back
  together across pages.
- Footnotes and chapter endnotes linked to their reference, with a link back to the text.
- Printed page numbers kept in the book (a page list), so you can cite a page.
- Lists, tables, images and captions, links; two-column papers in reading order; mathematics (two-dimensional formulas
  as pictures with their text, subscripts and superscripts as text).

**Readable scanned books**
- Built-in OCR (Tesseract, English and French) for pages that are only pictures; blank pages and empty pictures are left
  out, and white-on-black pages are read too.
- Careful fixes for common recognition mistakes: letter-spaced words, words run together ("ofthe" → "of the", in English
  and French), classic character confusions.

**Private and safe**
- Everything happens on your computer: no file is sent to any external service.
- The EPUBs are valid (checked with epubcheck) and DRM-free.

Three ways to use it: an **app** (a page opens in your browser), a **command-line** tool, or a **server** you host
yourself (Docker).

### Getting started

1. **Download** the file for your computer from the
   [latest release](https://github.com/ember169/pdf_to_epub/releases/latest):

   | System | File | Size | Minimum |
   |---|---|---|---|
   | Mac with Apple silicon (M1 and later) | `pdftoepub-macos-arm64.dmg` | ≈ 40 MB | macOS 12 Monterey |
   | Mac with Intel processor | `pdftoepub-macos-x86_64.dmg` | ≈ 42 MB | macOS 12 Monterey |
   | Mac, command line only | `pdftoepub-macos-arm64` / `pdftoepub-macos-x86_64` | ≈ 37 / 38 MB | macOS 12 |
   | Windows | `pdftoepub-windows-x86_64.exe` | ≈ 88 MB | 64-bit Windows (tested under Wine only) |
   | Linux (PC) | `pdftoepub-linux-x86_64` | ≈ 73 MB | glibc 2.31 (Debian 11, Ubuntu 20.04 or newer) |
   | Linux (ARM) | `pdftoepub-linux-arm64` | ≈ 72 MB | same |

   Every file includes OCR; nothing else to install (no Python, no Tesseract). Checksums are in `SHA256SUMS`. On a Mac,
   pick by chip ( menu → About This Mac).
2. **Mac:** open the `.dmg`, drag `pdftoepub.app` to Applications, double-click it. **Windows:** double-click the
   `.exe`.
3. The first launch warns that the app is not signed: see [First launch](#first-launch-of-an-unsigned-build) (once
   only).
4. Your browser opens: drop your PDFs, click **Convert**, then **Download**. To stop it, click **Quit** in the page (it
   also stops by itself after 15 minutes without use).

<p align="center"><img src="docs/images/interface-en.jpg" alt="The pdftoepub page after converting two PDFs, one of them a scan read with OCR, with Download and Preview buttons" width="460"></p>

Then open the `.epub` file in your reading app (Apple Books, Calibre, Kobo, Thorium, most e-readers; for Kindle, use
"Send to Kindle", which accepts EPUB).

### First launch of an unsigned build

The builds are **not signed** with an Apple or Microsoft certificate (that costs a yearly fee), so the system warns
once. Afterwards the app opens normally.

**macOS 15 Sequoia and newer** (the old right-click → Open shortcut no longer works):

1. Double-click `pdftoepub.app`. macOS shows *"pdftoepub" Not Opened*. Click **Done** (not *Move to Trash*).
2. Open **System Settings → Privacy & Security**, scroll down to *Security*: next to *"pdftoepub" was blocked to protect
   your Mac* click **Open Anyway**, confirm with **Open Anyway** and your password or Touch ID.
3. From now on, double-click opens it directly.

**macOS 12–14:** right-click (or Control-click) `pdftoepub.app` → **Open** → **Open**.

**Windows:** SmartScreen shows *Windows protected your PC*. Click **More info**, then **Run anyway**.

**Command-line files** (`pdftoepub-macos-*`): clear the download quarantine once in Terminal:
`xattr -d com.apple.quarantine pdftoepub-macos-arm64 && chmod +x pdftoepub-macos-arm64`
(for the app: `xattr -dr com.apple.quarantine /Applications/pdftoepub.app`).

On a Mac the first launch unpacks about 100 MB into `~/Library/Caches/pdftoepub/` (about 15 s, once); delete that
folder to uninstall.

### Command line

Every download is also a command-line tool (on a Mac the app's executable is
`/Applications/pdftoepub.app/Contents/MacOS/pdftoepub`):

```bash
pdftoepub book.pdf -o book.epub
pdftoepub serve --open        # the web page on http://127.0.0.1:8000
pdftoepub                     # no arguments: starts the web page and opens the browser
```

| Option | Default | Meaning |
|---|---|---|
| `--title`, `--author` | recovered from the PDF | Override the title or author |
| `--language` | detected | BCP 47 code, e.g. `en` |
| `--ocr` | `auto` | `auto` (pages without text), `off`, `force` |
| `--ocr-langs` | `fra+eng` | Tesseract languages |
| `--keep-headers-footers` | off | Keep running headers/footers and page numbers |
| `--no-columns` | off | Disable multi-column reading order |
| `--no-images` | off | Leave images (and the cover) out |
| `--timeout`, `--max-mem`, `--max-pages` | none | Stop conversions that take too long, too much memory or too many pages |

`pdftoepub --help` lists them all; the web page offers the same choices under *Advanced options*. For OCR,
`TESSERACT_CMD` / `TESSDATA_PREFIX`, or a `tesseract/` folder next to the executable, override the bundled copy (for
example to add languages).

### Self-hosting (Docker)

```bash
docker compose -f deploy/docker-compose.yml up --build
```

Open <http://localhost:8000>. The port is published on **127.0.0.1 only**; the container runs read-only, as a non-root
user, with a memory limit, and deletes files after `JOB_TTL_HOURS`. For public access, set `AUTH_TOKEN` and
`ALLOWED_HOSTS` and put a TLS proxy in front ([`deploy/Caddyfile.example`](deploy/Caddyfile.example)). All variables
are listed in [`src/pdftoepub/web/README.md`](src/pdftoepub/web/README.md).

### Quality

Measured on a corpus of 18 public-domain or openly licensed PDFs (3,362 pages: novels in English and French, arXiv
papers, a 1,185-page textbook, math books, scanned Internet Archive books), and on a real 420-page scanned book; method
and detailed results in [`tests/corpus/REPORT.md`](tests/corpus/REPORT.md):

- **98.3 %** of the words found (running heads and page numbers are removed on purpose) and a reading-order score of
  **0.95** (6-word sequences in the right order).
- **0 epubcheck errors** on every book, with both PDF backends.
- Scanned books: 7 of 7 chapters and 13 of 13 sections found in Zola's *Le Roman expérimental*; in the 420-page book, all
  21 parts and chapters of the printed table of contents, and 316 note references linked to their note.

### Limits

- Layout analysis is heuristic: complex layouts (magazines, nested tables, marginal notes) may need touching up.
- Mathematics: no MathML; two-dimensional formulas are pictures (with their text as the description).
- Scanned books: the text keeps some recognition mistakes, and whatever a PDF's OCR layer missed (a note, a line) stays
  missing. Fixes for words run together cover English and French only.
- Vector figures become pictures; password-protected PDFs are rejected.

### Rights of use

**The software** is under the [MIT license](LICENSE): you may use, copy, modify and redistribute it, commercially too,
as long as you keep the copyright and license notice. It comes with no warranty.

**Your documents** stay yours: pdftoepub claims no right over what you convert and sends nothing anywhere. Converting
does not change the copyright of the content: convert documents you are entitled to use (bought, openly licensed, in the
public domain, or your own). The EPUBs it produces carry no DRM.

**Bundled components.** The apps and the Docker image include third-party software and data, each under its own
license (the full list is in `THIRD_PARTY_LICENSES`, shipped with every binary):
- Python (PSF), pdfminer.six (MIT), pypdfium2 and PDFium (Apache-2.0 / BSD-3), Pillow (HPND);
- Tesseract (Apache-2.0), Leptonica (BSD-2), libpng, and the English and French `tessdata_fast` data (Apache-2.0);
- the [wordfreq](https://github.com/rspeer/wordfreq) 3.2 word-frequency lists (`large_fr`, `large_en`, unmodified),
  used to split words that OCR ran together. This **data** is licensed **CC BY-SA 4.0** (wordfreq's code is Apache-2.0):
  if you redistribute it, keep its attribution (`pdftoepub/core/data/wordfreq/NOTICE.txt`), and share it under the same
  license if you modify it.

An optional PDF backend uses [PyMuPDF](https://pymupdf.readthedocs.io/), which is **AGPL-3.0**: an installation that
includes it (`pip install ".[pymupdf]"`) falls under the AGPL. The apps and the Docker image do not include it.

### Contributing

Help is welcome: report a problem, suggest an improvement, try it on your documents.

**Report a problem**: open an [issue](https://github.com/ember169/pdf_to_epub/issues) with your system, the version,
the command or options you used and what you expected. If you can, attach a PDF that can be shared publicly (public
domain, openly licensed, or your own document). **Never attach a copyrighted document**: describe the problem instead
(a screenshot of one page is often enough).

**Contribute code**

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"                    # includes PyMuPDF (AGPL) to test both backends
python -m pdftoepub.core.lexicon fetch     # wordfreq frequency lists (optional, CC BY-SA 4.0)
pytest -q tests src                        # the whole suite, once per PDF backend
```

- OCR from a source install needs `tesseract` (`brew install tesseract tesseract-lang`,
  `apt install tesseract-ocr-fra`); the epubcheck tests need `java` (the jar is downloaded and checked once).
- The tests build their PDFs on the fly (reportlab): add a test for every fix or feature, with a synthetic PDF (never
  text from a copyrighted book).
- Every change to the conversion is measured on the real-document corpus, before and after:
  ```bash
  python tests/corpus/fetch.py                     # downloads the corpus (public domain / open licenses, sha256)
  python tests/corpus/evaluate.py --label before   # on the main branch
  python tests/corpus/evaluate.py --label after    # with your change
  python tests/corpus/evaluate.py --compare before after
  ```
  A change must not make any document worse, and epubcheck must stay at 0 errors. You can add your own books locally,
  without ever publishing them (`tests/.corpus/private/`, ignored by git).
- Where things are: the conversion in [`src/pdftoepub/core/`](src/pdftoepub/core/README.md) (every step is described
  there), the web page and server in [`src/pdftoepub/web/`](src/pdftoepub/web/README.md), the command line in
  `src/pdftoepub/cli.py`, the public API in `src/pdftoepub/api.py`, the apps in `packaging/` and the Docker server in
  `deploy/`. Releasing is described in [`RELEASING.md`](RELEASING.md).

By contributing, you agree that your contribution is published under the project's MIT license.
