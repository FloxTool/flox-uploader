"""Tests Sprint D.23 v0.5.0 — Fix bug UI tree dossiers depliables.

Cible note Louis B2 : "dans la section 'Contenu du torrent' je n'arrive
pas a deplier les dossier qui se trouve dans le dossier. il y a des bug
d'affichage le bouton sembler reagire mais rien ne se deplis. j'ai
reussi a un moment mais impossible de le refermer."

Verification du fix : event delegation sur listEl avec closest() pour
gerer les clicks sur le caret/span enfants du bouton, + stopPropagation
pour eviter tout bubble parasite.

Note : c'est un fix JS frontend qu'on ne peut pas unit-tester sans
browser. On valide ici la presence des elements clefs dans le template
(structure HTML + JS handler avec event delegation).
"""
from __future__ import annotations

from pathlib import Path


def test_tree_uses_event_delegation():
    """Le handler de toggle doit utiliser event delegation (listEl listener
    + closest('.tu-tree-toggle')) au lieu de binding par bouton."""
    template = (
        Path(__file__).parent.parent
        / "src" / "flox_uploader" / "web" / "templates"
        / "package_detail.html"
    )
    content = template.read_text(encoding="utf-8")

    # On cherche le pattern event delegation avec closest()
    assert "listEl.addEventListener('click'" in content, (
        "Le tree torrent doit utiliser event delegation sur listEl, "
        "pas un addEventListener par bouton."
    )
    assert "closest('.tu-tree-toggle')" in content, (
        "Le handler doit utiliser closest() pour gerer les clicks sur "
        "les descendants du bouton (caret, span, svg)."
    )
    assert "e.stopPropagation()" in content, (
        "Le handler doit appeler stopPropagation pour eviter bubble parasite."
    )


def test_tree_caret_rotation_logic_preserved():
    """Le caret doit toujours rotate-90 quand le dossier s'ouvre."""
    template = (
        Path(__file__).parent.parent
        / "src" / "flox_uploader" / "web" / "templates"
        / "package_detail.html"
    )
    content = template.read_text(encoding="utf-8")
    # On verifie que le caret toggling rotate-90 est conserve
    assert "caret.classList.add('rotate-90')" in content
    assert "caret.classList.remove('rotate-90')" in content


def test_tree_aria_expanded_managed():
    """L'attribut aria-expanded doit etre tenu a jour pour accessibilite."""
    template = (
        Path(__file__).parent.parent
        / "src" / "flox_uploader" / "web" / "templates"
        / "package_detail.html"
    )
    content = template.read_text(encoding="utf-8")
    assert "btn.setAttribute('aria-expanded'" in content


def test_tree_old_buggy_per_button_binding_removed():
    """L'ancien binding par bouton (forEach + addEventListener) est retire
    car cause le bug d'imbrication."""
    template = (
        Path(__file__).parent.parent
        / "src" / "flox_uploader" / "web" / "templates"
        / "package_detail.html"
    )
    content = template.read_text(encoding="utf-8")
    # On ne doit PLUS avoir le pattern .forEach(btn => btn.addEventListener)
    # pour les tu-tree-toggle. (On l'aurait toujours pour d'autres usages
    # type .tu-section-toggle qui n'a pas ce bug.)
    # Pattern specifique : forEach + addEventListener APPELE sur les
    # querySelectorAll('.tu-tree-toggle')
    assert "listEl.querySelectorAll('.tu-tree-toggle').forEach" not in content, (
        "Pattern buggy retire : on utilise event delegation maintenant."
    )
