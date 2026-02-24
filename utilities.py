"""
utilities.py – Fonctions utilitaires pour Photo Selector.
"""

import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path

try:
    import imagehash
    from PIL import Image as PilImage
    _IMAGEHASH_OK = True
except ImportError:
    _IMAGEHASH_OK = False

from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS
from PyQt5.QtCore import QThread, pyqtSignal

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tiff", ".heic"}
DEFAULT_THRESHOLD = 8   # max Hamming distance


def extract_metadata(image_path: str) -> dict:
    """
    Extrait les métadonnées d'une photo.

    Args:
        image_path: Chemin absolu ou relatif vers le fichier image.

    Returns:
        Un dictionnaire contenant les métadonnées disponibles :
          - file_name       : nom du fichier
          - file_size_kb    : taille en kilo-octets
          - file_modified   : date de dernière modification du fichier
          - format          : format de l'image (JPEG, PNG, …)
          - mode            : mode couleur (RGB, RGBA, L, …)
          - width           : largeur en pixels
          - height          : hauteur en pixels
          - exif            : dictionnaire des balises EXIF (si disponibles)
          - gps             : dictionnaire des données GPS (si disponibles)

    Raises:
        FileNotFoundError: si le fichier n'existe pas.
        ValueError: si le fichier ne peut pas être ouvert comme image.
    """
    if not os.path.isfile(image_path):
        raise FileNotFoundError(f"Fichier introuvable : {image_path}")

    # --- Infos système du fichier ---
    stat = os.stat(image_path)
    metadata = {
        "file_name": os.path.basename(image_path),
        "file_size_kb": round(stat.st_size / 1024, 2),
        "file_modified": datetime.fromtimestamp(stat.st_mtime).strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
        "format": None,
        "mode": None,
        "width": None,
        "height": None,
        "exif": {},
        "gps": {},
    }

    # --- Infos image via Pillow ---
    try:
        with Image.open(image_path) as img:
            metadata["format"] = img.format
            metadata["mode"] = img.mode
            metadata["width"], metadata["height"] = img.size

            # Lecture des données EXIF brutes
            raw_exif = img._getexif()  # Disponible pour JPEG/TIFF
    except Exception as exc:
        raise ValueError(f"Impossible d'ouvrir l'image : {image_path}") from exc

    if not raw_exif:
        return metadata

    # --- Décodage des balises EXIF ---
    exif_data = {}
    gps_data = {}

    for tag_id, value in raw_exif.items():
        tag_name = TAGS.get(tag_id, tag_id)

        if tag_name == "GPSInfo":
            # Décodage des sous-balises GPS
            for gps_tag_id, gps_value in value.items():
                gps_tag_name = GPSTAGS.get(gps_tag_id, gps_tag_id)
                gps_data[gps_tag_name] = gps_value
        else:
            # Conversion des bytes non lisibles en chaîne
            if isinstance(value, bytes):
                try:
                    value = value.decode("utf-8", errors="replace")
                except Exception:
                    value = repr(value)
            exif_data[tag_name] = value

    metadata["exif"] = exif_data
    metadata["gps"] = gps_data

    new_meta = {
    "date" : metadata["exif"].get("DateTime"),
    "dimension" : (metadata["width"],metadata["height"]),
    "gps" : metadata["gps"],
    "user_comment" : metadata["exif"].get("UserComment"),
    }

    return new_meta


# ---------------------------------------------------------------------------
# Organisation des photos par tranche de temps
# ---------------------------------------------------------------------------

import shutil

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".heic", ".webp", ".bmp"}

def organize_by_period(
    source_dir: str,
    dest_dir: str | None = None,
    period: str = "month",
    copy: bool = False,
) -> dict[str, list[str]]:
    """
    Organise les photos d'un dossier dans des sous-dossiers par tranche de temps.

    Args:
        source_dir : Dossier contenant les photos à organiser.
        dest_dir   : Dossier de destination (par défaut : même dossier que source).
        period     : Granularité temporelle — "year" | "month" | "week" | "day".
        copy       : Si True, copie les fichiers ; sinon les déplace.

    Returns:
        Un dictionnaire { nom_dossier: [liste des fichiers déplacés] }.

    Raises:
        ValueError          : si `period` n'est pas une valeur reconnue.
        FileNotFoundError   : si `source_dir` n'existe pas.
    """
    VALID_PERIODS = ("year", "month", "week", "day")
    if period not in VALID_PERIODS:
        raise ValueError(f"period doit être parmi {VALID_PERIODS}, reçu : {period!r}")

    if not os.path.isdir(source_dir):
        raise FileNotFoundError(f"Dossier introuvable : {source_dir}")

    if dest_dir is None:
        dest_dir = source_dir

    # Formats de nommage selon la granularité
    _FOLDER_FMT = {
        "year":  "%Y",
        "month": "%Y-%m",
        "week":  "%Y-W%W",   # semaine ISO (lundi = début)
        "day":   "%Y-%m-%d",
    }
    fmt = _FOLDER_FMT[period]

    result: dict[str, list[str]] = {}

    for filename in os.listdir(source_dir):
        ext = os.path.splitext(filename)[1].lower()
        if ext not in SUPPORTED_EXTENSIONS:
            continue

        file_path = os.path.join(source_dir, filename)
        if not os.path.isfile(file_path):
            continue

        # --- Fichiers marqués comme supprimés → _trash/ ---
        if ".trashed" in filename.lower():
            trash_dir = os.path.join(dest_dir, "_trash")
            os.makedirs(trash_dir, exist_ok=True)
            trash_path = os.path.join(trash_dir, filename)
            if os.path.exists(trash_path):
                name_t, ext_t = os.path.splitext(filename)
                trash_path = os.path.join(trash_dir, f"{name_t}_dup{ext_t}")
            shutil.move(file_path, trash_path)
            result.setdefault("_trash", []).append(filename)
            continue

        # --- Récupération de la date ---
        folder_name = "date_inconnue"
        try:
            meta = extract_metadata(file_path)
            date_str = meta.get("date")          # format "YYYY:MM:DD HH:MM:SS"
            if date_str:
                dt = datetime.strptime(date_str, "%Y:%m:%d %H:%M:%S")
                folder_name = dt.strftime(fmt)
        except Exception:
            pass  # fichier sans EXIF → dossier "date_inconnue"

        # --- Création du dossier cible ---
        target_dir = os.path.join(dest_dir, folder_name)
        os.makedirs(target_dir, exist_ok=True)

        # --- Déplacement / copie (gestion des doublons) ---
        target_path = os.path.join(target_dir, filename)
        if os.path.exists(target_path):
            name, ext2 = os.path.splitext(filename)
            target_path = os.path.join(target_dir, f"{name}_dup{ext2}")

        if copy:
            shutil.copy2(file_path, target_path)
        else:
            shutil.move(file_path, target_path)
        result.setdefault(folder_name, []).append(filename)

    return result

# ---------------------------------------------------------------------------
# Background worker — organisation par période
# ---------------------------------------------------------------------------

class OrganizeWorker(QThread):
    progress = pyqtSignal(int, int)          # (fichiers traités, total)
    finished = pyqtSignal(dict)             # { nom_dossier: [fichiers] }
    error    = pyqtSignal(str)

    def __init__(
        self,
        source_dir: str,
        dest_dir: str | None = None,
        period: str = "month",
        copy: bool = False,
    ):
        super().__init__()
        self.source_dir = source_dir
        self.dest_dir   = dest_dir
        self.period     = period
        self.copy       = copy

    def run(self):
        try:
            VALID_PERIODS = ("year", "month", "week", "day")
            if self.period not in VALID_PERIODS:
                raise ValueError(
                    f"period doit être parmi {VALID_PERIODS}, reçu : {self.period!r}"
                )
            if not os.path.isdir(self.source_dir):
                raise FileNotFoundError(
                    f"Dossier introuvable : {self.source_dir}"
                )

            dest_dir = self.dest_dir or self.source_dir
            _FOLDER_FMT = {
                "year":  "%Y",
                "month": "%Y-%m",
                "week":  "%Y-W%W",
                "day":   "%Y-%m-%d",
            }
            fmt = _FOLDER_FMT[self.period]

            files = [
                f for f in os.listdir(self.source_dir)
                if os.path.splitext(f)[1].lower() in SUPPORTED_EXTENSIONS
                and os.path.isfile(os.path.join(self.source_dir, f))
            ]
            total = len(files)
            result: dict[str, list[str]] = {}

            for idx, filename in enumerate(files):
                self.progress.emit(idx + 1, total)
                file_path = os.path.join(self.source_dir, filename)

                # --- Fichiers marqués comme supprimés → _trash/ ---
                if ".trashed" in filename.lower():
                    trash_dir = os.path.join(dest_dir, "_trash")
                    os.makedirs(trash_dir, exist_ok=True)
                    trash_path = os.path.join(trash_dir, filename)
                    if os.path.exists(trash_path):
                        name_t, ext_t = os.path.splitext(filename)
                        trash_path = os.path.join(trash_dir, f"{name_t}_dup{ext_t}")
                    shutil.move(file_path, trash_path)
                    result.setdefault("_trash", []).append(filename)
                    continue

                folder_name = "date_inconnue"
                try:
                    meta = extract_metadata(file_path)
                    date_str = meta.get("date")
                    if date_str:
                        dt = datetime.strptime(date_str, "%Y:%m:%d %H:%M:%S")
                        folder_name = dt.strftime(fmt)
                except Exception:
                    pass

                target_dir  = os.path.join(dest_dir, folder_name)
                os.makedirs(target_dir, exist_ok=True)
                target_path = os.path.join(target_dir, filename)
                if os.path.exists(target_path):
                    name, ext2  = os.path.splitext(filename)
                    target_path = os.path.join(target_dir, f"{name}_dup{ext2}")

                if self.copy:
                    shutil.copy2(file_path, target_path)
                else:
                    shutil.move(file_path, target_path)
                result.setdefault(folder_name, []).append(filename)

            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


# ---------------------------------------------------------------------------
# Background worker — perceptual hash similarity scan
# ---------------------------------------------------------------------------

class ScanWorker(QThread):
    progress = pyqtSignal(int, int)                  # (scanned, total)
    groupsReady = pyqtSignal(list)                   # list[list[str]]
    error = pyqtSignal(str)

    def __init__(self, folder: str, threshold: int = DEFAULT_THRESHOLD):
        super().__init__()
        self.folder = folder
        self.threshold = threshold

    def run(self):
        if not _IMAGEHASH_OK:
            self.error.emit(
                "Les bibliothèques 'imagehash' et 'Pillow' sont requises.\n"
                "Installez-les avec : pip install imagehash Pillow"
            )
            return

        try:
            paths = [
                str(p) for p in Path(self.folder).rglob("*")
                if p.suffix.lower() in IMAGE_EXTS and p.is_file()
                and "_duplicates_trash" not in p.parts
            ]
            total = len(paths)

            # 1) Compute perceptual hashes
            hashes: list[tuple[str, object]] = []   # (path, dhash)
            for i, path in enumerate(paths):
                self.progress.emit(i + 1, total)
                h = self._phash(path)
                if h is not None:
                    hashes.append((path, h))

            # 2) Union-Find grouping by Hamming distance
            n = len(hashes)
            parent = list(range(n))

            def find(x):
                while parent[x] != x:
                    parent[x] = parent[parent[x]]
                    x = parent[x]
                return x

            def union(x, y):
                parent[find(x)] = find(y)

            for i in range(n):
                for j in range(i + 1, n):
                    dist = hashes[i][1] - hashes[j][1]
                    if dist <= self.threshold:
                        union(i, j)

            # 3) Build groups
            bucket: dict[int, list[str]] = defaultdict(list)
            for i, (path, _) in enumerate(hashes):
                bucket[find(i)].append(path)

            groups = [sorted(v) for v in bucket.values() if len(v) >= 2]
            self.groupsReady.emit(groups)
        except Exception as e:
            self.error.emit(str(e))

    @staticmethod
    def _phash(path: str):
        """Return imagehash.dhash for the image, or None on error."""
        try:
            with PilImage.open(path) as img:
                return imagehash.dhash(img)
        except Exception:
            return None


# ---------------------------------------------------------------------------
# Exemple d'utilisation (script lancé directement)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    import json

    if len(sys.argv) < 2:
        print("Usage : python utilities.py <chemin_image>")
        sys.exit(1)

    path = sys.argv[1]
    meta = extract_metadata(path)
    print(json.dumps(meta, indent=2, default=str, ensure_ascii=False))
