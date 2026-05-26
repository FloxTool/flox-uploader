"""Extraction cover + previews random depuis fichiers livre.

Sprint D.19 v0.5.0 (note Louis Q3). Extrait depuis le fichier source :
- 1 image cover (couverture, generee depuis le 1er asset du fichier)
- N images previews (pages random pour PDF, images espacees pour CBZ/CBR)

Formats supportes :
- EPUB : cover via OPF manifest (deja D.7). Pas de previews (texte XHTML).
- CBZ : cover = 1re image triee. Previews = N images espacees (25%, 50%, 75%).
- CBR : idem CBZ via rarfile + unrar. Degrade gracieusement si unrar absent.
- PDF : cover = page 1 rendue. Previews = N pages random via PyMuPDF.
- MP3 : cover via mutagen ID3 (APIC frame). Pas de previews (audio).
- M4B : cover via mutagen MP4 ('covr' atom). Pas de previews.
- Autres : skip silencieusement (.mobi/.azw3/.djvu).

Le caller (pipeline._process_book) sauve les images dans
`package_dir/_previews/` et envoie au upload host (imgbb).
"""
from __future__ import annotations

import random
import zipfile
from pathlib import Path


# Extensions d'images considerees comme pages (CBZ/CBR/EPUB ressources)
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif"}

# Sprint D.42 v0.5.0 (feedback Louis) : compression agressive pour rester
# sous le quota imgbb (500 uploads/jour, plus exigeant en taille pour
# eviter le rate limit).
# - PyMuPDF zoom 1.7 -> 1.2 : ~50% de pixels en moins (~75% en taille fichier).
# - jpg_quality 80 (vs default 95) : ~30% de gain supplementaire.
# - Resize max 1200px largeur : safety net pour les CBZ/MP3 covers extraites
#   en pleine resolution depuis le ZIP/ID3.
# Total : 2.5 MB -> ~250-400 KB par image (gain x6-10).
PYMUPDF_ZOOM = 1.2
JPEG_QUALITY = 80
MAX_IMAGE_WIDTH_PX = 1200


def _save_pixmap_compressed(pix, path: Path) -> None:
    """Sprint D.42 : sauve un Pixmap PyMuPDF en JPEG avec compression agressive.

    pix.save() ecrit en PNG par defaut (= 5-10x plus gros que JPEG q=80).
    On force JPEG via le param `output=` + qualite reduite.

    Note : PyMuPDF.Pixmap.save accepte `jpg_quality` (default 95). On
    descend a 80 = pratiquement invisible visuellement, gros gain taille.
    """
    pix.save(str(path), output="jpeg", jpg_quality=JPEG_QUALITY)


def _maybe_recompress_external_image(path: Path) -> None:
    """Sprint D.42 : si Pillow est disponible, recompresse une image externe
    (CBZ premiere page, MP3 ID3 cover, folder.jpg) pour limiter le poids
    avant upload imgbb.

    - Resize si largeur > MAX_IMAGE_WIDTH_PX (preserve ratio)
    - JPEG quality JPEG_QUALITY
    - PNG -> JPEG si pas de transparence (gain x3-5)

    Si Pillow n'est pas installe : no-op silencieux (degrade gracieusement).
    """
    try:
        from PIL import Image
    except ImportError:
        return  # Pillow optionnel : pas de recompression
    if not path.is_file():
        return
    try:
        img = Image.open(path)
        original_size = path.stat().st_size
        # Convertir RGBA -> RGB si pas de transparence reelle utilisee
        # (sinon JPEG = perte du canal alpha). On garde PNG pour les
        # vraies images transparentes.
        has_alpha = img.mode in ("RGBA", "LA") or (
            img.mode == "P" and "transparency" in img.info
        )
        # Resize si trop large
        if img.width > MAX_IMAGE_WIDTH_PX:
            ratio = MAX_IMAGE_WIDTH_PX / img.width
            new_size = (MAX_IMAGE_WIDTH_PX, int(img.height * ratio))
            img = img.resize(new_size, Image.LANCZOS)
        # Save : JPEG si pas d'alpha, sinon WebP (gere alpha + compresse mieux)
        ext = path.suffix.lower()
        if has_alpha and ext == ".png":
            # Garde PNG pour transparence (mais le PIL.optimize reduit la taille)
            img.save(path, "PNG", optimize=True)
        else:
            # Convertir en RGB et sauver en JPEG (meme si l'ext etait .png)
            if img.mode != "RGB":
                img = img.convert("RGB")
            # On garde l'extension d'origine pour ne pas casser les refs ;
            # PIL save() respecte le format explicite passe en 2e arg.
            img.save(path, "JPEG", quality=JPEG_QUALITY, optimize=True)
        new_size = path.stat().st_size
        if new_size < original_size:
            print(
                f"[INFO] Image recompressee : {path.name} "
                f"{original_size // 1024} KB -> {new_size // 1024} KB "
                f"(-{100 * (original_size - new_size) // original_size}%)"
            )
    except Exception as e:
        # Toute erreur Pillow = no-op silencieux (image gardee telle quelle)
        print(f"[WARN] Recompression {path.name} echec : {type(e).__name__} {e}")


def extract_cover_and_previews(
    source: Path,
    output_dir: Path,
    preview_count: int = 4,
    rng_seed: int | None = None,
) -> dict:
    """Extrait cover + N previews depuis un fichier livre.

    Args:
        source : path du fichier (.epub / .pdf / .cbz / .cbr / .mp3 / .m4b).
        output_dir : dossier de sortie (cree si absent). Y ecrit :
          - cover.jpg (ou .png/.webp selon source) : la couverture
          - preview_1.jpg, preview_2.jpg, ... : les previews
        preview_count : nombre de previews random (defaut 4, note Louis).
        rng_seed : seed pour le random (utile pour les tests). None = aleatoire.

    Returns:
        Dict {
          "cover": Path | None,
          "previews": list[Path],  # peut etre [] si format sans previews
          "format": str,  # "epub" / "cbz" / "pdf" / "mp3" / "m4b" / "cbr" / "unsupported"
          "warning": str,  # vide ou message si fallback (rarfile absent, etc.)
        }

    Ne plante jamais : un format non supporte ou un fichier corrompu
    retourne un dict avec cover=None et warning rempli.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    ext = source.suffix.lower().lstrip(".")
    result: dict = {
        "cover": None,
        "previews": [],
        "format": ext or "unknown",
        "warning": "",
    }

    # Sprint D.37 v0.5.0 : si source est un DOSSIER (audiobook MP3
    # multi-chapitres typiquement), on trouve le 1er fichier audio
    # dedans et on extrait depuis ce fichier-la.
    #
    # Sprint D.39 v0.5.0 (feedback Louis #26 Marc Levy) : si le 1er MP3
    # n'a pas d'APIC, on essaie les SUIVANTS. Tous les chapitres ne
    # taggent pas systematiquement la cover (Piste 01.mp3 sans APIC,
    # Piste 02.mp3 avec APIC -> on prend Piste 02). On stocke la liste
    # complete dans result["_audio_fallback_files"] pour que
    # _extract_from_audio puisse iterer.
    if source.is_dir():
        # Chercher TOUS les fichiers audio (MP3/M4B) dans le dossier
        audio_files = sorted([
            p for p in source.rglob("*")
            if p.is_file() and p.suffix.lower() in (".mp3", ".m4b")
        ])
        if audio_files:
            source = audio_files[0]
            ext = source.suffix.lower().lstrip(".")
            result["format"] = ext
            # Sprint D.39 : memoriser tous les autres MP3 pour fallback
            result["_audio_fallback_files"] = audio_files
        else:
            # Pas d'audio, fallback : chercher 1er ebook
            ebook_files = sorted([
                p for p in source.rglob("*")
                if p.is_file() and p.suffix.lower() in (
                    ".epub", ".pdf", ".cbz", ".cbr"
                )
            ])
            if ebook_files:
                source = ebook_files[0]
                ext = source.suffix.lower().lstrip(".")
                result["format"] = ext
            else:
                result["warning"] = f"Aucun fichier livre/audio dans : {source}"
                return result

    if not source.is_file():
        result["warning"] = f"Fichier source absent : {source}"
        return result

    if ext == "epub":
        return _extract_from_epub(
            source, output_dir, preview_count, rng_seed, result,
        )

    if ext == "cbz":
        return _extract_from_zip(
            source, output_dir, preview_count, rng_seed, result,
        )

    if ext == "cbr":
        return _extract_from_rar(
            source, output_dir, preview_count, rng_seed, result,
        )

    if ext == "pdf":
        return _extract_from_pdf(
            source, output_dir, preview_count, rng_seed, result,
        )

    if ext in ("mp3", "m4b"):
        return _extract_from_audio(source, output_dir, result)

    # Format non supporte (mobi/azw3/djvu/...)
    result["warning"] = (
        f"Extraction non supportee pour .{ext}. "
        "Saisis une cover URL externe dans Options upload."
    )
    return result


# ============================================================
# EPUB (cover via OPF + previews depuis images embedded)
# ============================================================

class _EmptyEPUB(Exception):
    """Marqueur interne : EPUB sans pages -> fallback legacy."""


def _extract_from_epub(
    source: Path,
    output_dir: Path,
    preview_count: int,
    rng_seed: int | None,
    result: dict,
) -> dict:
    """Extrait cover + N previews EPUB en RENDANT les pages complètes.

    Sprint D.32 v0.5.0 (UX Louis) : avant on extrayait des images embedded
    (illustrations brutes hors contexte). Maintenant on rend chaque page
    EPUB complete via PyMuPDF (qui ouvre EPUB nativement comme PDF).
    On voit donc la mise en page reelle : texte + images dans leur contexte.

    Fallback : si PyMuPDF echoue (rare), on bascule sur l'ancienne strategie
    (cover via OPF manifest + images ZIP embedded). Defensif.

    Strategie :
    1. fitz.open(epub) -> doc paginated
    2. Cover : page 0 rendue en image
    3. Previews : N pages random dans [1, page_count-1]
    """
    # === Tentative principale : PyMuPDF (rend les pages comme PDF) ===
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return _extract_from_epub_legacy(
            source, output_dir, preview_count, rng_seed, result,
        )

    try:
        doc = fitz.open(str(source))
    except Exception as e:
        # Echec ouverture EPUB par fitz -> fallback legacy
        print(f"[WARN] EPUB fitz ouverture echec ({source.name}) : {type(e).__name__} {e}")
        return _extract_from_epub_legacy(
            source, output_dir, preview_count, rng_seed, result,
        )

    try:
        if doc.page_count == 0:
            # On laisse le finally fermer doc avant le fallback
            raise _EmptyEPUB()

        # Sprint D.42 : zoom 1.2 + JPEG quality 80 (~85 dpi, compression aggressive).
        # Equilibre lisibilite preview / taille fichier / quota imgbb.
        mat = fitz.Matrix(PYMUPDF_ZOOM, PYMUPDF_ZOOM)

        # Cover : page 0 rendue
        cover_path = output_dir / "cover.jpg"
        try:
            page = doc.load_page(0)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            _save_pixmap_compressed(pix, cover_path)
            result["cover"] = cover_path
        except Exception as e:
            print(f"[WARN] EPUB cover render echec : {type(e).__name__} {e}")
            # Fallback cover via OPF manifest si render rate
            from .epub_metadata import extract_epub_cover
            if extract_epub_cover(source, cover_path):
                _maybe_recompress_external_image(cover_path)
                result["cover"] = cover_path

        # Previews : pages random dans [1, page_count-1] (skip page 1 = cover,
        # skip derniere = souvent table des matieres / mentions legales).
        # Skip aussi les ~10 premieres pages (souvent intro / sommaire) et
        # les ~5 dernieres pour livres assez longs.
        if doc.page_count >= 3:
            if doc.page_count >= 30:
                skip_start = 10
                skip_end = 5
            else:
                skip_start = 1
                skip_end = 1
            available = list(range(skip_start, max(skip_start + 1, doc.page_count - skip_end)))
            if len(available) > preview_count:
                if rng_seed is not None:
                    random.seed(rng_seed)
                preview_indices = sorted(random.sample(available, preview_count))
            else:
                preview_indices = available

            for i, page_idx in enumerate(preview_indices, start=1):
                try:
                    page = doc.load_page(page_idx)
                    pix = page.get_pixmap(matrix=mat, alpha=False)
                    p = output_dir / f"preview_{i}.jpg"
                    _save_pixmap_compressed(pix, p)
                    result["previews"].append(p)
                except Exception as e:
                    print(f"[WARN] EPUB page {page_idx} render echec : {e}")
    except _EmptyEPUB:
        # Bascule sur le fallback legacy (cover via OPF + images ZIP)
        doc.close()
        return _extract_from_epub_legacy(
            source, output_dir, preview_count, rng_seed, result,
        )
    finally:
        if not doc.is_closed:
            doc.close()
    return result


def _extract_from_epub_legacy(
    source: Path,
    output_dir: Path,
    preview_count: int,
    rng_seed: int | None,
    result: dict,
) -> dict:
    """Fallback EPUB : cover via OPF + previews via images embedded ZIP.

    Sprint D.22 (legacy) — strategie precedente conservee pour les cas ou
    PyMuPDF echoue sur un EPUB exotique.
    """
    from .epub_metadata import extract_epub_cover

    cover_path = output_dir / "cover.jpg"
    if extract_epub_cover(source, cover_path):
        result["cover"] = cover_path

    # Previews : explorer le ZIP a la recherche d'images embedded
    try:
        with zipfile.ZipFile(source, "r") as zf:
            image_names = sorted([
                n for n in zf.namelist()
                if Path(n).suffix.lower() in _IMAGE_EXTS
                and not n.startswith("__MACOSX/")
                and not n.lower().endswith("/.ds_store")
            ])
            non_cover = [
                n for n in image_names
                if "cover" not in Path(n).name.lower()
                and "couv" not in Path(n).name.lower()
            ]
            if result["cover"] is not None and non_cover and non_cover == image_names:
                non_cover = non_cover[1:]

            if not non_cover:
                return result

            preview_picks = _pick_evenly_spaced(
                non_cover, preview_count, skip_start=0, skip_end=0,
            )
            for i, name in enumerate(preview_picks, start=1):
                try:
                    data = zf.read(name)
                    ext_img = Path(name).suffix.lower()
                    p = output_dir / f"preview_{i}{ext_img}"
                    p.write_bytes(data)
                    result["previews"].append(p)
                except (KeyError, OSError) as e:
                    print(f"[WARN] EPUB preview {name} : {type(e).__name__} {e}")
    except (zipfile.BadZipFile, OSError) as e:
        if result["cover"] is None:
            result["warning"] = f"EPUB lecture echec : {type(e).__name__} {e}"
    return result


# ============================================================
# CBZ (ZIP d'images)
# ============================================================

def _extract_from_zip(
    source: Path,
    output_dir: Path,
    preview_count: int,
    rng_seed: int | None,
    result: dict,
) -> dict:
    """Cover = 1re image triee. Previews = N images espacees."""
    try:
        with zipfile.ZipFile(source, "r") as zf:
            image_names = sorted([
                n for n in zf.namelist()
                if Path(n).suffix.lower() in _IMAGE_EXTS
                and not n.startswith("__MACOSX/")
                and not n.lower().endswith("/.ds_store")
            ])
            if not image_names:
                result["warning"] = "CBZ sans images detectees."
                return result

            # Cover = 1re image
            cover_data = zf.read(image_names[0])
            cover_path = output_dir / f"cover{Path(image_names[0]).suffix.lower()}"
            cover_path.write_bytes(cover_data)
            # Sprint D.42 : recompresse pour limiter le poids avant upload imgbb
            _maybe_recompress_external_image(cover_path)
            result["cover"] = cover_path

            # Previews = N images espacees uniformement (eviter les 2-3 1res
            # qui sont souvent cover/copyright/sommaire, et la derniere
            # qui est souvent une 4e de couverture).
            preview_paths = _pick_evenly_spaced(
                image_names, preview_count, skip_start=2, skip_end=1,
            )
            for i, name in enumerate(preview_paths, start=1):
                data = zf.read(name)
                ext = Path(name).suffix.lower()
                p = output_dir / f"preview_{i}{ext}"
                p.write_bytes(data)
                _maybe_recompress_external_image(p)
                result["previews"].append(p)
    except (zipfile.BadZipFile, OSError, KeyError) as e:
        result["warning"] = f"CBZ lecture echec : {type(e).__name__} {e}"
    return result


def _pick_evenly_spaced(
    items: list,
    count: int,
    skip_start: int = 0,
    skip_end: int = 0,
) -> list:
    """Selectionne `count` items repartis uniformement.

    Saute les `skip_start` premiers et `skip_end` derniers pour eviter
    cover (deja extraite) et 4e de couv.

    Si pas assez d'items apres skip, on prend ce qu'on peut.
    """
    if not items:
        return []
    available = items[skip_start:len(items) - skip_end] if (len(items) > skip_start + skip_end) else items
    if not available:
        return []
    if len(available) <= count:
        return available
    # Repartition uniforme : N items espaces sur [0, len-1]
    step = len(available) / (count + 1)
    return [available[int(step * (i + 1))] for i in range(count)]


# ============================================================
# CBR (RAR d'images)
# ============================================================

def _extract_from_rar(
    source: Path,
    output_dir: Path,
    preview_count: int,
    rng_seed: int | None,
    result: dict,
) -> dict:
    """CBR = RAR d'images. Necessite rarfile + unrar.exe dans le PATH."""
    try:
        import rarfile
    except ImportError:
        result["warning"] = (
            "rarfile non installe. CBR non extrait. "
            "Saisis une cover URL externe ou converti en CBZ."
        )
        return result

    try:
        # Test rapide si unrar est dispo : on cree un objet, mais en realite
        # rarfile delegate a unrar a la lecture. Si unrar absent : OSError.
        with rarfile.RarFile(source) as rf:
            image_names = sorted([
                n for n in rf.namelist()
                if Path(n).suffix.lower() in _IMAGE_EXTS
                and not n.startswith("__MACOSX/")
            ])
            if not image_names:
                result["warning"] = "CBR sans images detectees."
                return result

            # Cover
            with rf.open(image_names[0]) as fh:
                cover_data = fh.read()
            cover_path = output_dir / f"cover{Path(image_names[0]).suffix.lower()}"
            cover_path.write_bytes(cover_data)
            # Sprint D.42 : recompresse pour quota imgbb
            _maybe_recompress_external_image(cover_path)
            result["cover"] = cover_path

            # Previews
            preview_picks = _pick_evenly_spaced(
                image_names, preview_count, skip_start=2, skip_end=1,
            )
            for i, name in enumerate(preview_picks, start=1):
                with rf.open(name) as fh:
                    data = fh.read()
                p = output_dir / f"preview_{i}{Path(name).suffix.lower()}"
                p.write_bytes(data)
                _maybe_recompress_external_image(p)
                result["previews"].append(p)
    except Exception as e:
        # rarfile.BadRarFile, rarfile.RarCannotExec (unrar absent), OSError
        msg = str(e)
        if "Cannot find working tool" in msg or "RarCannotExec" in type(e).__name__:
            result["warning"] = (
                "unrar.exe absent du PATH. Pour supporter les CBR, installe "
                "unrar (https://www.rarlab.com/rar_add.htm) ou convertis en CBZ."
            )
        else:
            result["warning"] = f"CBR lecture echec : {type(e).__name__} {e}"
    return result


# ============================================================
# PDF (rendu via PyMuPDF)
# ============================================================

def _extract_from_pdf(
    source: Path,
    output_dir: Path,
    preview_count: int,
    rng_seed: int | None,
    result: dict,
) -> dict:
    """PDF : cover = page 1 rendue en image, previews = N pages random."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        result["warning"] = (
            "PyMuPDF (fitz) non installe. PDF cover/previews non extraits."
        )
        return result

    try:
        doc = fitz.open(str(source))
    except Exception as e:
        result["warning"] = f"PDF ouverture echec : {type(e).__name__} {e}"
        return result

    try:
        if doc.page_count == 0:
            result["warning"] = "PDF sans pages."
            return result

        # Sprint D.42 : zoom 1.2 + JPEG quality 80 (compression aggressive
        # cf. _save_pixmap_compressed pour rationale).
        mat = fitz.Matrix(PYMUPDF_ZOOM, PYMUPDF_ZOOM)

        # Cover : page 1
        cover_path = output_dir / "cover.jpg"
        try:
            page = doc.load_page(0)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            _save_pixmap_compressed(pix, cover_path)
            result["cover"] = cover_path
        except Exception as e:
            result["warning"] = f"PDF cover render echec : {type(e).__name__} {e}"

        # Previews : pages random (eviter page 1 = cover, page finale = TOC)
        # On choisit dans [1, page_count - 1] (0-indexed, donc on saute la 1re).
        if doc.page_count >= 3:
            available = list(range(1, doc.page_count - 1))
            if len(available) > preview_count:
                if rng_seed is not None:
                    random.seed(rng_seed)
                preview_indices = sorted(random.sample(available, preview_count))
            else:
                preview_indices = available

            for i, page_idx in enumerate(preview_indices, start=1):
                try:
                    page = doc.load_page(page_idx)
                    pix = page.get_pixmap(matrix=mat, alpha=False)
                    p = output_dir / f"preview_{i}.jpg"
                    _save_pixmap_compressed(pix, p)
                    result["previews"].append(p)
                except Exception as e:
                    print(f"[WARN] PDF page {page_idx} render echec : {e}")
    finally:
        doc.close()
    return result


# ============================================================
# MP3 / M4B (audiobook cover via mutagen)
# ============================================================

def _extract_from_audio(
    source: Path,
    output_dir: Path,
    result: dict,
) -> dict:
    """Cover audiobook depuis ID3 (MP3) ou MP4 atom (M4B).

    Sprint D.39 v0.5.0 (feedback Louis #26 Marc Levy) : si la 1re piste
    n'a pas de cover embedded, on essaie les SUIVANTES (toutes les pistes
    du dossier listees dans result["_audio_fallback_files"]).
    """
    try:
        from mutagen import File as MutagenFile
        from mutagen.id3 import ID3
    except ImportError:
        result["warning"] = "mutagen non installe. Cover audiobook non extraite."
        return result

    # Sprint D.39 : essayer tous les fichiers audio (1er + fallbacks)
    candidates = [source]
    fallbacks = result.pop("_audio_fallback_files", [])
    for fb in fallbacks:
        if fb != source and fb not in candidates:
            candidates.append(fb)

    last_warning = ""
    for idx, cand in enumerate(candidates):
        try:
            audio = MutagenFile(str(cand))
            if audio is None:
                last_warning = f"Audio non lisible par mutagen : {cand.name}"
                continue

            cover_data = None
            cover_ext = "jpg"

            # MP3 : APIC frames dans ID3
            try:
                id3 = ID3(str(cand))
                apic_frames = [v for k, v in id3.items() if k.startswith("APIC")]
                if apic_frames:
                    apic = apic_frames[0]
                    cover_data = apic.data
                    if "png" in (apic.mime or "").lower():
                        cover_ext = "png"
            except Exception:
                pass  # pas un ID3, ou pas d'APIC. Suite : essayons MP4.

            # M4B : MP4 'covr' atom
            if cover_data is None:
                covr = audio.tags.get("covr") if audio.tags else None
                if covr:
                    cover_data = bytes(covr[0])
                    if hasattr(covr[0], "imageformat") and covr[0].imageformat == 14:
                        cover_ext = "png"

            if cover_data:
                cover_path = output_dir / f"cover.{cover_ext}"
                cover_path.write_bytes(cover_data)
                # Sprint D.42 : recompresse la cover MP3 pour quota imgbb
                # (les ID3 covers sont souvent en pleine resolution ~1500px).
                _maybe_recompress_external_image(cover_path)
                result["cover"] = cover_path
                if idx > 0:
                    # Trace le fait qu'on a du recourir au fallback
                    result["warning"] = (
                        f"Cover extraite du fichier audio #{idx + 1} "
                        f"({cand.name}). Les pistes precedentes n'avaient "
                        f"pas de cover embedded."
                    )
                return result
            else:
                last_warning = (
                    f"Pas de cover embedded dans {cand.name}."
                )
        except Exception as e:
            last_warning = f"Audio cover extraction echec ({cand.name}) : {type(e).__name__} {e}"
            continue

    # Aucun candidat n'a donne de cover
    result["warning"] = last_warning or "Pas de cover embedded dans les tags audio."
    return result
