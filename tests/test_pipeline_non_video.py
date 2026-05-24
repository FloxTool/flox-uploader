"""Tests Sprint A v0.5.0 PR-3 : pipeline.process_one ne plante plus sur les
fichiers non-video. C'est le DoD principal de Sprint A.

Avant : un .epub / .exe / .iso jeu dans process_one levait une exception
non-geree sur detect_media_type ('Aucun fichier video trouve') ou plus loin
sur parse_mediainfo_json (subprocess MediaInfo qui echoue).

Apres : early-return propre via die() avec message clair pour l'user.

Cf. PLAN-MULTICAT.md §5.2 Brique 1 + §9 Sprint A.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from flox_uploader import pipeline
from flox_uploader.trackers.gemini.unit3d_mapping import (
    CATEGORY_BOOKS, CATEGORY_GAME, CATEGORY_MOVIE, CATEGORY_SOFTWARE,
    CATEGORY_TRAINING,
)


# ============================================================
# Helper : process_one minimal avec env mockee
# ============================================================

@pytest.fixture
def mock_env(monkeypatch):
    """Mock les variables d'env critiques pour eviter SystemExit prematuré.

    `process_one` appelle `config.get_required_env("TRACKER_ANNOUNCE")` au
    debut, qui lèverait via die() si absent. On lui donne une valeur factice.
    """
    monkeypatch.setenv("TRACKER_ANNOUNCE", "https://test.tracker/announce/passkey")
    monkeypatch.setenv("TMDB_API_KEY", "test_tmdb")
    monkeypatch.setenv("OMDB_API_KEY", "test_omdb")
    yield


# ============================================================
# Cas non-video : die() proprement
# ============================================================

def _make_fake_file(tmp_path: Path, filename: str) -> Path:
    """Cree un fichier vide avec le nom donne."""
    p = tmp_path / filename
    p.write_bytes(b"")
    return p


@pytest.mark.parametrize("filename,expected_keyword", [
    ("Setup.exe", "Logiciel"),
    ("Installer.msi", "Logiciel"),
])
def test_process_one_unsupported_non_video_dies_with_clear_message(
    tmp_path, mock_env, capsys, filename, expected_keyword,
):
    """Sprint D.4 : seuls les Logiciels (et Formations, Jeux) declenchent
    encore die(). Les Livres ont leur propre pipeline (_process_book) et ne
    meurent plus."""
    fake = _make_fake_file(tmp_path, filename)

    with pytest.raises(SystemExit) as exc_info:
        pipeline.process_one(fake, tracker_key="gemini")

    assert exc_info.value.code == 1, "die() doit exit avec code 1"

    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert expected_keyword in output, (
        f"Message d'erreur attendu contient '{expected_keyword}', obtenu : {output}"
    )
    # Le message doit pointer vers la roadmap restante (sprints E ou H)
    assert ("v0.5.0" in output or "PLAN-MULTICAT" in output or "Sprints" in output
            or "sprints" in output), (
        f"Message doit indiquer que la cat sera supportee plus tard : {output}"
    )


@pytest.mark.parametrize("filename", [
    "Tolkien.epub", "Document.pdf", "Manga.cbz", "Audiobook.m4b",
])
def test_process_one_book_no_longer_dies(
    tmp_path, mock_env, capsys, filename, monkeypatch,
):
    """Sprint D.4 : les livres ne meurent plus, ils passent dans _process_book.

    Le pipeline va probablement planter plus loin sur le .torrent (fichier
    vide -> torf.PathError) ou sur l'absence de providers reels — mais on
    verifie qu'on ne meurt PAS sur la Brique 1 avec le message "pas encore
    supportee".
    """
    fake = _make_fake_file(tmp_path, filename)

    # Court-circuite create_torrent pour eviter le PathError torf sur fichier vide
    def fake_create_torrent(*args, **kwargs):
        # Cree un .torrent placeholder
        output = args[1] if len(args) > 1 else kwargs.get("output_torrent")
        if output:
            Path(output).write_bytes(b"d4:test4:datae")

    monkeypatch.setattr(pipeline, "create_torrent", fake_create_torrent)
    # Court-circuite l'orchestrateur lookup (qui ferait des appels HTTP reels)
    from flox_uploader.core.naming import book_strategy as _bs

    def no_lookup(meta):
        return meta

    monkeypatch.setattr(_bs, "lookup_book_metadata", lambda m, **kw: m)

    try:
        result = pipeline.process_one(fake, tracker_key="gemini")
        # Si on arrive ici, c'est que _process_book a tourne sans planter.
        assert result is not None
        assert result.is_dir()
    except BaseException as e:
        # On accepte les erreurs DEROULEMENT (ex: pas de TRACKER_API_URL, etc.)
        # mais on refuse une SystemExit avec message Brique 1.
        captured = capsys.readouterr()
        output = captured.out + captured.err
        assert "pas encore supportee" not in output, (
            f"La Brique 1 ne doit PLUS die() sur un livre. Message inattendu : {output}"
        )


def test_process_one_unknown_extension_falls_back_to_movie(
    tmp_path, mock_env,
):
    """Un fichier d'extension inconnue (.xyz) tombe sur CATEGORY_MOVIE (fallback),
    donc continue le pipeline et plantera plus loin sur detect_media_type
    comme dans la v0.3.x. C'est le comportement retro-compatible attendu :
    pas de nouveau comportement silencieux.
    """
    fake = _make_fake_file(tmp_path, "weird.xyz")
    # Le pipeline va passer la barriere Brique 1 (early_category_guess retourne
    # CATEGORY_MOVIE) puis appeler detect_media_type qui leve ValueError
    # ("Aucun fichier video trouve" - comportement v0.3.x preserve).
    with pytest.raises((ValueError, SystemExit)):
        pipeline.process_one(fake, tracker_key="gemini")


# ============================================================
# Cas video : pipeline doit progresser au-dela de Brique 1
# (verification negative : on doit PAS die() sur la Brique 1)
# ============================================================

def test_process_one_video_passes_brique_1_check(tmp_path, mock_env, capsys):
    """Un fichier .mkv passe la Brique 1 (early_category_guess -> CATEGORY_MOVIE
    = video), donc le pipeline continue vers detect_media_type et au-dela.

    On accepte n'importe quelle exception plus loin (le .mkv est vide donc
    plein de choses peuvent planter : MediaInfo, torf.PathError, etc.) —
    l'important c'est qu'on ne sorte PAS sur la Brique 1 avec le message
    'Categorie ... pas encore supportee'.
    """
    fake = _make_fake_file(tmp_path, "Fake.Movie.2024.mkv")
    # On laisse n'importe quelle exception remonter, mais on verifie ensuite
    # que la sortie ne contient PAS le message Brique 1 specifique.
    try:
        pipeline.process_one(fake, tracker_key="gemini")
    except BaseException:
        # On accepte tout (SystemExit, ValueError, torf.PathError, etc.)
        # tant que ce n'est pas la Brique 1 qui a tire la sonnette.
        pass

    captured = capsys.readouterr()
    output = captured.out + captured.err
    # Le message specifique de la Brique 1 ne doit PAS apparaitre pour un .mkv.
    assert "pas encore supportee" not in output, (
        "La Brique 1 a refuse un .mkv par erreur — le routing categorie casse"
    )


# ============================================================
# Cas hint user explicite
# ============================================================

def test_process_one_video_file_with_book_hint_routes_to_book_pipeline(
    tmp_path, mock_env, capsys, monkeypatch,
):
    """Sprint D.4 : si l'user passe explicitement category_hint=CATEGORY_BOOKS
    sur un .mkv, on respecte son hint et on route vers _process_book (au lieu
    de die() comme avant Sprint D.4).

    La priorite du hint user (Sprint C UI) s'applique meme si l'extension dit
    autre chose. Le hint user fait foi.
    """
    fake = _make_fake_file(tmp_path, "Fake.mkv")

    # Court-circuite create_torrent et le lookup providers
    def fake_create_torrent(*args, **kwargs):
        output = args[1] if len(args) > 1 else kwargs.get("output_torrent")
        if output:
            Path(output).write_bytes(b"d4:test4:datae")

    monkeypatch.setattr(pipeline, "create_torrent", fake_create_torrent)
    from flox_uploader.core.naming import book_strategy as _bs
    monkeypatch.setattr(_bs, "lookup_book_metadata", lambda m, **kw: m)

    try:
        result = pipeline.process_one(
            fake, tracker_key="gemini",
            category_hint=CATEGORY_BOOKS,
        )
        # Si on arrive ici, _process_book a tourne -> package cree
        assert result is not None
    except BaseException:
        pass  # On accepte les erreurs en aval (NFO, state init, etc.)

    # Le critere principal : on ne doit PAS voir le message Brique 1 die()
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "pas encore supportee" not in output, (
        f"Le hint user CATEGORY_BOOKS doit router vers _process_book, "
        f"pas die() Brique 1. Sortie : {output}"
    )


def test_process_one_book_file_with_movie_hint_passes_brique_1(
    tmp_path, mock_env, capsys,
):
    """Inversement : un .epub avec category_hint=CATEGORY_MOVIE doit passer la
    Brique 1 (le hint user remplace l'extension). Plantera plus loin sur
    detect_media_type (= comportement v0.3.x attendu pour un faux .mkv).
    """
    fake = _make_fake_file(tmp_path, "Fake.epub")
    # On ne doit PAS die() sur "Categorie 'Livre' pas encore supportee"
    # car le hint user force CATEGORY_MOVIE.
    try:
        pipeline.process_one(
            fake, tracker_key="gemini",
            category_hint=CATEGORY_MOVIE,
        )
    except BaseException:
        # Tout est tolere sauf le message Brique 1 (verifie ci-dessous).
        pass

    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "pas encore supportee" not in output, (
        "Le hint user CATEGORY_MOVIE doit prendre le pas sur l'extension .epub"
    )
