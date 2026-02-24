"""
photo_selector.py
─────────────────
Détecte les photos similaires dans un dossier (perceptual hash dHash),
les groupe et laisse l'utilisateur choisir quelle copie garder.
Les autres sont déplacées dans _duplicates_trash/ ou supprimées définitivement.
"""

import sys
import os
import shutil
from pathlib import Path

try:
    import imagehash
    from PIL import Image as PilImage
    _IMAGEHASH_OK = True
except ImportError:
    _IMAGEHASH_OK = False

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QScrollArea,
    QLabel, QPushButton, QFileDialog, QFrame,
    QHBoxLayout, QVBoxLayout, QFormLayout, QProgressBar,
    QMessageBox, QSizePolicy, QSpacerItem, QSlider,
    QComboBox, QCheckBox, QDialog, QDialogButtonBox
)
from PyQt5.QtGui import QPixmap, QFont, QColor, QPainter, QBrush, QIcon
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QSize, QTimer

from utilities import organize_by_period, OrganizeWorker, ScanWorker, DEFAULT_THRESHOLD, IMAGE_EXTS

THUMB = 260          # thumbnail size (px)
CARD_W = THUMB
CARD_H = THUMB

# ═══════════════════════════════════════════════════════════
#  Single image card
# ═══════════════════════════════════════════════════════════

class ImageCard(QFrame):
    clicked = pyqtSignal(object)   # emits self

    STATE_NEUTRAL  = "neutral"
    STATE_KEEP     = "keep"
    STATE_DELETE   = "delete"

    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self.path = path
        self._state = self.STATE_NEUTRAL
        self.setObjectName("ImageCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(path)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.img_label = QLabel()
        self.img_label.setAlignment(Qt.AlignCenter)
        self.img_label.setObjectName("ImgLabel")
        layout.addWidget(self.img_label, alignment=Qt.AlignCenter)

        self._load_thumb()

    def _load_thumb(self):
        px = QPixmap(self.path)
        if not px.isNull():
            px = px.scaled(THUMB, THUMB, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            w, h = px.width(), px.height()
        else:
            w, h = THUMB, THUMB
        self.img_label.setFixedSize(w, h)
        self.setFixedSize(w, h)
        self.img_label.setPixmap(px)

    def set_state(self, state: str):
        self._state = state
        self._refresh_style()

    def _refresh_style(self):
        if self._state == self.STATE_KEEP:
            self.setStyleSheet("""
                QFrame#ImageCard {
                    background: #0d2b1a;
                    border-radius: 10px;
                    border: 2.5px solid #2cb67d;
                }
            """)
        elif self._state == self.STATE_DELETE:
            self.setStyleSheet("""
                QFrame#ImageCard {
                    background: #2b0d0d;
                    border-radius: 10px;
                }
            """)
        else:
            self.setStyleSheet("""
                QFrame#ImageCard {
                    background: #0f3460;
                    border-radius: 10px;
                }
            """)

    def resize_to(self, size: int):
        """Dynamically resize the card to match the actual image aspect ratio."""
        px = QPixmap(self.path)
        if not px.isNull():
            px = px.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            w, h = px.width(), px.height()
        else:
            w, h = size, size
        self.img_label.setFixedSize(w, h)
        self.setFixedSize(w, h)
        self.img_label.setPixmap(px)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self)


# ═══════════════════════════════════════════════════════════
#  One duplicate group row
# ═══════════════════════════════════════════════════════════
class DuplicateGroupWidget(QFrame):
    selectionChanged = pyqtSignal()
    photoChosen = pyqtSignal(str)   # chemin de la photo à GARDER

    def __init__(self, paths: list, group_index: int, parent=None):
        super().__init__(parent)
        self.paths = paths
        self.group_index = group_index
        self.cards: list[ImageCard] = []
        self.selected_path: str | None = None

        self.setObjectName("GroupFrame")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 10, 14, 10)
        root.setSpacing(8)

        # Header
        header = QLabel(f"  Groupe #{group_index + 1}  —  {len(paths)} images similaires  •  Cliquez sur la photo à garder")
        header.setObjectName("GroupHeader")
        root.addWidget(header)

        # Cards row
        cards_row = QHBoxLayout()
        cards_row.setSpacing(12)
        cards_row.setContentsMargins(0, 0, 0, 0)

        for path in paths:
            card = ImageCard(path)
            card.clicked.connect(self._on_card_clicked)
            self.cards.append(card)
            cards_row.addWidget(card)

        cards_row.addStretch()
        root.addLayout(cards_row)

    def _on_card_clicked(self, card: ImageCard):
        """Flash vert bref sur la photo choisie, puis émet photoChosen."""
        self.selected_path = card.path
        # Marquer visuellement
        for c in self.cards:
            c.set_state(ImageCard.STATE_DELETE)
        card.set_state(ImageCard.STATE_KEEP)
        # Laisser 250 ms de feedback visuel avant de passer au suivant
        QTimer.singleShot(250, lambda: self.photoChosen.emit(card.path))

    def _apply_selection(self):
        for card in self.cards:
            if card.path == self.selected_path:
                card.set_state(ImageCard.STATE_KEEP)
            else:
                card.set_state(ImageCard.STATE_DELETE)

    def get_to_delete(self) -> list[str]:
        return [p for p in self.paths if p != self.selected_path]


# ═══════════════════════════════════════════════════════════
#  Organise dialog
# ═══════════════════════════════════════════════════════════

class OrganizeDialog(QDialog):
    """Pop-up permettant de configurer et lancer l'organisation par période."""

    PERIOD_MAP = {"Année": "year", "Mois": "month", "Semaine": "week", "Jour": "day"}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🗂  Trier par date")
        self.setMinimumWidth(420)
        self._dest: str = ""

        root = QVBoxLayout(self)
        root.setSpacing(14)

        # ── Champ source ──
        form = QFormLayout()
        form.setSpacing(8)

        self._source_label = QLabel("(aucun)")
        self._source_label.setWordWrap(True)
        src_btn = QPushButton("📂  Choisir…")
        src_btn.clicked.connect(self._pick_source)
        src_row = QHBoxLayout()
        src_row.addWidget(self._source_label)
        src_row.addWidget(src_btn)
        form.addRow("Dossier source :", src_row)

        self._dest_label = QLabel("(même dossier)")
        self._dest_label.setWordWrap(True)
        dest_btn = QPushButton("📁  Choisir…")
        dest_btn.clicked.connect(self._pick_dest)
        dest_row = QHBoxLayout()
        dest_row.addWidget(self._dest_label)
        dest_row.addWidget(dest_btn)
        form.addRow("Destination :", dest_row)

        self.period_combo = QComboBox()
        self.period_combo.addItems(list(self.PERIOD_MAP.keys()))
        self.period_combo.setCurrentIndex(1)  # Mois
        form.addRow("Grouper par :", self.period_combo)

        self.copy_check = QCheckBox("Copier (ne pas déplacer)")
        self.copy_check.setChecked(True)
        form.addRow("", self.copy_check)

        root.addLayout(form)

        # ── Boutons OK / Annuler ──
        btns = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
            Qt.Horizontal, self
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

    # ── helpers ─────────────────────────────────────────────
    def _pick_source(self):
        folder = QFileDialog.getExistingDirectory(self, "Dossier de photos à organiser")
        if folder:
            self._source = folder
            short = folder if len(folder) <= 45 else "…" + folder[-43:]
            self._source_label.setText(short)

    def _pick_dest(self):
        folder = QFileDialog.getExistingDirectory(self, "Dossier de destination")
        if folder:
            self._dest = folder
            short = folder if len(folder) <= 45 else "…" + folder[-43:]
            self._dest_label.setText(short)
        else:
            self._dest = ""
            self._dest_label.setText("(même dossier)")

    # ── public API ──────────────────────────────────────────
    @property
    def source(self) -> str:
        return getattr(self, "_source", "")

    @property
    def dest(self) -> str:
        return self._dest

    @property
    def period(self) -> str:
        return self.PERIOD_MAP[self.period_combo.currentText()]

    @property
    def copy(self) -> bool:
        return self.copy_check.isChecked()


# ═══════════════════════════════════════════════════════════
#  Main window
# ═══════════════════════════════════════════════════════════
class PhotoSelectorWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Trieur de photos")
        self.setWindowIcon(QIcon(str(Path(__file__).parent / "icone.png")))
        self.resize(1100, 750)
        self.group_widgets: list[DuplicateGroupWidget] = []
        self._current_idx: int = 0          # index du groupe affiché
        self._worker: ScanWorker | None = None
        self._scan_folder = ""
        self._threshold = DEFAULT_THRESHOLD
        default_image_size = 50
        self._thumb_size = default_image_size

        self._build_ui()
        self._apply_stylesheet()
        self.size_slider.setValue(50)
        self._on_size_label_changed(50)

    # ── UI ────────────────────────────────────────────────
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        self._org_dest: str = ""

        # ── Scan bar ──
        top = QHBoxLayout()

        self.scan_btn = QPushButton("🔍 Detection des doublons")
        self.scan_btn.setObjectName("PrimaryBtn")
        self.scan_btn.clicked.connect(self._start_scan)
        top.addWidget(self.scan_btn)

        self.org_btn = QPushButton("🗂  Trier")
        self.org_btn.setObjectName("NavBtn")
        self.org_btn.clicked.connect(self._open_organize_dialog)
        top.addWidget(self.org_btn)

        top.addSpacing(16)

        # Threshold slider
        thresh_label_left = QLabel("Similarité :")
        thresh_label_left.setObjectName("StatusLabel")
        top.addWidget(thresh_label_left)

        self.thresh_slider = QSlider(Qt.Horizontal)
        self.thresh_slider.setRange(0, 20)
        self.thresh_slider.setValue(DEFAULT_THRESHOLD)
        self.thresh_slider.setFixedWidth(120)
        self.thresh_slider.setObjectName("ThreshSlider")
        self.thresh_slider.valueChanged.connect(self._on_threshold_changed)
        top.addWidget(self.thresh_slider)

        self.thresh_val_label = QLabel(f"{DEFAULT_THRESHOLD}")
        self.thresh_val_label.setObjectName("StatusLabel")
        self.thresh_val_label.setFixedWidth(24)
        top.addWidget(self.thresh_val_label)

        top.addSpacing(20)

        # Size slider
        size_label = QLabel("Taille :")
        size_label.setObjectName("StatusLabel")
        top.addWidget(size_label)

        self.size_slider = QSlider(Qt.Horizontal)
        self.size_slider.setRange(0, 100)
        self.size_slider.setValue(50)
        self.size_slider.setFixedWidth(130)
        self.size_slider.setObjectName("ThreshSlider")
        self.size_slider.valueChanged.connect(self._on_size_label_changed)
        self.size_slider.sliderReleased.connect(self._on_size_released)
        top.addWidget(self.size_slider)

        self.size_val_label = QLabel(f"{THUMB} px")
        self.size_val_label.setObjectName("StatusLabel")
        self.size_val_label.setFixedWidth(50)
        top.addWidget(self.size_val_label)

        top.addStretch()

        self.status_label = QLabel("Aucun dossier sélectionné")
        self.status_label.setObjectName("StatusLabel")
        top.addWidget(self.status_label)

        root.addLayout(top)

        # ── Progress bar (hidden by default) ──
        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("ScanProgress")
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.hide()
        root.addWidget(self.progress_bar)

        # ── Separator ──
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setObjectName("Separator")
        root.addWidget(sep)


        # ── Navigation bar (groupe X / N) ──
        nav = QHBoxLayout()
        nav.setSpacing(10)

        self.prev_btn = QPushButton("◀  Précédent")
        self.prev_btn.setObjectName("NavBtn")
        self.prev_btn.setEnabled(False)
        self.prev_btn.clicked.connect(self._go_prev)
        nav.addWidget(self.prev_btn)

        self.nav_label = QLabel("")
        self.nav_label.setObjectName("NavLabel")
        self.nav_label.setAlignment(Qt.AlignCenter)
        nav.addWidget(self.nav_label, stretch=1)

        self.next_btn = QPushButton("Suivant  ▶")
        self.next_btn.setObjectName("NavBtn")
        self.next_btn.setEnabled(False)
        self.next_btn.clicked.connect(self._go_next)
        nav.addWidget(self.next_btn)

        root.addLayout(nav)

        # ── Scroll area — single group view ──
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setObjectName("ScrollArea")

        # Container that holds either the hint label or one group widget
        self.group_container = QWidget()
        self.group_container.setObjectName("GroupsWidget")
        self.group_container_layout = QVBoxLayout(self.group_container)
        self.group_container_layout.setContentsMargins(8, 8, 8, 8)
        self.group_container_layout.setSpacing(0)

        self.hint_label = QLabel(
            "📂  Choisissez un dossier pour détecter les photos similaires"
        )
        self.hint_label.setAlignment(Qt.AlignCenter)
        self.hint_label.setObjectName("HintLabel")
        self.group_container_layout.addWidget(self.hint_label)
        self.group_container_layout.addStretch()

        self.scroll.setWidget(self.group_container)
        root.addWidget(self.scroll, stretch=1)


        # ── Global footer bar ──
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setObjectName("Separator")
        root.addWidget(sep2)

        bottom = QHBoxLayout()
        bottom.setSpacing(12)

        self.summary_label = QLabel("")
        self.summary_label.setObjectName("SummaryLabel")
        bottom.addWidget(self.summary_label)

        bottom.addStretch()

        self.reset_btn = QPushButton("🔄  Réinitialiser les doublons")
        self.reset_btn.setObjectName("NavBtn")
        self.reset_btn.setEnabled(False)
        self.reset_btn.clicked.connect(self._reset_all_selections)
        bottom.addWidget(self.reset_btn)

        self.move_btn = QPushButton("✅  Valider la sélection")
        self.move_btn.setObjectName("MoveBtn")
        self.move_btn.setEnabled(False)
        self.move_btn.clicked.connect(self._execute_action)
        bottom.addWidget(self.move_btn)

        root.addLayout(bottom)
        

    # ── Threshold ──────────────────────────────────────────
    def _on_threshold_changed(self, value: int):
        self._threshold = value
        self.thresh_val_label.setText(str(value))

    # ── Image size ─────────────────────────────────────────
    def get_size_coef(self,value=0):
        if value:
            return (100 + value) * 5
        else:
            return (100 + self.size_slider.value()) * 5
    
    def _on_size_label_changed(self, value: int):
        """Met à jour le label en temps réel sans recharger les images."""
        self._thumb_size = self.get_size_coef(value)
        self.size_val_label.setText(f"{value} px")

    def _on_size_released(self):
        """Redimensionne les images uniquement quand le slider est relâché."""
        value = (self.get_size_coef())
        for gw in self.group_widgets:
            for card in gw.cards:
                card.resize_to(value)

    # ── Scan ──────────────────────────────────────────────
    def _start_scan(self):
        folder = QFileDialog.getExistingDirectory(self, "Choisir un dossier")
        if not folder:
            return
        self._scan_folder = folder
        self._clear_groups()
        self.scan_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        self.progress_bar.show()
        self.status_label.setText("Scan en cours…")
        self.hint_label.setText("⏳  Analyse des fichiers en cours…")
        self.hint_label.show()

        self._worker = ScanWorker(folder, threshold=self._threshold)
        self._worker.progress.connect(self._on_progress)
        self._worker.groupsReady.connect(self._on_groups_ready)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_progress(self, done: int, total: int):
        if total > 0:
            self.progress_bar.setMaximum(total)
            self.progress_bar.setValue(done)
            self.status_label.setText(f"Analyse : {done} / {total} fichiers…")

    def _on_groups_ready(self, groups: list):
        self.progress_bar.hide()
        self.scan_btn.setEnabled(True)

        if not groups:
            self.hint_label.setText("✅  Aucune image similaire trouvée dans ce dossier.")
            self.hint_label.show()
            self.status_label.setText("Scan terminé — aucune similarité détectée")
            self._update_ui()
            return

        for i, paths in enumerate(groups):
            gw = DuplicateGroupWidget(paths, i)
            gw.photoChosen.connect(lambda path, g=gw: self._on_photo_chosen(g, path))
            self.group_widgets.append(gw)
            if self._thumb_size != THUMB:
                for card in gw.cards:
                    card.resize_to(self._thumb_size)

        n_groups = len(groups)
        n_files = sum(len(g) for g in groups)
        self.status_label.setText(
            f"✅  {n_groups} groupe(s) similaires · {n_files} fichiers concernés"
        )
        self._current_idx = 0
        self._show_current()

    def _on_photo_chosen(self, gw: "DuplicateGroupWidget", chosen_path: str):
        """Déplace les doublons et passe au groupe suivant."""
        to_delete = [p for p in gw.paths if p != chosen_path]
        errors = self._do_delete(to_delete, delete=False)
        if errors:
            QMessageBox.warning(
                self, "Erreurs",
                f"{len(errors)} erreur(s) :\n" + "\n".join(errors[:5])
            )

        if gw in self.group_widgets:
            idx = self.group_widgets.index(gw)
            self.group_widgets.pop(idx)
            if self._current_idx >= len(self.group_widgets) and self._current_idx > 0:
                self._current_idx -= 1

        if not self.group_widgets:
            QMessageBox.information(self, "Terminé", "✅  Tous les groupes ont été traités !")

        self._show_current()

    def _on_error(self, msg: str):
        self.progress_bar.hide()
        self.scan_btn.setEnabled(True)
        self.status_label.setText("Erreur lors du scan")
        QMessageBox.critical(self, "Erreur", f"Scan échoué :\n{msg}")

    # ── Navigation ────────────────────────────────────────
    def _show_current(self):
        """Display the group at _current_idx in the scroll area."""
        # Remove whatever is currently shown (all children of layout)
        while self.group_container_layout.count():
            item = self.group_container_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)

        if not self.group_widgets:
            self.hint_label = type(self.hint_label)(  # re-create after reparenting
                "📂  Choisissez un dossier pour détecter les photos similaires"
            )
            self.hint_label.setAlignment(Qt.AlignCenter)
            self.hint_label.setObjectName("HintLabel")
            self.group_container_layout.addWidget(self.hint_label)
            self.group_container_layout.addStretch()
            self._update_ui()
            return

        gw = self.group_widgets[self._current_idx]
        self.group_container_layout.addWidget(gw)
        self.group_container_layout.addStretch()
        self._update_ui()

    def _go_prev(self):
        if self._current_idx > 0:
            self._current_idx -= 1
            self._show_current()

    def _go_next(self):
        if self._current_idx < len(self.group_widgets) - 1:
            self._current_idx += 1
            self._show_current()

    def _skip_group(self):
        """Ignore this group (no deletion) and move to next."""
        if not self.group_widgets:
            return
        self.group_widgets.pop(self._current_idx)
        if self._current_idx >= len(self.group_widgets) and self._current_idx > 0:
            self._current_idx -= 1
        self._show_current()

    def _reset_all_selections(self):
        """Remet tous les fichiers de _duplicates_trash dans le dossier source."""
        if not self._scan_folder:
            QMessageBox.warning(self, "Aucun dossier", "Aucun dossier scanné en mémoire.")
            return

        trash_dir = os.path.join(self._scan_folder, "_duplicates_trash")
        if not os.path.isdir(trash_dir):
            QMessageBox.information(self, "Rien à restaurer",
                                    "Le dossier _duplicates_trash est introuvable ou vide.")
            return

        files = [f for f in os.listdir(trash_dir)
                 if os.path.isfile(os.path.join(trash_dir, f))]
        if not files:
            QMessageBox.information(self, "Rien à restaurer",
                                    "_duplicates_trash est vide.")
            return

        errors = []
        restored = 0
        for filename in files:
            src = os.path.join(trash_dir, filename)
            dst = os.path.join(self._scan_folder, filename)
            if os.path.exists(dst):
                base, ext = os.path.splitext(filename)
                dst = os.path.join(self._scan_folder, f"{base}_restored{ext}")
            try:
                shutil.move(src, dst)
                restored += 1
            except Exception as e:
                errors.append(f"{filename} : {e}")

        if errors:
            QMessageBox.warning(self, "Erreurs",
                                f"{restored} fichier(s) restauré(s), "
                                f"{len(errors)} erreur(s) :\n" + "\n".join(errors[:5]))
        else:
            QMessageBox.information(self, "Restauration terminée",
                                    f"✅  {restored} fichier(s) remis dans\n{self._scan_folder}")

        # Relancer le scan pour refléter l'état réel
        self._start_scan_same_folder()

    # ── Groups management ─────────────────────────────────
    def _clear_groups(self):
        # Detach current widget from container before clearing
        while self.group_container_layout.count():
            item = self.group_container_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
        for gw in self.group_widgets:
            gw.setParent(None)
        self.group_widgets.clear()
        self._current_idx = 0
        # Re-add hint
        self.hint_label.setText("📂  Choisissez un dossier pour détecter les photos similaires")
        self.group_container_layout.addWidget(self.hint_label)
        self.hint_label.show()
        self.group_container_layout.addStretch()
        self._update_ui()

    def _update_ui(self):
        """Refresh navigation labels, buttons, and summary."""
        n = len(self.group_widgets)
        has = n > 0

        # Nav bar
        if has:
            self.nav_label.setText(
                f"<b>Groupe {self._current_idx + 1}</b> / {n}"
            )
        else:
            self.nav_label.setText("")
        self.prev_btn.setEnabled(has and self._current_idx > 0)
        self.next_btn.setEnabled(has and self._current_idx < n - 1)

        # Boutons
        self.reset_btn.setEnabled(has)

        # Global buttons & summary
        self.move_btn.setEnabled(has)
        if has:
            n_dup = sum(len(gw.paths) - 1 for gw in self.group_widgets)
            self.summary_label.setText(
                f"<b>{n}</b> groupe(s) restant(s) · "
                f"<b>{n_dup}</b> doublon(s) à déplacer au total"
            )
        else:
            self.summary_label.setText("")

    def _update_summary(self):
        self._update_ui()

    def _collect_to_delete(self) -> list[str]:
        result = []
        for gw in self.group_widgets:
            result.extend(gw.get_to_delete())
        return result

    # ── Action ────────────────────────────────────────────
    def _apply_group(self):
        """Déplace les copies du groupe courant dans _duplicates_trash et passe au suivant."""
        if not self.group_widgets:
            return
        gw = self.group_widgets[self._current_idx]
        to_delete = gw.get_to_delete()
        if not to_delete:
            self._skip_group()
            return

        errors = self._do_delete(to_delete, delete=False)
        if errors:
            QMessageBox.warning(
                self, "Erreurs",
                f"{len(errors)} erreur(s) :\n" + "\n".join(errors[:5])
            )

        self.group_widgets.pop(self._current_idx)
        if self._current_idx >= len(self.group_widgets) and self._current_idx > 0:
            self._current_idx -= 1

        if not self.group_widgets:
            QMessageBox.information(self, "Terminé", "✅  Tous les groupes ont été traités !")

        self._show_current()

    def _execute_action(self):
        """Déplace TOUS les doublons restants dans _duplicates_trash."""
        to_delete = self._collect_to_delete()
        if not to_delete:
            QMessageBox.information(self, "Rien à faire", "Aucun fichier à déplacer.")
            return

        reply = QMessageBox.question(
            self,
            "Confirmer",
            f"Déplacer {len(to_delete)} fichier(s) dans _duplicates_trash/ ?"
            f" ({len(self.group_widgets)} groupe(s))\n\n" +
            "\n".join(f"  • {os.path.basename(p)}" for p in to_delete[:10]) +
            (f"\n  … et {len(to_delete) - 10} autre(s)" if len(to_delete) > 10 else ""),
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        errors = self._do_delete(to_delete, delete=False)
        if errors:
            QMessageBox.warning(
                self, "Erreurs",
                f"{len(errors)} erreur(s) :\n" + "\n".join(errors[:5])
            )
        else:
            QMessageBox.information(
                self, "Terminé",
                f"✅  {len(to_delete)} fichier(s) déplacé(s) avec succès."
            )
        self._start_scan_same_folder()

    def _do_delete(self, paths: list, delete: bool) -> list:
        """Move or delete a list of paths. Returns list of error strings."""
        errors = []
        if delete:
            for p in paths:
                try:
                    os.remove(p)
                except Exception as e:
                    errors.append(f"{p}: {e}")
        else:
            trash = os.path.join(self._scan_folder, "_duplicates_trash")
            os.makedirs(trash, exist_ok=True)
            for p in paths:
                try:
                    dest = os.path.join(trash, os.path.basename(p))
                    if os.path.exists(dest):
                        base, ext = os.path.splitext(os.path.basename(p))
                        cnt = 1
                        while os.path.exists(dest):
                            dest = os.path.join(trash, f"{base}_{cnt}{ext}")
                            cnt += 1
                    shutil.move(p, dest)
                except Exception as e:
                    errors.append(f"{p}: {e}")
        return errors

    def _start_scan_same_folder(self):
        if not self._scan_folder:
            return
        self._clear_groups()
        self.scan_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        self.progress_bar.show()
        self.status_label.setText("Nouveau scan…")
        self.hint_label.setText("⏳  Analyse en cours…")
        self.hint_label.show()
        self._worker = ScanWorker(self._scan_folder, threshold=self._threshold)
        self._worker.progress.connect(self._on_progress)
        self._worker.groupsReady.connect(self._on_groups_ready)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    # ── Organize by period ────────────────────────────────
    def _open_organize_dialog(self):
        """Ouvre le pop-up de configuration et lance OrganizeWorker si accepté."""
        dlg = OrganizeDialog(self)
        if dlg.exec_() != OrganizeDialog.Accepted:
            return
        if not dlg.source:
            QMessageBox.warning(self, "Source manquante",
                                "Veuillez choisir un dossier source.")
            return

        self.org_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        self.progress_bar.show()
        self.status_label.setText("⏳  Organisation en cours…")

        self._org_worker = OrganizeWorker(
            dlg.source,
            dest_dir=dlg.dest or None,
            period=dlg.period,
            copy=dlg.copy,
        )
        self._org_worker.progress.connect(self._on_org_progress)
        self._org_worker.finished.connect(self._on_org_finished)
        self._org_worker.error.connect(self._on_org_error)
        self._org_worker.start()

    def _on_org_progress(self, done: int, total: int):
        if total > 0:
            self.progress_bar.setMaximum(total)
            self.progress_bar.setValue(done)
            self.status_label.setText(f"Organisation : {done} / {total} fichiers…")

    def _on_org_finished(self, result: dict):
        self.progress_bar.hide()
        self.org_btn.setEnabled(True)
        n_folders = len(result)
        n_files   = sum(len(v) for v in result.values())
        verb      = "copiées" if (self._org_worker and self._org_worker.copy) else "déplacées"
        self.status_label.setText(f"✅  {n_files} photo(s) {verb} dans {n_folders} dossier(s)")

        detail_lines = [
            f"  📁 {name}  ({len(files)} fichier(s))"
            for name, files in sorted(result.items())
        ]
        from itertools import islice
        QMessageBox.information(
            self,
            "Organisation terminée",
            f"✅  {n_files} photo(s) {verb} dans {n_folders} dossier(s).\n\n"
            + "\n".join(islice(detail_lines, 20))
            + (f"\n  … et {n_folders - 20} autre(s) dossier(s)" if n_folders > 20 else "")
        )

    def _on_org_error(self, msg: str):
        self.progress_bar.hide()
        self.org_btn.setEnabled(True)
        self.status_label.setText("Erreur lors de l'organisation")
        QMessageBox.critical(self, "Erreur", f"Organisation échouée :\n{msg}")

    # ── Stylesheet ────────────────────────────────────────
    # (CSS added below)
    def _apply_stylesheet(self):
        self.setStyleSheet("""
        /* ── Base ──────────────────────────────────────── */
        QMainWindow, QWidget {
            background: #0d0d12;
            color: #e2e4f0;
            font-family: 'Segoe UI', 'Inter', 'Arial', sans-serif;
            font-size: 13px;
        }

        /* ── Scan / Primary button ────────────────────── */
        QPushButton#PrimaryBtn {
            background: #6366f1;
            color: #ffffff;
            border: none;
            border-radius: 10px;
            padding: 10px 24px;
            font-weight: 700;
            font-size: 13px;
            letter-spacing: 0.3px;
        }
        QPushButton#PrimaryBtn:hover  { background: #4f52d4; }
        QPushButton#PrimaryBtn:pressed{ background: #3e40b8; }
        QPushButton#PrimaryBtn:disabled{ background: #23232f; color: #44475a; }

        /* ── Green / Validate button ──────────────────── */
        QPushButton#MoveBtn {
            background: #10b981;
            color: #ffffff;
            border: none;
            border-radius: 10px;
            padding: 10px 20px;
            font-weight: 700;
        }
        QPushButton#MoveBtn:hover  { background: #0d9e6e; }
        QPushButton#MoveBtn:pressed{ background: #0a7d57; }
        QPushButton#MoveBtn:disabled{ background: #1a2920; color: #2e5040; }

        /* ── Neutral / Nav button ─────────────────────── */
        QPushButton#NavBtn {
            background: #18181f;
            color: #c5c8e0;
            border: 1px solid #2e2e40;
            border-radius: 10px;
            padding: 8px 18px;
            font-weight: 600;
        }
        QPushButton#NavBtn:hover  { background: #23233a; border-color: #6366f1; color: #e2e4f0; }
        QPushButton#NavBtn:pressed{ background: #1a1a2e; }
        QPushButton#NavBtn:disabled{ background: #111117; color: #2e3050; border-color: #1e1e28; }

        /* ── Organiser button ─────────────────────────── */
        QPushButton#OrgBtn {
            background: #0ea5e9;
            color: #ffffff;
            border: none;
            border-radius: 10px;
            padding: 8px 20px;
            font-weight: 700;
        }
        QPushButton#OrgBtn:hover  { background: #0b8fc9; }
        QPushButton#OrgBtn:pressed{ background: #0872a3; }

        /* ── Sliders ──────────────────────────────────── */
        QSlider#ThreshSlider::groove:horizontal {
            height: 4px;
            background: #23232f;
            border-radius: 2px;
        }
        QSlider#ThreshSlider::handle:horizontal {
            background: #6366f1;
            width: 16px; height: 16px;
            margin: -6px 0;
            border-radius: 8px;
            border: 2px solid #0d0d12;
        }
        QSlider#ThreshSlider::sub-page:horizontal {
            background: #6366f1;
            border-radius: 2px;
        }

        /* ── Labels ───────────────────────────────────── */
        QLabel#StatusLabel  { color: #64678a; font-size: 12px; }
        QLabel#SummaryLabel { color: #64678a; font-size: 12px; }
        QLabel#NavLabel     { color: #e2e4f0; font-size: 14px; font-weight: 700; }
        QLabel#HintLabel {
            color: #2a2a40;
            font-size: 17px;
            font-style: italic;
            padding: 80px;
        }
        QLabel#ImgLabel { background: transparent; border-radius: 8px; }

        /* ── Group frame ──────────────────────────────── */
        QFrame#GroupFrame {
            background: #13131a;
            border-radius: 14px;
            border: 1px solid #22223a;
        }
        QLabel#GroupHeader {
            color: #6366f1;
            font-weight: 700;
            font-size: 13px;
            letter-spacing: 0.2px;
        }

        /* ── Separators ───────────────────────────────── */
        QFrame#Separator { color: #1a1a25; max-height: 1px; background: #1a1a25; }

        /* ── Scroll area ──────────────────────────────── */
        QScrollArea#ScrollArea { border: none; background: #0d0d12; border-radius: 12px; }
        QWidget#GroupsWidget   { background: #0d0d12; }
        QScrollBar:vertical { background: #0d0d12; width: 6px; margin: 0; }
        QScrollBar::handle:vertical { background: #2a2a3a; border-radius: 3px; min-height: 24px; }
        QScrollBar::handle:vertical:hover { background: #6366f1; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }

        /* ── Progress bar ─────────────────────────────── */
        QProgressBar#ScanProgress {
            background: #18181f;
            border: none;
            border-radius: 3px;
        }
        QProgressBar#ScanProgress::chunk {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #6366f1, stop:1 #10b981);
            border-radius: 3px;
        }

        /* ── ComboBox ─────────────────────────────────── */
        QComboBox {
            background: #18181f;
            color: #e2e4f0;
            border: 1px solid #2e2e40;
            border-radius: 8px;
            padding: 5px 10px;
        }
        QComboBox:hover { border-color: #6366f1; }
        QComboBox::drop-down { border: none; width: 20px; }
        QComboBox QAbstractItemView {
            background: #18181f;
            color: #e2e4f0;
            selection-background-color: #6366f1;
            border: 1px solid #2e2e40;
            border-radius: 6px;
        }

        /* ── CheckBox ─────────────────────────────────── */
        QCheckBox { color: #9496b8; spacing: 7px; }
        QCheckBox::indicator {
            width: 16px; height: 16px;
            border: 1.5px solid #2e2e40;
            border-radius: 5px;
            background: #18181f;
        }
        QCheckBox::indicator:checked { background: #6366f1; border-color: #6366f1; }
        QCheckBox::indicator:hover   { border-color: #6366f1; }

        /* ── Dialog ───────────────────────────────────── */
        QDialog {
            background: #13131a;
            border: 1px solid #22223a;
            border-radius: 14px;
        }
        QDialogButtonBox QPushButton {
            border-radius: 8px;
            padding: 7px 20px;
            font-weight: 600;
            min-width: 80px;
        }
        """)




# ═══════════════════════════════════════════════════════════
#  Entry point
# ═══════════════════════════════════════════════════════════
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = PhotoSelectorWindow()
    win.show()
    sys.exit(app.exec_())
