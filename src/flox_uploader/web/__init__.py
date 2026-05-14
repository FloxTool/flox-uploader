"""Interface web locale pour flox-uploader.

Stack : FastAPI + Jinja2 + Tailwind (via CDN). Persistance : on garde
`package_state.json` comme source de verite, SQLite ne sert qu'au log/historique.

Lancement : `flox-uploader serve` (defaut : http://127.0.0.1:8765/).

Architecture :
- `app.py` : FastAPI app, routes, dependances
- `templates/` : Jinja2 (base layout + pages)
- `static/` : assets (vide pour l'instant, Tailwind via CDN)
"""
