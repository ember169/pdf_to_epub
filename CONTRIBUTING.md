# Contribuer · Contributing

**[Français](#français)** · **[English](#english)**

---

## Français

### Signaler un problème

Ouvrez une [issue](https://github.com/ember169/pdf_to_epub/issues) avec votre système, la version, la commande ou les
options utilisées, et ce que vous attendiez. Joignez si possible un PDF partageable publiquement (domaine public,
licence libre, ou un document à vous). **Ne joignez jamais un document protégé par le droit d'auteur** : une capture
d'une page suffit souvent.

### Installer depuis les sources

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"                    # inclut PyMuPDF (AGPL) pour tester les deux moteurs
python -m pdftoepub.core.lexicon fetch     # listes wordfreq (facultatif, CC BY-SA 4.0)
pytest -q tests src
```

L'OCR depuis les sources demande `tesseract` (`brew install tesseract tesseract-lang`, `apt install tesseract-ocr-fra`) ;
les tests epubcheck demandent `java`.

### Règles

- Chaque correction ou fonctionnalité vient avec un test, sur un PDF synthétique généré par le test (jamais le texte d'un
  livre protégé).
- Toute modification de la conversion se mesure sur le corpus de documents réels, avant et après :
  ```bash
  python tests/corpus/fetch.py
  python tests/corpus/evaluate.py --label avant    # sur main
  python tests/corpus/evaluate.py --label apres    # avec votre modification
  python tests/corpus/evaluate.py --compare avant apres
  ```
  Aucun document ne doit régresser, et epubcheck doit rester à 0 erreur. Vos propres livres peuvent s'ajouter en local
  dans `tests/.corpus/private/` (ignoré par git).
- En proposant une contribution, vous acceptez qu'elle soit publiée sous la licence MIT du projet.

### Où se trouve quoi

| Dossier | Contenu |
|---|---|
| [`src/pdftoepub/core/`](src/pdftoepub/core/README.md) | La conversion, étape par étape |
| [`src/pdftoepub/web/`](src/pdftoepub/web/README.md) | L'interface web et le serveur |
| `src/pdftoepub/cli.py`, `src/pdftoepub/api.py` | La ligne de commande et l'API publique |
| `packaging/` | Les applications portables ([`RELEASING.md`](RELEASING.md)) |
| `deploy/` | Le serveur Docker |
| `tests/corpus/` | Le corpus d'évaluation et son [rapport](tests/corpus/REPORT.md) |

---

## English

### Report a problem

Open an [issue](https://github.com/ember169/pdf_to_epub/issues) with your system, the version, the command or options
you used, and what you expected. If you can, attach a PDF that can be shared publicly (public domain, openly licensed,
or your own). **Never attach a copyrighted document**: a screenshot of one page is often enough.

### Install from source

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"                    # includes PyMuPDF (AGPL) to test both backends
python -m pdftoepub.core.lexicon fetch     # wordfreq lists (optional, CC BY-SA 4.0)
pytest -q tests src
```

OCR from source needs `tesseract` (`brew install tesseract tesseract-lang`, `apt install tesseract-ocr-fra`); the
epubcheck tests need `java`.

### Rules

- Every fix or feature comes with a test, on a synthetic PDF the test builds (never text from a copyrighted book).
- Every change to the conversion is measured on the real-document corpus, before and after:
  ```bash
  python tests/corpus/fetch.py
  python tests/corpus/evaluate.py --label before   # on main
  python tests/corpus/evaluate.py --label after    # with your change
  python tests/corpus/evaluate.py --compare before after
  ```
  No document may get worse, and epubcheck must stay at 0 errors. You can add your own books locally in
  `tests/.corpus/private/` (ignored by git).
- By contributing, you agree that your contribution is published under the project's MIT license.

### Where things are

| Folder | Contents |
|---|---|
| [`src/pdftoepub/core/`](src/pdftoepub/core/README.md) | The conversion, step by step |
| [`src/pdftoepub/web/`](src/pdftoepub/web/README.md) | The web page and server |
| `src/pdftoepub/cli.py`, `src/pdftoepub/api.py` | The command line and the public API |
| `packaging/` | The portable apps ([`RELEASING.md`](RELEASING.md)) |
| `deploy/` | The Docker server |
| `tests/corpus/` | The evaluation corpus and its [report](tests/corpus/REPORT.md) |
