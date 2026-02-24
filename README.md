# 📸 Trieur de Photos

> Application de bureau pour détecter, gérer et organiser vos photos en double — développée avec PyQt5 (application perso).

---

[![Télécharger l'installeur](https://img.shields.io/badge/Télécharger-Installeur%20Windows-blue?style=for-the-badge&logo=windows)](https://github.com/mael-boutsoque/Trieur-de-photos/releases/download/v1.0/Installer.Trieur.de.Photo.exe)

---

## ✨ Fonctionnalités

| Fonctionnalité | Description |
|---|---|
| 🔍 **Détection de doublons** | Utilise le *perceptual hashing* (dHash) pour trouver les photos quasi-identiques, même si elles ont été rognées ou légèrement modifiées |
| 🖼️ **Visualisation par groupe** | Navigation groupe par groupe avec aperçu des miniatures côte à côte |
| ✅ **Sélection en un clic** | Cliquez sur la photo à conserver — les autres sont automatiquement marquées |
| 🗑️ **Corbeille sécurisée** | Les doublons sont déplacés dans `_duplicates_trash/` (pas de suppression définitive) |
| 🔄 **Restauration** | Remettez tous les fichiers déplacés dans le dossier d'origine en un clic |
| 🗂️ **Organisation par date** | Triez vos photos dans des sous-dossiers par année, mois, semaine ou jour (via les données EXIF) |
| 🎚️ **Seuil de similarité réglable** | Ajustez la sensibilité de détection avec un slider (distance de Hamming, 0–20) |
| 🔎 **Taille des miniatures** | Redimensionnez l'affichage des photos à la volée |

---

## 📁 Structure du projet

```
Photo_selector/
├── photo_selector.py        # Application principale (UI PyQt5)
├── utilities.py             # Moteur de scan, organisation EXIF, extraction de métadonnées
├── icone.ico                # Icône de l'application (Windows)
├── icone.png                # Icône (usage interne)
├── installation_script.iss  # Script Inno Setup pour créer l'installeur Windows
```

---

## 🚀 Installation & Lancement

### Option 1 — Exécutable Windows (sans Python)

Téléchargez et installer directement une version Release **`Installer Trieur de Photos.exe`**.

### Option 2 — Depuis les sources (Python)

**Prérequis :** Python 3.10+

```bash
# 1. Cloner le dépôt
git clone <url-du-repo>
cd Photo_selector

# 2. Installer les dépendances
pip install PyQt5 Pillow imagehash

# 3. Lancer l'application
python photo_selector.py
```

---

## 🧩 Dépendances

| Bibliothèque | Version recommandée | Rôle |
|---|---|---|
| `PyQt5` | ≥ 5.15 | Interface graphique |
| `Pillow` | ≥ 10.0 | Ouverture des images & lecture EXIF |
| `imagehash` | ≥ 4.3 | Calcul des hash perceptuels (dHash) |

```bash
pip install PyQt5 Pillow imagehash
```

---

## 🎮 Guide d'utilisation

### 1. Détecter les doublons

1. Cliquez sur **🔍 Détection des doublons**
2. Sélectionnez le dossier à analyser
3. Ajustez le **seuil de similarité** si nécessaire (valeur par défaut : 8)
   - `0` = images strictement identiques
   - `20` = images très approximativement similaires
4. Patientez le temps du scan (une barre de progression s'affiche)

### 2. Sélectionner les photos à garder

- Naviguez entre les groupes avec **◀ Précédent** / **Suivant ▶**
- **Cliquez sur la photo à conserver** dans chaque groupe — les autres sont marquées en rouge
- La photo choisie est encadrée en vert ✅

### 3. Valider la sélection

- **✅ Valider la sélection** : déplace tous les doublons des groupes traités dans `_duplicates_trash/`
- **🔄 Réinitialiser les doublons** : restore tous les fichiers depuis `_duplicates_trash/` vers le dossier d'origine

### 4. Organiser par date (optionnel)

1. Cliquez sur **🗂 Trier**
2. Choisissez le dossier source et la destination
3. Sélectionnez la granularité : **Année / Mois / Semaine / Jour**
4. Choisissez **Copier** ou **Déplacer**

Les photos sont triées en sous-dossiers nommés d'après leur date EXIF. Les photos sans date EXIF sont placées dans un dossier `date_inconnue/`.

---

## ⚙️ Paramètres techniques

### Algorithme de détection

La similarité est calculée par **dHash** (*difference hash*) : chaque image est réduite à une empreinte de 64 bits. La distance de Hamming entre deux empreintes mesure leur ressemblance.

Les images sont regroupées via un algorithme **Union-Find** pour former des clusters de photos similaires.

### Formats supportés

`.jpg` `.jpeg` `.png` `.bmp` `.gif` `.webp` `.tiff` `.heic`

### Données EXIF extraites

| Champ | Description |
|---|---|
| `date` | Date de prise de vue (`DateTime`) |
| `dimension` | Largeur × Hauteur en pixels |
| `gps` | Coordonnées GPS si disponibles |
| `user_comment` | Commentaire utilisateur embarqué |

---

## 🏗️ Créer l'installeur Windows

Le fichier `installation_script.iss` permet de générer un installeur avec [Inno Setup](https://jrsoftware.org/isinfo.php).

1. Compilez d'abord l'exécutable avec PyInstaller :
   ```bash
   pyinstaller --onefile --windowed --icon=icone.ico photo_selector.py
   ```
2. Ouvrez `installation_script.iss` dans Inno Setup Compiler
3. Compilez → un fichier `Installer Trieur de Photo.exe` est généré

---

## 👤 Auteur

**Maël Boutsoque**  
[Portfolio](https://maelboutsoque.framer.website/fr/)

---

## 📄 Licence

Usage non commercial — voir le script d'installation pour les détails.
