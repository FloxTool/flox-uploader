"""Sous-package confidence_strategies : Protocol + 6 strategies par profil.

Sprint C.5 v0.5.0 (PLAN-MULTICAT §5.4 Brique 3) — extraction progressive du
moteur de score `compute_confidence_score` vers une structure modulaire qui
supporte plusieurs profils via Strategy pattern (similaire a NamingStrategy
Sprint B).

Sprint C.5 (cette PR) :
- `strategy.py` : Protocol ConfidenceStrategy + dispatcher
- `video.py` : VideoConfidenceStrategy qui WRAP `compute_confidence_score`
- `book.py / game.py / show.py / sport.py / manual.py` : stubs minimaux

Sprint D / E / F / G / H : enrichiront les 5 stubs avec leurs penalites
specifiques (ex: book.py penalisera auteur absent, ISBN manquant, etc.).
"""
from __future__ import annotations
