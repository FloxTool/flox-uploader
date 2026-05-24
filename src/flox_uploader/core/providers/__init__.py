"""Sous-package providers : sources de metadonnees externes par categorie.

Sprint D v0.5.0 (PLAN-MULTICAT §7) — moteur de recuperation de metadonnees
pour les categories non-video. Chaque provider implemente une interface
commune pour son univers (livre, jeu, emission TV, sport, formation).

Sprint D (cette PR) :
- `book_metadata.py` : dataclass BookMetadata (titre, auteur, ISBN, etc.)
- `epub_metadata.py` : extracteur metadata.opf depuis un .epub local
- `bnf.py` : client BnF SRU (Sprint D.2)
- `google_books.py` : client Google Books API (Sprint D.2)
- `openlibrary.py` : client OpenLibrary fallback (Sprint D.2)

Sprint E : igdb.py, steam_store.py, rawg.py
Sprint F : tvmaze.py, wikidata_sparql.py
Sprint G : thesportsdb.py
Sprint H : github_repo.py, youtube_playlist.py, virustotal.py

Aucun provider ne plante en cas d'erreur reseau / API. Le pipeline degrade
gracieusement (la dataclass est partielle, le score baisse, l'user complete
manuellement).
"""
from __future__ import annotations
