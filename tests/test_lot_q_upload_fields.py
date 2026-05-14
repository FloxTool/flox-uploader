"""Tests Lot Q : champs upload supplementaires (formulaire Gemini reel).

Couvre :
- Q.1 PackageStateData expose les nouveaux champs avec defaults
- Q.2 tmdb_context contient tvdb_id + keywords
- Q.5 build_upload_payload utilise les overrides + extra dict
"""
from __future__ import annotations

from pathlib import Path

import pytest

from flox_uploader.core.media_type import MediaType
from flox_uploader.core.package_state import PackageStateData


# ============================================================
# Q.1 — PackageStateData expose les nouveaux champs
# ============================================================

def test_q1_default_values_zero():
    """Tous les nouveaux champs ont la valeur par defaut 0/'' ."""
    s = PackageStateData()
    assert s.manual_imdb_id == ""
    assert s.manual_tvdb_id == 0
    assert s.manual_mal_id == 0
    assert s.manual_season_number == 0
    assert s.manual_episode_number == 0
    assert s.manual_distributor_id == 0
    assert s.manual_region_id == 0
    assert s.manual_keywords == ""


def test_q1_serialize_roundtrip():
    """Sauvegarde + relecture preserve les nouveaux champs."""
    s = PackageStateData(
        release_name="Foo.2024-TEAM",
        manual_imdb_id="tt9999999",
        manual_tvdb_id=12345,
        manual_mal_id=678,
        manual_season_number=2,
        manual_episode_number=10,
        manual_distributor_id=4,
        manual_region_id=7,
        manual_keywords="action, thriller",
    )
    raw = s.to_json()
    s2 = PackageStateData.from_json(raw)
    assert s2.manual_imdb_id == "tt9999999"
    assert s2.manual_tvdb_id == 12345
    assert s2.manual_mal_id == 678
    assert s2.manual_season_number == 2
    assert s2.manual_episode_number == 10
    assert s2.manual_distributor_id == 4
    assert s2.manual_region_id == 7
    assert s2.manual_keywords == "action, thriller"


# ============================================================
# Q.2 — TMDB context contient les nouveaux IDs externes + keywords
# ============================================================

def test_q2_build_tmdb_context_extracts_tvdb_id():
    """_build_tmdb_context extrait tvdb_id depuis external_ids."""
    from flox_uploader.core.tmdb import _build_tmdb_context

    details = {
        "id": 911430,
        "title": "F1",
        "external_ids": {"imdb_id": "tt16311594", "tvdb_id": 999888},
        "keywords": {"keywords": [{"name": "racing"}, {"name": "formula one"}]},
    }
    ctx = _build_tmdb_context(details, 911430)
    assert ctx["tvdb_id"] == 999888
    assert ctx["keywords"] == ["racing", "formula one"]


def test_q2_build_tmdb_context_no_keywords_empty_list():
    from flox_uploader.core.tmdb import _build_tmdb_context
    details = {"id": 1, "title": "X", "external_ids": {}}
    ctx = _build_tmdb_context(details, 1)
    assert ctx["tvdb_id"] == 0
    assert ctx["keywords"] == []


def test_q2_build_tv_context_extracts_tvdb():
    """Variante TV : keywords dans .results au lieu de .keywords."""
    from flox_uploader.core.tmdb import _build_tv_context

    details = {
        "id": 79573,
        "name": "Show",
        "external_ids": {"imdb_id": "tt7753154", "tvdb_id": 372848},
        "keywords": {"results": [{"name": "documentary"}, {"name": "f1"}]},
    }
    ctx = _build_tv_context(details, 79573)
    assert ctx["tvdb_id"] == 372848
    assert ctx["keywords"] == ["documentary", "f1"]


# ============================================================
# Q.5 — build_upload_payload applique les overrides + extra
# ============================================================

@pytest.fixture
def fake_bundle(tmp_path):
    """Forge un PackageBundle minimal pour tester build_upload_payload."""
    from flox_uploader.core.upload_orchestrator import PackageBundle
    package_dir = tmp_path / "pkg"
    package_dir.mkdir()
    torrent_path = package_dir / "release.torrent"
    torrent_path.write_bytes(b"")
    return PackageBundle(
        release_name="Foo.2024.MULTi.VFF.1080p.BluRay.x265-TEAM",
        package_dir=package_dir,
        torrent_path=torrent_path,
        nfo_path=None,
        description="desc",
        mediainfo="mediainfo",
        infohash="abc",
        size_bytes=10**9,
        tmdb_id=42,
        imdb_id=1234567,
        tvdb_id=0,
        media_type=MediaType.MOVIE,
        season_number=0,
        episode_number=0,
        tmdb_genres=["Action"],
    )


def _save_state(package_dir: Path, **overrides):
    from flox_uploader.core.package_state import (
        PackageStateData, PackageState, write_state,
    )
    s = PackageStateData(state=PackageState.PREPARED, **overrides)
    write_state(package_dir, s)


def test_q5_no_overrides_uses_bundle_defaults(fake_bundle):
    from flox_uploader.core.upload_orchestrator import (
        build_upload_payload, UploadConfig,
    )
    cfg = UploadConfig(api_url="http://x", api_key="k", dry_run=True)
    payload = build_upload_payload(fake_bundle, cfg)
    assert payload.imdb_id == 1234567
    assert payload.tvdb_id == 0
    assert payload.mal_id == 0
    assert payload.extra == {}


def test_q5_imdb_override_strips_tt(fake_bundle):
    """L'user saisit 'tt9999999' -> on le passe au tracker en int 9999999."""
    from flox_uploader.core.upload_orchestrator import (
        build_upload_payload, UploadConfig,
    )
    _save_state(fake_bundle.package_dir, manual_imdb_id="tt9999999")
    payload = build_upload_payload(fake_bundle, UploadConfig(api_url="http://x", api_key="k", dry_run=True))
    assert payload.imdb_id == 9999999


def test_q5_tvdb_mal_override(fake_bundle):
    from flox_uploader.core.upload_orchestrator import (
        build_upload_payload, UploadConfig,
    )
    _save_state(fake_bundle.package_dir, manual_tvdb_id=111, manual_mal_id=222)
    payload = build_upload_payload(fake_bundle, UploadConfig(api_url="http://x", api_key="k", dry_run=True))
    assert payload.tvdb_id == 111
    assert payload.mal_id == 222


def test_q5_season_episode_override(fake_bundle):
    from flox_uploader.core.upload_orchestrator import (
        build_upload_payload, UploadConfig,
    )
    _save_state(
        fake_bundle.package_dir,
        manual_season_number=5,
        manual_episode_number=12,
    )
    payload = build_upload_payload(fake_bundle, UploadConfig(api_url="http://x", api_key="k", dry_run=True))
    assert payload.season_number == 5
    assert payload.episode_number == 12


def test_q5_keywords_added_to_extra(fake_bundle):
    from flox_uploader.core.upload_orchestrator import (
        build_upload_payload, UploadConfig,
    )
    _save_state(fake_bundle.package_dir, manual_keywords="super-heros, marvel")
    payload = build_upload_payload(fake_bundle, UploadConfig(api_url="http://x", api_key="k", dry_run=True))
    assert payload.extra.get("keywords") == "super-heros, marvel"


def test_q5_distributor_only_for_full_disc(fake_bundle):
    """Distributor/Region n'est inclus dans extra QUE si type_id = 1 (Full Disc)."""
    from flox_uploader.core.upload_orchestrator import (
        build_upload_payload, UploadConfig,
    )
    # Cas 1 : manual_distributor mais type non FullDisc -> NOT in extra
    _save_state(
        fake_bundle.package_dir,
        manual_distributor_id=4,
        manual_region_id=7,
    )
    payload = build_upload_payload(fake_bundle, UploadConfig(api_url="http://x", api_key="k", dry_run=True))
    # Type auto pour BluRay.x265 -> BDRIP (id 3), pas Full Disc
    assert "distributor_id" not in payload.extra
    assert "region_id" not in payload.extra


def test_q5_distributor_present_for_full_disc(fake_bundle):
    """Si user override type=1 (Full Disc) ET distributor>0 -> dans extra."""
    from flox_uploader.core.upload_orchestrator import (
        build_upload_payload, UploadConfig,
    )
    _save_state(
        fake_bundle.package_dir,
        manual_type_id=1,  # Full Disc
        manual_distributor_id=4,
        manual_region_id=7,
    )
    payload = build_upload_payload(fake_bundle, UploadConfig(api_url="http://x", api_key="k", dry_run=True))
    assert payload.extra.get("distributor_id") == 4
    assert payload.extra.get("region_id") == 7
