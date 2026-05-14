"""Tests du module core/gemini_api.py.

Ces tests utilisent `responses` pour mocker requests sans toucher au reseau.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from flox_uploader.core.gemini_api import (
    DELTA_PCT_AMBIGUOUS,
    DELTA_PCT_CERTAIN,
    DELTA_PCT_VERY_LIKELY,
    DupConfidence,
    DuplicateCandidate,
    DuplicateCheckResult,
    GeminiAPIError,
    GeminiClient,
    UploadPayload,
    _classify_delta,
    _compute_delta_pct,
)

responses = pytest.importorskip("responses")


# ============================================================
# Fixtures
# ============================================================

API_URL = "https://gemini-tracker.org/api"
API_KEY = "test-key-12345"

# Tailles types pour les tests : un film 4 Go.
OUR_SIZE = 4_000_000_000


@pytest.fixture
def client() -> GeminiClient:
    return GeminiClient(api_url=API_URL, api_key=API_KEY)


@pytest.fixture
def torrent_file(tmp_path: Path) -> Path:
    """Cree un faux .torrent valide en bencode minimal."""
    p = tmp_path / "test.torrent"
    p.write_bytes(b"d8:announce4:teste")
    return p


@pytest.fixture
def basic_payload(torrent_file: Path) -> UploadPayload:
    return UploadPayload(
        name="Foo.2024.1080p.BluRay.x265-TEAM",
        description="[b]Foo[/b]",
        mediainfo="General\nFormat : Matroska",
        torrent_path=torrent_file,
        tmdb_id=12345,
        imdb_id=9876543,
        category_id=1,
        type_id=3,
        resolution_id=2,
    )


def _hit(
    torrent_id: int,
    name: str,
    size: int,
    tmdb_id: int = 12345,
    info_hash: str = "",
    via_attributes: bool = True,
) -> dict:
    """Construit un hit Unit3D au format JSON:API (attributes nested)."""
    payload = {
        "name": name,
        "size": size,
        "tmdb_id": tmdb_id,
        "info_hash": info_hash or ("a" * 40),
        "details_link": f"https://gemini-tracker.org/torrents/{torrent_id}",
    }
    if via_attributes:
        return {"id": torrent_id, "attributes": payload}
    return {"id": torrent_id, **payload}


# ============================================================
# Helpers de classification (purs, sans HTTP)
# ============================================================

class TestClassification:
    def test_certain_when_delta_below_0_1pct(self):
        # 4 Go vs 4 Go + 100 octets -> < 0.1 %
        delta = _compute_delta_pct(OUR_SIZE, OUR_SIZE + 100)
        assert _classify_delta(delta, OUR_SIZE, OUR_SIZE + 100) == DupConfidence.CERTAIN

    def test_very_likely_when_delta_below_2pct(self):
        # 4 Go vs 4.05 Go -> ~1.25 %
        delta = _compute_delta_pct(OUR_SIZE, 4_050_000_000)
        assert _classify_delta(delta, OUR_SIZE, 4_050_000_000) == DupConfidence.VERY_LIKELY

    def test_ambiguous_when_delta_below_10pct(self):
        # 4 Go vs 4.3 Go -> ~7 %
        delta = _compute_delta_pct(OUR_SIZE, 4_300_000_000)
        assert _classify_delta(delta, OUR_SIZE, 4_300_000_000) == DupConfidence.AMBIGUOUS

    def test_none_when_delta_above_10pct(self):
        # 4 Go vs 5 Go -> ~20 % : autre qualite, pas un doublon
        delta = _compute_delta_pct(OUR_SIZE, 5_000_000_000)
        assert _classify_delta(delta, OUR_SIZE, 5_000_000_000) == DupConfidence.NONE

    def test_ambiguous_when_size_unknown(self):
        # Si on ne connait pas une des tailles, on marque ambigu (decision humaine)
        assert _classify_delta(0.0, 0, 4_000_000_000) == DupConfidence.AMBIGUOUS
        assert _classify_delta(0.0, 4_000_000_000, 0) == DupConfidence.AMBIGUOUS


# ============================================================
# Construction du client
# ============================================================

def test_client_requires_url_and_key():
    with pytest.raises(ValueError, match="api_url"):
        GeminiClient(api_url="", api_key="x")
    with pytest.raises(ValueError, match="api_key"):
        GeminiClient(api_url="https://x", api_key="")


def test_client_strips_trailing_slash():
    c = GeminiClient(api_url="https://x/api/", api_key="k")
    assert c.api_url == "https://x/api"


# ============================================================
# check_duplicate : cascade TMDB -> taille
# ============================================================

@responses.activate
def test_check_duplicate_certain_via_tmdb_exact_size(client: GeminiClient):
    """TMDB matche + taille a l'octet pres -> CERTAIN."""
    responses.add(
        responses.GET, f"{API_URL}/torrents/filter",
        json={"data": [_hit(42, "Foo.2024.1080p", OUR_SIZE, tmdb_id=12345)]},
        status=200,
    )
    result = client.check_duplicate(tmdb_id=12345, size_bytes=OUR_SIZE)
    assert result.confidence == DupConfidence.CERTAIN
    assert result.is_duplicate
    assert result.matched_via == "tmdb"
    assert result.primary.torrent_id == 42
    assert result.primary.delta_pct < 0.001


@responses.activate
def test_check_duplicate_very_likely_via_tmdb_size_close(client: GeminiClient):
    """TMDB matche + taille a 1.25 % -> VERY_LIKELY."""
    responses.add(
        responses.GET, f"{API_URL}/torrents/filter",
        json={"data": [_hit(43, "Foo.2024.1080p.AltRip", 4_050_000_000)]},
        status=200,
    )
    result = client.check_duplicate(tmdb_id=12345, size_bytes=OUR_SIZE)
    assert result.confidence == DupConfidence.VERY_LIKELY
    assert result.is_duplicate
    assert 1.0 < result.primary.delta_pct < 2.0


@responses.activate
def test_check_duplicate_ambiguous_when_size_in_2_to_10_pct(client: GeminiClient):
    """TMDB matche + taille a 7 % -> AMBIGUOUS."""
    responses.add(
        responses.GET, f"{API_URL}/torrents/filter",
        json={"data": [_hit(44, "Foo.2024.1080p.OtherRip", 4_300_000_000)]},
        status=200,
    )
    result = client.check_duplicate(tmdb_id=12345, size_bytes=OUR_SIZE)
    assert result.confidence == DupConfidence.AMBIGUOUS
    assert not result.is_duplicate
    assert result.needs_review


@responses.activate
def test_check_duplicate_none_when_size_too_different(client: GeminiClient):
    """TMDB matche mais taille +25 % -> autre qualite, pas un doublon."""
    responses.add(
        responses.GET, f"{API_URL}/torrents/filter",
        json={"data": [_hit(45, "Foo.2024.2160p.UHD", 5_000_000_000)]},
        status=200,
    )
    result = client.check_duplicate(tmdb_id=12345, size_bytes=OUR_SIZE)
    assert result.confidence == DupConfidence.NONE
    assert not result.is_duplicate
    assert result.candidates == []   # filtre, pas un doublon valide


@responses.activate
def test_check_duplicate_multiple_candidates_sorted_by_delta(client: GeminiClient):
    """Plusieurs torrents pour le meme TMDB : on retourne tries par delta croissant."""
    responses.add(
        responses.GET, f"{API_URL}/torrents/filter",
        json={"data": [
            _hit(50, "Foo.1080p.OtherRip", 4_300_000_000),    # ~7 %  (ambiguous)
            _hit(51, "Foo.1080p.MyRelease", OUR_SIZE),        # ~0 %  (certain)
            _hit(52, "Foo.2160p", 8_000_000_000),             # 50 %  (none, filtre)
            _hit(53, "Foo.1080p.AltCut", 4_050_000_000),      # ~1.25%(very_likely)
        ]},
        status=200,
    )
    result = client.check_duplicate(tmdb_id=12345, size_bytes=OUR_SIZE)
    # Le plus proche en premier (CERTAIN)
    assert result.confidence == DupConfidence.CERTAIN
    assert [c.torrent_id for c in result.candidates] == [51, 53, 50]


@responses.activate
def test_check_duplicate_rejects_tmdb_false_positive(client: GeminiClient):
    """API renvoie un torrent avec un tmdb_id different -> on ignore (faux positif)."""
    # Premier appel : TMDB renvoie un torrent au mauvais tmdb_id
    responses.add(
        responses.GET, f"{API_URL}/torrents/filter",
        json={"data": [_hit(99, "Welcome.to.School.S04E05", OUR_SIZE, tmdb_id=99999)]},
        status=200,
    )
    # Fallback name : pas de match
    responses.add(
        responses.GET, f"{API_URL}/torrents/filter",
        json={"data": []}, status=200,
    )
    result = client.check_duplicate(
        tmdb_id=12345,
        size_bytes=OUR_SIZE,
        release_name="GOAT.2026.MULTi.VF2-Amen",
    )
    assert not result.is_duplicate
    assert result.confidence == DupConfidence.NONE
    assert "tmdb_id" in result.note   # message diagnostique present


@responses.activate
def test_check_duplicate_fallback_name_when_no_tmdb(client: GeminiClient):
    """Si tmdb_id == 0, on cherche par nom et on classifie pareillement."""
    responses.add(
        responses.GET, f"{API_URL}/torrents/filter",
        json={"data": [_hit(60, "Foo.2024.1080p.BluRay.x265-TEAM", OUR_SIZE)]},
        status=200,
    )
    result = client.check_duplicate(
        tmdb_id=0,
        size_bytes=OUR_SIZE,
        release_name="Foo.2024.1080p.BluRay.x265-TEAM",  # meme team => CERTAIN
    )
    assert result.matched_via == "name"
    assert result.confidence == DupConfidence.CERTAIN


@responses.activate
def test_check_duplicate_rejects_name_false_positive(client: GeminiClient):
    """API renvoie un torrent au nom totalement different -> on ignore."""
    responses.add(
        responses.GET, f"{API_URL}/torrents/filter",
        json={"data": [_hit(70, "Welcome.to.Demon.School.S04E05", OUR_SIZE)]},
        status=200,
    )
    result = client.check_duplicate(
        tmdb_id=0,
        size_bytes=OUR_SIZE,
        release_name="GOAT.2026.MULTi.VF2.2160p-Amen",
    )
    assert not result.is_duplicate
    assert "ressemble" in result.note.lower() or "ne ressemble" in result.note.lower()


@responses.activate
def test_check_duplicate_no_match_returns_clean(client: GeminiClient):
    """Aucun candidat trouve -> NONE, candidates vide, pas de note."""
    responses.add(
        responses.GET, f"{API_URL}/torrents/filter",
        json={"data": []}, status=200,
    )
    result = client.check_duplicate(tmdb_id=12345, size_bytes=OUR_SIZE)
    assert result.confidence == DupConfidence.NONE
    assert result.candidates == []
    assert not result.is_duplicate


@responses.activate
def test_check_duplicate_401_raises(client: GeminiClient):
    responses.add(
        responses.GET, f"{API_URL}/torrents/filter",
        json={"message": "Unauthorized"}, status=401,
    )
    with pytest.raises(GeminiAPIError) as ei:
        client.check_duplicate(tmdb_id=12345, size_bytes=OUR_SIZE)
    assert ei.value.status_code == 401


def test_check_duplicate_requires_at_least_one_criterion(client: GeminiClient):
    with pytest.raises(ValueError):
        client.check_duplicate(tmdb_id=0, release_name="")


# ============================================================
# upload_torrent
# ============================================================

def test_upload_dry_run_does_not_call_network(
    client: GeminiClient, basic_payload: UploadPayload,
):
    with responses.RequestsMock() as rsps:
        result = client.upload_torrent(basic_payload, dry_run=True)
        assert len(rsps.calls) == 0

    assert result.success
    assert result.dry_run_payload is not None
    assert result.dry_run_payload["name"] == basic_payload.name
    assert result.dry_run_payload["tmdb"] == 12345
    assert result.dry_run_payload["category_id"] == 1
    assert "_torrent_file" in result.dry_run_payload
    assert result.dry_run_payload["_torrent_size_bytes"] > 0


def test_upload_missing_torrent_file_raises(
    client: GeminiClient, basic_payload: UploadPayload,
):
    basic_payload.torrent_path = Path("/nonexistent/path/file.torrent")
    with pytest.raises(FileNotFoundError):
        client.upload_torrent(basic_payload, dry_run=True)


@responses.activate
def test_upload_real_post_returns_torrent_id(
    client: GeminiClient, basic_payload: UploadPayload,
):
    responses.add(
        responses.POST,
        f"{API_URL}/torrents/upload",
        json={
            "data": {
                "id": 1234,
                "attributes": {
                    "name": basic_payload.name,
                    "details_link": "https://gemini-tracker.org/torrents/1234",
                },
            },
            "message": "Torrent uploaded",
        },
        status=200,
    )

    result = client.upload_torrent(basic_payload, dry_run=False)
    assert result.success
    assert result.torrent_id == 1234
    assert "1234" in result.torrent_url


@responses.activate
def test_upload_422_raises_with_body(
    client: GeminiClient, basic_payload: UploadPayload,
):
    responses.add(
        responses.POST, f"{API_URL}/torrents/upload",
        json={"errors": {"name": ["Le nom ne respecte pas la convention"]}},
        status=422,
    )
    with pytest.raises(GeminiAPIError) as ei:
        client.upload_torrent(basic_payload, dry_run=False)
    assert ei.value.status_code == 422
    assert "convention" in ei.value.body


# ============================================================
# download_torrent
# ============================================================

@responses.activate
def test_download_torrent_writes_bencoded_content(
    client: GeminiClient, tmp_path: Path,
):
    fake_torrent_bytes = b"d8:announce30:https://example.org/announce/xyze"
    responses.add(
        responses.GET, f"{API_URL}/torrents/download/42",
        body=fake_torrent_bytes, status=200,
        content_type="application/x-bittorrent",
    )

    dest = tmp_path / "out.torrent"
    written = client.download_torrent(42, dest)
    assert written == dest
    assert dest.read_bytes() == fake_torrent_bytes


@responses.activate
def test_download_torrent_html_response_raises(
    client: GeminiClient, tmp_path: Path,
):
    responses.add(
        responses.GET, f"{API_URL}/torrents/download/42",
        body=b"<html><body>Forbidden</body></html>", status=200,
    )
    with pytest.raises(GeminiAPIError, match="non-bencode"):
        client.download_torrent(42, tmp_path / "out.torrent")


def test_download_torrent_invalid_id_raises(client: GeminiClient, tmp_path: Path):
    with pytest.raises(ValueError):
        client.download_torrent(0, tmp_path / "out.torrent")
    with pytest.raises(ValueError):
        client.download_torrent(-1, tmp_path / "out.torrent")


# ============================================================
# Phase 3b.3 : resserrement dedup (team + resolution)
# ============================================================

@responses.activate
def test_classify_team_mismatch_downgrades_certain_to_ambiguous(client: GeminiClient):
    """Same size + meme TMDB ID + meme resolution mais team differente
    -> downgrade CERTAIN -> AMBIGUOUS (le size match est suspect)."""
    responses.add(
        responses.GET, f"{API_URL}/torrents/filter",
        json={"data": [_hit(60, "Foo.2024.1080p.BluRay.x265-OTHER", OUR_SIZE)]},
        status=200,
    )
    result = client.check_duplicate(
        tmdb_id=12345,
        size_bytes=OUR_SIZE,
        release_name="Foo.2024.1080p.BluRay.x265-MINE",
    )
    assert result.confidence == DupConfidence.AMBIGUOUS
    assert len(result.candidates) == 1


@responses.activate
def test_classify_resolution_mismatch_means_not_a_duplicate(client: GeminiClient):
    """Resolution differente connue des deux cotes -> NONE (pas un doublon)."""
    responses.add(
        responses.GET, f"{API_URL}/torrents/filter",
        json={"data": [_hit(60, "Foo.2024.720p.BluRay.x264-TEAM", OUR_SIZE)]},
        status=200,
    )
    result = client.check_duplicate(
        tmdb_id=12345,
        size_bytes=OUR_SIZE,
        release_name="Foo.2024.2160p.BluRay.x265-TEAM",  # 2160p vs 720p
    )
    assert result.confidence == DupConfidence.NONE
    assert len(result.candidates) == 0  # filtre, pas un doublon


@responses.activate
def test_classify_same_team_same_res_keeps_certain(client: GeminiClient):
    """Meme team + meme resolution + meme taille -> CERTAIN."""
    responses.add(
        responses.GET, f"{API_URL}/torrents/filter",
        json={"data": [_hit(60, "Foo.2024.1080p.BluRay.x265-TEAM", OUR_SIZE)]},
        status=200,
    )
    result = client.check_duplicate(
        tmdb_id=12345,
        size_bytes=OUR_SIZE,
        release_name="Foo.2024.1080p.BluRay.x265-TEAM",
    )
    assert result.confidence == DupConfidence.CERTAIN
