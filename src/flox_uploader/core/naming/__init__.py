"""Sous-package naming : helpers, strategies par categorie, dispatcher.

Sprint B v0.5.0 (PLAN-MULTICAT §5.5) — extraction progressive du module
monolithique `release_name.py` vers une structure modulaire qui supporte
plusieurs categories (video, livres, jeux, logiciels) via Strategy pattern.

Sprint B.1 : `_helpers.py` (cette PR) — helpers mutualisables purs.
Sprint B.2 : `strategy.py` — Protocol NamingStrategy + dispatcher.
Sprint B.3 : `video_strategy.py` — VideoNamingStrategy qui wrap l'existant.
Sprint D / E / H : BookNamingStrategy, GameNamingStrategy, etc.
"""
from __future__ import annotations
