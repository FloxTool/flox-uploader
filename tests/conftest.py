"""Configuration pytest globale.

Force user-site-packages en tete du sys.path pour que les versions modernes
des dependances (jinja2 etc.) installees via `pip install --user` soient
chargees prioritairement par rapport a celles du systeme.
"""
import site
import sys

_user_site = site.getusersitepackages()
if _user_site in sys.path:
    sys.path.remove(_user_site)
sys.path.insert(0, _user_site)
