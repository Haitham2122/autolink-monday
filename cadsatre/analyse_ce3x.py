# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                    ANALYSE THERMIQUE CE3X - CADASTRE ESPAGNOL                ║
║                                                                              ║
║  Script d'extraction et d'analyse des données cadastrales pour CE3X         ║
║  Sources: API OVC + WFS INSPIRE + Scraping HTML sedecatastro.gob.es         ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import requests
import re
import json
import math
import sys
import os
import logging
import time
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Tuple
from enum import Enum

# ============================================================================
# CONFIGURATION
# ============================================================================

# Logger
logger = logging.getLogger('analyse_ce3x')
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter('[%(levelname)s] %(message)s'))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# URLs des services
URL_CPMRC = "http://ovc.catastro.meh.es/ovcservweb/OVCSWLocalizacionRC/OVCCoordenadas.asmx/Consulta_CPMRC"
URL_WFS_BU = "http://ovc.catastro.meh.es/INSPIRE/wfsBU.aspx"
URL_WFS_CP = "http://ovc.catastro.meh.es/INSPIRE/wfsCP.aspx"
URL_SEDE = "https://www1.sedecatastro.gob.es/CYCBienInmueble"
URL_FXCC_KML = "https://www1.sedecatastro.gob.es/Cartografia/FXCC/FXCC_KML.aspx"

# Session HTTP réutilisable
SESSION = requests.Session()
SESSION.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
})

# Délai entre requêtes successives (rate limiting)
DELAI_ENTRE_REQUETES = 0.5  # secondes
_derniere_requete = 0.0


def faire_requete(url: str, params: Optional[Dict] = None, timeout: int = 15, max_retries: int = 3) -> Optional[requests.Response]:
    """
    Effectue une requête HTTP GET avec retry et backoff exponentiel.
    Inclut un rate limiting pour respecter les serveurs gouvernementaux.
    """
    global _derniere_requete

    # Rate limiting
    maintenant = time.time()
    ecart = maintenant - _derniere_requete
    if ecart < DELAI_ENTRE_REQUETES:
        time.sleep(DELAI_ENTRE_REQUETES - ecart)

    for tentative in range(max_retries):
        try:
            _derniere_requete = time.time()
            r = SESSION.get(url, params=params, timeout=timeout)
            return r
        except (requests.ConnectionError, requests.Timeout) as e:
            delai = 2 ** tentative  # 1s, 2s, 4s
            if tentative < max_retries - 1:
                logger.info(f"Tentative {tentative + 1}/{max_retries} échouée ({e}), retry dans {delai}s...")
                time.sleep(delai)
            else:
                logger.warning(f"Échec après {max_retries} tentatives pour {url}: {e}")
                raise

    return None


# ============================================================================
# MODÈLES DE DONNÉES
# ============================================================================

class TypeBatiment(Enum):
    """Type de bâtiment détecté"""
    MAISON = "Maison individuelle"
    APPARTEMENT = "Appartement en immeuble"
    INCONNU = "Type inconnu"


def _normaliser_planta(planta: str) -> str:
    """Normalise les codes d'étage du cadastre espagnol.

    B, BJ (Bajo) → '00' (rez-de-chaussée)
    SS (Semi-sótano) → 'SS'
    ST, SO (Sótano) → conservé
    01, 02... → conservé
    """
    p = planta.strip().upper()
    if p in ('B', 'BJ', 'BAJA'):
        return '00'
    return p


@dataclass
class Construccion:
    """Unité de construction (VIVIENDA, ALMACEN, etc.)"""
    uso: str
    superficie_m2: int
    planta: str = "00"
    puerta: Optional[str] = None
    escalera: Optional[str] = None
    referencia_20: Optional[str] = None

    @property
    def est_chauffee(self) -> bool:
        return "VIVIENDA" in self.uso.upper()


@dataclass
class Inmueble:
    """Bien immobilier (appartement ou maison)"""
    referencia_20: str
    construcciones: List[Construccion] = field(default_factory=list)
    
    @property
    def superficie_vivienda(self) -> int:
        return sum(c.superficie_m2 for c in self.construcciones if c.est_chauffee)
    
    @property
    def superficie_total(self) -> int:
        return sum(c.superficie_m2 for c in self.construcciones)


@dataclass
class EnveloppeThermique:
    """Surfaces de l'enveloppe thermique pour CE3X"""
    murs_exterieurs: float = 0.0
    murs_exterieurs_nord: float = 0.0
    murs_exterieurs_sud: float = 0.0
    murs_exterieurs_est: float = 0.0
    murs_exterieurs_ouest: float = 0.0
    murs_mitoyens_lnc: float = 0.0  # Murs vers Local Non Chauffé (ALMACEN, garage...)
    murs_mitoyens_chauffes: float = 0.0  # Murs vers autre logement chauffé (adiabatique)
    plancher_terre_plein: float = 0.0
    plancher_sur_lnc: float = 0.0
    plancher_sur_local_chauffe: float = 0.0  # Plancher au-dessus d'un autre logement
    plafond_sous_local_chauffe: float = 0.0  # Plafond sous un autre logement
    toiture: float = 0.0
    # Huecos (fenêtres/ouvertures) — estimation normative par orientation
    huecos_nord: float = 0.0
    huecos_sud: float = 0.0
    huecos_est: float = 0.0
    huecos_ouest: float = 0.0
    huecos_total: float = 0.0
    # Caractéristiques estimées des menuiseries
    tipo_vidrio: str = ""       # "Simple", "Doble 4/6/4", "Doble bajo emisivo"
    tipo_marco: str = ""        # "Madera", "Metálico sin RPT", "Metálico con RPT", "PVC"
    ratio_huecos_murs: float = 0.0  # Ratio fenêtres/murs utilisé (ex: 0.15)


@dataclass
class PartieBatiment:
    """Partie de bâtiment avec géométrie (extrait du GML INSPIRE)"""
    nom: str  # Part 1, Part 2, etc.
    hauteur_m: float  # Hauteur au-dessus du sol en mètres
    style: str  # WFS, etc.
    nb_etages_estime: int = 1  # Nombre d'étages au-dessus du sol
    nb_etages_sous_sol: int = 0  # Nombre d'étages sous le sol
    hauteur_sous_sol: float = 0.0  # Profondeur du sous-sol en mètres
    polygone: List[Tuple[float, float]] = field(default_factory=list)  # Coordonnées UTM
    surface_au_sol: float = 0.0  # Surface au sol calculée depuis le polygone (m²)


@dataclass
class LocalFXCC:
    """Local extrait du KML FXCC (croquis par planta)"""
    code_uso: str           # "V", "V.01", "AAP", "AAP.01", "TZA", "ALM", "YSP", "POR"
    description: str        # "Vivienda", "Aparcamiento", "Terraza"
    planta: str             # "00", "01", "-1" (normalisé)
    polygone_sol: List[Tuple[float, float]]  # WGS84 (lon, lat) du plancher
    altitude_min: float     # z du plancher (0 pour RDC, 3 pour étage 1...)
    altitude_max: float     # z du plafond

    @property
    def est_vivienda(self) -> bool:
        """Local chauffé (vivienda, porche habitable, etc.)"""
        code = self.code_uso.split('.')[0].upper()
        return code in ('V', 'VIV')

    @property
    def est_lnc(self) -> bool:
        """Local non chauffé (parking, entrepôt, etc.)"""
        code = self.code_uso.split('.')[0].upper()
        return code in ('AAP', 'ALM', 'K', 'TRS')


@dataclass
class DonneesFXCC:
    """Données extraites du KML FXCC (croquis par planta)"""
    etages: Dict[str, List[LocalFXCC]] = field(default_factory=dict)  # planta → [locaux]
    disponible: bool = True


@dataclass
class ResultatAnalyse:
    """Résultat complet de l'analyse"""
    referencia: str
    type_batiment: TypeBatiment
    province: Optional[str] = None
    municipalite: Optional[str] = None
    adresse: Optional[str] = None
    annee_construction: Optional[int] = None
    nombre_etages: int = 1
    hauteur_etage: float = 2.7
    hauteur_max_gml: Optional[float] = None  # Hauteur max depuis KML
    perimetre: float = 0.0
    utm_zone: int = 30  # UTM Zone (29, 30, ou 31)
    utm_x: Optional[float] = None  # UTM Easting (ETRS89)
    utm_y: Optional[float] = None  # UTM Northing (ETRS89)
    coord_wgs84_lon: Optional[float] = None  # Longitude WGS84
    coord_wgs84_lat: Optional[float] = None  # Latitude WGS84
    url_photo_facade: Optional[str] = None  # Lien vers photo de façade (API)
    fichier_photo_facade: Optional[str] = None  # Chemin local de la photo téléchargée
    fichier_carte_localisation: Optional[str] = None  # Chemin local de la carte de localisation
    parties_batiment: List[PartieBatiment] = field(default_factory=list)  # Parties 3D du GML
    polygones_voisins: List[List[Tuple[float, float]]] = field(default_factory=list)  # Bâtiments adjacents
    inmuebles: List[Inmueble] = field(default_factory=list)
    enveloppe: EnveloppeThermique = field(default_factory=EnveloppeThermique)
    # Codes sedecatastro (pour FXCC KML)
    del_code: Optional[str] = None  # Code delegación interne catastro
    mun_code: Optional[str] = None  # Code municipio interne catastro
    fxcc: Optional[DonneesFXCC] = None  # Données FXCC (croquis par planta)
    # Alertes pour l'isolation
    est_dernier_etage: bool = False  # True si l'appartement est au dernier étage
    etage_combles: Optional[int] = None  # Étage où se trouvent les combles
    alerte_combles: Optional[str] = None  # Message d'alerte si pas de combles
    
    @property
    def surface_utile(self) -> int:
        """Surface habitable totale (VIVIENDA uniquement)"""
        return sum(i.superficie_vivienda for i in self.inmuebles)
    
    @property
    def surface_totale(self) -> int:
        """Surface construite totale"""
        return sum(i.superficie_total for i in self.inmuebles)


# ============================================================================
# FONCTIONS GÉOMÉTRIQUES
# ============================================================================

def calculer_surface_polygone(coords: List[Tuple[float, float]]) -> float:
    """Calcule la surface d'un polygone par la formule de Shoelace (m²)."""
    n = len(coords)
    if n < 3:
        return 0.0
    # Fermer le polygone si nécessaire
    if coords[0] != coords[-1]:
        coords = coords + [coords[0]]
    area = 0.0
    for i in range(len(coords) - 1):
        area += coords[i][0] * coords[i + 1][1] - coords[i + 1][0] * coords[i][1]
    return abs(area) / 2.0


def calculer_perimetre_polygone(coords: List[Tuple[float, float]]) -> float:
    """Calcule le périmètre d'un polygone (m)."""
    if len(coords) < 2:
        return 0.0
    if coords[0] != coords[-1]:
        coords = coords + [coords[0]]
    perim = 0.0
    for i in range(len(coords) - 1):
        dx = coords[i + 1][0] - coords[i][0]
        dy = coords[i + 1][1] - coords[i][1]
        perim += math.sqrt(dx * dx + dy * dy)
    return perim


def trouver_mur_mitoyen(poly1: List[Tuple[float, float]], poly2: List[Tuple[float, float]], tolerance: float = 0.5) -> float:
    """
    Trouve la longueur du mur mitoyen entre deux polygones.
    Vérifie chaque arête de poly1 : si ses deux extrémités correspondent
    à des vertices de poly2 (à tolérance près), c'est un mur partagé.
    Retourne la longueur totale du mur mitoyen en mètres.
    """
    if not poly1 or not poly2:
        return 0.0

    def dist(p1, p2):
        return math.sqrt((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2)

    def point_dans_poly(p, polygon):
        return any(dist(p, q) < tolerance for q in polygon)

    longueur = 0.0
    n = len(poly1)
    for i in range(n):
        j = (i + 1) % n
        v1, v2 = poly1[i], poly1[j]
        seg = dist(v1, v2)
        if seg < 0.1:
            continue
        if point_dans_poly(v1, poly2) and point_dans_poly(v2, poly2):
            longueur += seg

    return longueur


def calculer_mitoyennete_voisins(
    polygone_batiment: List[Tuple[float, float]],
    polygones_voisins: List[List[Tuple[float, float]]],
    tolerance: float = 0.5
) -> Tuple[float, Dict[str, float]]:
    """
    Calcule la longueur et l'orientation des murs mitoyens avec les bâtiments voisins.

    Pour chaque bâtiment voisin :
    1. Trouve les vertices communs entre notre polygone et celui du voisin
    2. Calcule la longueur de chaque segment mitoyen
    3. Détermine l'orientation (N/S/E/O) de chaque segment via atan2

    Retourne (longueur_totale, {'N': ..., 'S': ..., 'E': ..., 'O': ...})
    """
    if not polygone_batiment or not polygones_voisins:
        return 0.0, {'N': 0.0, 'S': 0.0, 'E': 0.0, 'O': 0.0}

    def dist(p1, p2):
        return math.sqrt((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2)

    longueur_totale = 0.0
    orientations = {'N': 0.0, 'S': 0.0, 'E': 0.0, 'O': 0.0}

    # Exclure le point de fermeture du polygone (évite doublons)
    poly_ouvert = polygone_batiment
    if len(poly_ouvert) > 1 and dist(poly_ouvert[0], poly_ouvert[-1]) < tolerance:
        poly_ouvert = poly_ouvert[:-1]

    n = len(poly_ouvert)
    for poly_voisin in polygones_voisins:
        # Pour chaque arête du bâtiment, vérifier si les deux extrémités
        # correspondent à des vertices du voisin (= arête partagée)
        for i in range(n):
            j = (i + 1) % n
            v1, v2 = poly_ouvert[i], poly_ouvert[j]

            segment = dist(v1, v2)
            if segment < 0.5:
                continue

            v1_match = any(dist(v1, p2) < tolerance for p2 in poly_voisin)
            if not v1_match:
                continue
            v2_match = any(dist(v2, p2) < tolerance for p2 in poly_voisin)
            if not v2_match:
                continue

            longueur_totale += segment

            # Orientation du segment (même logique que get_geometrie_batiment)
            dx = v2[0] - v1[0]
            dy = v2[1] - v1[1]
            angle = math.degrees(math.atan2(dx, dy))
            if angle < 0:
                angle += 360

            # Le segment est un mur → la façade est perpendiculaire
            # Un segment orienté N-S bloque la façade E ou O
            if 315 <= angle or angle < 45:
                orientations['E'] += segment
            elif 45 <= angle < 135:
                orientations['S'] += segment
            elif 135 <= angle < 225:
                orientations['O'] += segment
            else:
                orientations['N'] += segment

    return longueur_totale, orientations


def estimer_huecos(annee_construction: Optional[int], env: EnveloppeThermique):
    """
    Estime les surfaces de fenêtres (huecos) par orientation selon la normative espagnole.

    Logique basée sur les périodes réglementaires :
    - Avant 1979 (pas de réglementation) : ratio 12%, vitrage simple, menuiserie bois
    - 1979-2006 (NBE-CT-79) : ratio 18%, double vitrage 4/6/4, menuiserie métallique sans RPT
    - Après 2006 (CTE DB-HE) : ratio 22%, double vitrage basse émissivité, PVC

    Le ratio est appliqué aux murs extérieurs par orientation.
    Le sud reçoit un bonus (+30%) et le nord un malus (-30%) car les façades sud
    ont historiquement plus d'ouvertures pour l'apport solaire.
    """
    if env.murs_exterieurs == 0:
        return

    annee = annee_construction or 1980  # Défaut si inconnu

    # Déterminer le ratio et les caractéristiques selon la période
    if annee < 1979:
        ratio_base = 0.12
        tipo_vidrio = "Simple"
        tipo_marco = "Madera"
    elif annee < 2007:
        ratio_base = 0.18
        tipo_vidrio = "Doble 4/6/4"
        tipo_marco = "Metálico sin RPT"
    else:
        ratio_base = 0.22
        tipo_vidrio = "Doble bajo emisivo"
        tipo_marco = "PVC"

    # Moduler par orientation :
    # Sud +30% (plus de fenêtres pour l'apport solaire)
    # Nord -30% (moins de fenêtres pour limiter les déperditions)
    # Est/Ouest : ratio de base
    env.huecos_nord = round(env.murs_exterieurs_nord * ratio_base * 0.7, 1)
    env.huecos_sud = round(env.murs_exterieurs_sud * ratio_base * 1.3, 1)
    env.huecos_est = round(env.murs_exterieurs_est * ratio_base, 1)
    env.huecos_ouest = round(env.murs_exterieurs_ouest * ratio_base, 1)
    env.huecos_total = round(
        env.huecos_nord + env.huecos_sud + env.huecos_est + env.huecos_ouest, 1
    )

    env.tipo_vidrio = tipo_vidrio
    env.tipo_marco = tipo_marco
    env.ratio_huecos_murs = round(ratio_base, 2)

    print(f"      Huecos estimés (ratio {ratio_base:.0%}, année {annee}):")
    print(f"        Nord: {env.huecos_nord} m² | Sud: {env.huecos_sud} m² | "
          f"Est: {env.huecos_est} m² | Ouest: {env.huecos_ouest} m²")
    print(f"        Total: {env.huecos_total} m² | Vidrio: {tipo_vidrio} | Marco: {tipo_marco}")


# ============================================================================
# FXCC KML (croquis par planta - enrichissement optionnel)
# ============================================================================

def _wgs84_vers_metres(coords_wgs84: List[Tuple[float, float]], lat_ref: float) -> List[Tuple[float, float]]:
    """Convertit des coordonnées WGS84 (lon, lat) en mètres locaux (approximation plane)."""
    cos_lat = math.cos(math.radians(lat_ref))
    if not coords_wgs84:
        return []
    origin_lon, origin_lat = coords_wgs84[0]
    return [
        ((lon - origin_lon) * 111320 * cos_lat, (lat - origin_lat) * 110540)
        for lon, lat in coords_wgs84
    ]


def calculer_surface_wgs84(coords_wgs84: List[Tuple[float, float]]) -> float:
    """
    Calcule la surface d'un polygone en coordonnées WGS84 (lon, lat).
    Formule de Shoelace avec correction cos(latitude).
    Retourne la surface en m².
    """
    if len(coords_wgs84) < 3:
        return 0.0

    lat_moy = sum(lat for _, lat in coords_wgs84) / len(coords_wgs84)
    coords_m = _wgs84_vers_metres(coords_wgs84, lat_moy)

    # Shoelace
    n = len(coords_m)
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += coords_m[i][0] * coords_m[j][1]
        area -= coords_m[j][0] * coords_m[i][1]
    return abs(area) / 2.0


def _normaliser_planta_fxcc(nom_folder: str) -> str:
    """Normalise le nom de planta FXCC en code standard.
    'PLANTA BAJA' → '00', 'PLANTA 01' → '01', 'PLANTA PRIMERA' → '01',
    'PLANTA SEGUNDA' → '02', 'BAJA 00' → '00', 'PISO 01' → '01',
    'SOTANO -1' → '-1', 'PLANTA -1' → '-1'
    """
    nom = nom_folder.strip().upper()

    # Chercher un numéro explicite (positif ou négatif)
    num_match = re.search(r'(-?\d+)', nom)

    if 'BAJA' in nom or nom == 'PLANTA BAJA':
        return '00'
    elif 'PRIMERA' in nom:
        return '01'
    elif 'SEGUNDA' in nom:
        return '02'
    elif 'TERCERA' in nom:
        return '03'
    elif 'SOTANO' in nom or 'SS' in nom:
        if num_match:
            val = int(num_match.group(1))
            return str(-abs(val)) if val > 0 else num_match.group(1)
        return '-1'
    elif num_match:
        return num_match.group(1).zfill(2) if int(num_match.group(1)) >= 0 else num_match.group(1)

    return '00'


def parser_fxcc_kml(contenu_kml: str) -> Optional[DonneesFXCC]:
    """
    Parse le contenu KML du FXCC et extrait les locaux par étage.
    Retourne None si le KML est invalide ou ne contient pas de données.
    """
    if not contenu_kml or '<kml' not in contenu_kml:
        return None

    etages: Dict[str, List[LocalFXCC]] = {}

    # Extraire les Folders (un par planta)
    folders = re.findall(r'<Folder>(.*?)</Folder>', contenu_kml, re.DOTALL)
    if not folders:
        return None

    for folder in folders:
        # Nom du folder
        name_m = re.search(r'<name>(.*?)</name>', folder)
        if not name_m:
            continue
        nom_folder = name_m.group(1).strip()

        # Ignorer PLANTA GENERAL (c'est juste l'emprise au sol)
        if 'GENERAL' in nom_folder.upper():
            continue

        planta = _normaliser_planta_fxcc(nom_folder)

        # Extraire les Placemarks (un par local)
        placemarks = re.findall(r'<Placemark>(.*?)</Placemark>', folder, re.DOTALL)
        for pm in placemarks:
            uso_m = re.search(r'<name>(.*?)</name>', pm)
            desc_m = re.search(r'<description>([^<]*)</description>', pm)
            code_uso = uso_m.group(1).strip() if uso_m else ''
            description = desc_m.group(1).strip() if desc_m else ''

            # Extraire tous les polygones
            coords_all = re.findall(r'<coordinates>(.*?)</coordinates>', pm, re.DOTALL)
            polygones = []
            for coords_str in coords_all:
                points = []
                for pt in coords_str.strip().split():
                    parts = pt.split(',')
                    if len(parts) >= 3:
                        try:
                            lon, lat, alt = float(parts[0]), float(parts[1]), float(parts[2])
                            points.append((lon, lat, alt))
                        except ValueError:
                            continue
                if len(points) >= 3:
                    polygones.append(points)

            if not polygones:
                continue

            # Trouver le polygone au sol (altitude minimale uniforme)
            min_alt = min(p[2] for poly in polygones for p in poly)
            max_alt = max(p[2] for poly in polygones for p in poly)

            # Le polygone sol = celui dont tous les points ont z == min_alt
            poly_sol = None
            for poly in polygones:
                if all(abs(p[2] - min_alt) < 0.01 for p in poly):
                    poly_sol = [(p[0], p[1]) for p in poly]
                    break

            if not poly_sol:
                # Fallback: prendre le premier polygone
                poly_sol = [(p[0], p[1]) for p in polygones[0]]

            local = LocalFXCC(
                code_uso=code_uso,
                description=description,
                planta=planta,
                polygone_sol=poly_sol,
                altitude_min=min_alt,
                altitude_max=max_alt,
            )

            if planta not in etages:
                etages[planta] = []
            etages[planta].append(local)

    if not etages:
        return None

    return DonneesFXCC(etages=etages)


def telecharger_fxcc_kml(ref14: str, del_code: str, mun_code: str) -> Optional[str]:
    """
    Télécharge le fichier KML FXCC depuis sedecatastro (GET direct).
    Retourne le contenu KML brut, ou None si non disponible.
    """
    try:
        r = faire_requete(URL_FXCC_KML, params={
            'refcat': ref14, 'del': del_code, 'mun': mun_code
        }, timeout=30)

        if not r or r.status_code != 200:
            return None

        content_type = r.headers.get('Content-Type', '').lower()
        if 'kml' in content_type and len(r.text) > 100:
            return r.text

        return None
    except Exception as e:
        logger.warning(f"Erreur téléchargement FXCC KML pour {ref14}: {e}")
        return None


def calculer_mur_mitoyen_fxcc(
    polygone_vivienda: List[Tuple[float, float]],
    polygones_lnc: List[List[Tuple[float, float]]],
) -> float:
    """
    Calcule la longueur du mur mitoyen entre vivienda et LNC au même étage,
    en utilisant les polygones FXCC (WGS84).
    Convertit en mètres locaux puis utilise trouver_mur_mitoyen().
    """
    if not polygone_vivienda or not polygones_lnc:
        return 0.0

    lat_ref = sum(lat for _, lat in polygone_vivienda) / len(polygone_vivienda)
    cos_lat = math.cos(math.radians(lat_ref))
    origin_lon, origin_lat = polygone_vivienda[0]

    # Convertir vivienda en mètres locaux
    poly_viv_m = [
        ((lon - origin_lon) * 111320 * cos_lat, (lat - origin_lat) * 110540)
        for lon, lat in polygone_vivienda
    ]

    longueur_totale = 0.0
    for poly_lnc in polygones_lnc:
        poly_lnc_m = [
            ((lon - origin_lon) * 111320 * cos_lat, (lat - origin_lat) * 110540)
            for lon, lat in poly_lnc
        ]
        mur = trouver_mur_mitoyen(poly_viv_m, poly_lnc_m, tolerance=0.3)
        longueur_totale += mur

    return longueur_totale


# ============================================================================
# SERVICES D'EXTRACTION DE DONNÉES
# ============================================================================

class CadastreService:
    """Service d'accès aux données cadastrales"""
    
    @staticmethod
    def get_codes_province_municipalite(ref14: str) -> Tuple[Optional[str], Optional[str]]:
        """Récupère les codes province/municipalité via CPMRC"""
        try:
            r = faire_requete(URL_CPMRC, params={
                'SRS': 'EPSG:4326', 'Provincia': '', 'Municipio': '', 'RC': ref14
            }, timeout=15)

            if r and r.status_code == 200:
                cp = re.search(r'<cp>(\d+)</cp>', r.text)
                cm = re.search(r'<cm>(\d+)</cm>', r.text)
                if cp and cm:
                    return cp.group(1), cm.group(1)
        except Exception as e:
            logger.warning(f"Erreur API CPMRC pour {ref14}: {e}")
        return None, None
    
    @staticmethod
    def get_geometrie_batiment(ref14: str) -> Tuple[float, Dict[str, float], List[Tuple[float, float]], int]:
        """Récupère la géométrie du bâtiment (périmètre, façades, coordonnées, zone UTM)"""
        try:
            # Ne pas forcer srsname - utiliser le format natif pour avoir la bonne zone
            r = faire_requete(URL_WFS_BU, params={
                'service': 'WFS',
                'version': '2.0.0',
                'request': 'GetFeature',
                'StoredQuery_id': 'GetBuildingByParcel',
                'refcat': ref14
            }, timeout=15)
            if not r:
                return 0.0, {}, [], 30

            # Détecter la zone UTM depuis le srsName
            zone_utm = 30  # défaut
            srs_match = re.search(r'EPSG::?258(\d+)', r.text)
            if srs_match:
                zone_utm = int(srs_match.group(1))
            
            # Extraire les coordonnées
            poslist = re.search(r'<gml:posList[^>]*>([^<]+)</gml:posList>', r.text)
            if not poslist:
                return 0.0, {}, [], zone_utm
            
            coords_str = poslist.group(1).strip().split()
            coords = [(float(coords_str[i]), float(coords_str[i+1])) 
                     for i in range(0, len(coords_str)-1, 2)]
            
            if len(coords) < 3:
                return 0.0, {}, coords, zone_utm
            
            # Calculer périmètre et façades par orientation
            perimetre = 0.0
            facades = {'N': 0.0, 'S': 0.0, 'E': 0.0, 'O': 0.0}
            
            for i in range(len(coords) - 1):
                dx = coords[i+1][0] - coords[i][0]
                dy = coords[i+1][1] - coords[i][1]
                segment = math.sqrt(dx*dx + dy*dy)
                perimetre += segment
                
                if segment > 0.5:
                    angle = math.degrees(math.atan2(dx, dy))
                    if angle < 0:
                        angle += 360
                    
                    if 315 <= angle or angle < 45:
                        facades['E'] += segment
                    elif 45 <= angle < 135:
                        facades['S'] += segment
                    elif 135 <= angle < 225:
                        facades['O'] += segment
                    else:
                        facades['N'] += segment
            
            return perimetre, facades, coords, zone_utm
            
        except Exception as e:
            logger.warning(f"Erreur WFS géométrie pour {ref14}: {e}")
            return 0.0, {}, [], 30
    
    @staticmethod
    def get_nombre_etages(ref14: str) -> int:
        """Récupère le nombre d'étages du bâtiment"""
        try:
            r = faire_requete(URL_WFS_BU, params={
                'service': 'WFS',
                'version': '2.0.0',
                'request': 'GetFeature',
                'StoredQuery_id': 'GetBuildingPartByParcel',
                'refcat': ref14,
                'srsname': 'EPSG:25830'
            }, timeout=15)
            if not r:
                return 1
            
            match = re.search(r'<bu-ext2d:numberOfFloorsAboveGround>(\d+)</bu-ext2d:numberOfFloorsAboveGround>', r.text)
            return int(match.group(1)) if match else 1
        except Exception as e:
            logger.warning(f"Erreur WFS nombre étages pour {ref14}: {e}")
            return 1


class BuildingPartService:
    """Service pour récupérer les parties de bâtiment depuis le WFS INSPIRE"""
    
    @staticmethod
    def get_building_parts(ref14: str) -> List[PartieBatiment]:
        """
        Récupère les parties du bâtiment avec toutes les données GML INSPIRE :
        - numberOfFloorsAboveGround / numberOfFloorsBelowGround
        - heightBelowGround
        - geometry (polygone) de chaque partie → surface au sol réelle
        """
        parties = []

        try:
            r = faire_requete(URL_WFS_BU, params={
                'service': 'WFS',
                'version': '2.0.0',
                'request': 'GetFeature',
                'StoredQuery_id': 'GetBuildingPartByParcel',
                'refcat': ref14
            }, timeout=15)

            if not r or r.status_code != 200:
                return parties

            # Découper le XML en blocs par BuildingPart
            part_blocks = re.findall(
                r'<bu-ext2d:BuildingPart[^>]*gml:id="([^"]+)".*?</bu-ext2d:BuildingPart>',
                r.text, re.DOTALL
            )

            for block_match in re.finditer(
                r'<bu-ext2d:BuildingPart[^>]*gml:id="([^"]+)"(.*?)</bu-ext2d:BuildingPart>',
                r.text, re.DOTALL
            ):
                part_id = block_match.group(1)
                block = block_match.group(2)

                # Numéro de partie
                part_num_match = re.search(r'_part(\d+)$', part_id)
                part_num = part_num_match.group(1) if part_num_match else "1"

                # Étages au-dessus du sol
                above_match = re.search(r'<bu-ext2d:numberOfFloorsAboveGround>(\d+)</bu-ext2d:numberOfFloorsAboveGround>', block)
                nb_etages = int(above_match.group(1)) if above_match else 1

                # Étages sous le sol
                below_match = re.search(r'<bu-ext2d:numberOfFloorsBelowGround>(\d+)</bu-ext2d:numberOfFloorsBelowGround>', block)
                nb_etages_ss = int(below_match.group(1)) if below_match else 0

                # Hauteur sous le sol
                height_below_match = re.search(r'<bu-ext2d:heightBelowGround[^>]*>(\d+(?:\.\d+)?)</bu-ext2d:heightBelowGround>', block)
                hauteur_ss = float(height_below_match.group(1)) if height_below_match else 0.0

                # Polygone (coordonnées UTM)
                polygone = []
                poslist_match = re.search(r'<gml:posList[^>]*>([^<]+)</gml:posList>', block)
                if poslist_match:
                    coords_str = poslist_match.group(1).strip().split()
                    polygone = [(float(coords_str[i]), float(coords_str[i + 1]))
                                for i in range(0, len(coords_str) - 1, 2)]

                # Surface au sol (depuis le polygone)
                surface = calculer_surface_polygone(polygone) if polygone else 0.0

                # Hauteur estimée au-dessus du sol
                hauteur_estimee = nb_etages * 3.0

                parties.append(PartieBatiment(
                    nom=f"Part {part_num}",
                    hauteur_m=hauteur_estimee,
                    style="WFS",
                    nb_etages_estime=nb_etages,
                    nb_etages_sous_sol=nb_etages_ss,
                    hauteur_sous_sol=hauteur_ss,
                    polygone=polygone,
                    surface_au_sol=round(surface, 1)
                ))

            return parties

        except Exception as e:
            logger.warning(f"Erreur WFS parties bâtiment pour {ref14}: {e}")
            return []

    @staticmethod
    def get_max_etages_from_parts(parties: List[PartieBatiment]) -> int:
        """Retourne le nombre d'étages maximum parmi toutes les parties"""
        if not parties:
            return 1
        return max(p.nb_etages_estime for p in parties)
    
    @staticmethod
    def get_coordonnees_wgs84(ref14: str) -> Tuple[Optional[float], Optional[float]]:
        """Récupère les coordonnées WGS84 du bâtiment via l'API CPMRC"""
        try:
            r = faire_requete(URL_CPMRC, params={
                'SRS': 'EPSG:4326',
                'Provincia': '',
                'Municipio': '',
                'RC': ref14
            }, timeout=15)

            if r and r.status_code == 200:
                # Extraire les coordonnées
                xcen = re.search(r'<xcen>([^<]+)</xcen>', r.text)
                ycen = re.search(r'<ycen>([^<]+)</ycen>', r.text)
                
                if xcen and ycen:
                    lon = float(xcen.group(1))
                    lat = float(ycen.group(1))
                    return lon, lat
            
            return None, None
        except Exception as e:
            logger.warning(f"Erreur coordonnées WGS84 pour {ref14}: {e}")
            return None, None

    @staticmethod
    def get_batiments_voisins(ref14: str, coords_batiment: List[Tuple[float, float]],
                               zone_utm: int = 30) -> List[List[Tuple[float, float]]]:
        """
        Recherche les bâtiments voisins via WFS INSPIRE en 2 étapes:
        1. GetNeighbourParcel (wfsCP) → liste des parcelles voisines
        2. GetBuildingByParcel (wfsBU) → polygone de chaque bâtiment voisin

        Retourne une liste de polygones (coordonnées UTM) des bâtiments voisins.
        """
        if not coords_batiment or len(coords_batiment) < 3:
            return []

        try:
            # Étape 1: Obtenir les parcelles voisines via wfsCP
            r = faire_requete(URL_WFS_CP, params={
                'service': 'WFS',
                'version': '2.0.0',
                'request': 'GetFeature',
                'StoredQuery_id': 'GetNeighbourParcel',
                'refcat': ref14
            }, timeout=15)

            if not r or r.status_code != 200:
                return []

            # Parser les ref14 des parcelles voisines
            refs_voisines = []
            for m_ref in re.finditer(
                r'<cp:nationalCadastralReference>([^<]+)</cp:nationalCadastralReference>',
                r.text
            ):
                ref_voisin = m_ref.group(1).strip()
                if ref_voisin != ref14:
                    refs_voisines.append(ref_voisin)

            if not refs_voisines:
                return []

            logger.info(f"Parcelles voisines de {ref14}: {refs_voisines}")

            # Étape 2: Obtenir le polygone de chaque bâtiment voisin via wfsBU
            voisins = []
            for ref_voisin in refs_voisines:
                try:
                    r_bu = faire_requete(URL_WFS_BU, params={
                        'service': 'WFS',
                        'version': '2.0.0',
                        'request': 'GetFeature',
                        'StoredQuery_id': 'GetBuildingByParcel',
                        'refcat': ref_voisin
                    }, timeout=10)

                    if not r_bu or r_bu.status_code != 200:
                        continue

                    # Extraire le polygone du bâtiment
                    for m_bu in re.finditer(
                        r'<bu-ext2d:Building[^>]*gml:id="([^"]*)"(.*?)</bu-ext2d:Building>',
                        r_bu.text, re.DOTALL
                    ):
                        block = m_bu.group(2)
                        poslist = re.search(r'<gml:posList[^>]*>([^<]+)</gml:posList>', block)
                        if not poslist:
                            continue

                        coords_str = poslist.group(1).strip().split()
                        if len(coords_str) < 6:
                            continue

                        polygone = [(float(coords_str[i]), float(coords_str[i + 1]))
                                    for i in range(0, len(coords_str) - 1, 2)]
                        voisins.append(polygone)

                except Exception as e:
                    logger.debug(f"Erreur WFS bâtiment voisin {ref_voisin}: {e}")
                    continue

            return voisins

        except Exception as e:
            logger.warning(f"Erreur WFS bâtiments voisins pour {ref14}: {e}")
            return []


class HTMLScrapingService:
    """Service de scraping des pages HTML du cadastre"""
    
    @staticmethod
    def get_page_inmuebles(ref14: str) -> Tuple[str, bool]:
        """
        Récupère la page des inmuebles.
        Retourne (contenu_html, est_page_detail)
        """
        rc1, rc2 = ref14[:7], ref14[7:14]
        url = f"{URL_SEDE}/OVCListaBienes.aspx?rc1={rc1}&rc2={rc2}"
        
        try:
            r = faire_requete(url, timeout=30)
            if not r:
                return "", False
            content = r.text

            # Détecter si page détail ou liste
            est_detail = 'Lista de inmuebles' not in content and 'Bien Inmueble' in content
            return content, est_detail
        except Exception as e:
            logger.warning(f"Erreur scraping page inmuebles pour {ref14}: {e}")
            return "", False
    
    @staticmethod
    def get_page_detail_inmueble(ref20: str, del_code: str, mun_code: str) -> str:
        """Récupère la page détail d'un inmueble spécifique"""
        url = f"{URL_SEDE}/OVCConCiud.aspx?del={del_code}&mun={mun_code}&UrbRus=U&RefC={ref20}"
        
        try:
            r = faire_requete(url, timeout=30)
            if r and 'Error de Datos' not in r.text:
                return r.text
        except Exception as e:
            logger.warning(f"Erreur scraping détail inmueble {ref20}: {e}")
        return ""
    
    @staticmethod
    def extraire_referencias_20(html: str) -> List[str]:
        """Extrait les références 20 caractères depuis une page liste"""
        pattern = r'target="_top"\s*>(\d{7}[A-Z]{2}\d{4}[A-Z]\d{4}[A-Z]{2})\s*</a>'
        refs = [m.group(1) for m in re.finditer(pattern, html)]
        return list(dict.fromkeys(refs))
    
    @staticmethod
    def extraire_referencia_detail(html: str) -> Optional[str]:
        """Extrait la référence depuis une page détail"""
        # Pattern flexible pour références cadastrales (20 caractères alphanumériques)
        match = re.search(r'RefC=([0-9A-Z]{20})', html)
        return match.group(1) if match else None
    
    @staticmethod
    def extraire_construcciones(html: str, ref20: str) -> List[Construccion]:
        """Extrait les constructions depuis une page HTML"""
        construcciones = []
        
        # Pattern pour table de construction
        pattern = r'<tr>\s*<td><span>([^<]+)</span></td>\s*<td><span>([^<]*)</span></td>\s*<td><span>([^<]*)</span></td>\s*<td><span>([^<]*)</span></td>\s*<td><span>(\d+)</span></td>'
        
        for m in re.finditer(pattern, html):
            uso, escalera, planta, puerta, superficie = m.groups()
            uso = uso.strip()
            if uso and uso not in ['Uso principal', '']:
                construcciones.append(Construccion(
                    uso=uso,
                    superficie_m2=int(superficie),
                    planta=_normaliser_planta(planta) if planta.strip() else "00",
                    puerta=puerta.strip() or None,
                    escalera=escalera.strip() or None,
                    referencia_20=ref20
                ))
        
        # Fallback: extraction simplifiée
        if not construcciones:
            sfc = re.search(r'Superficie construida.*?black[^>]*>\s*(\d+)\s*m', html, re.DOTALL)
            uso = re.search(r'Uso principal.*?black[^>]*>\s*([^<]+)\s*</label>', html, re.DOTALL)
            
            if sfc:
                construcciones.append(Construccion(
                    uso=uso.group(1).strip() if uso else "VIVIENDA",
                    superficie_m2=int(sfc.group(1)),
                    planta="00",
                    referencia_20=ref20
                ))
        
        return construcciones
    
    @staticmethod
    def extraire_annee_construction(html: str) -> Optional[int]:
        """Extrait l'année de construction"""
        match = re.search(r"title=['\"]Año[^\"']*['\"][^>]*>(\d{4})", html)
        if not match:
            match = re.search(r'construcci[oó]n.*?black[^>]*>\s*(\d{4})', html, re.DOTALL | re.IGNORECASE)
        return int(match.group(1)) if match else None
    
    @staticmethod
    def extraire_adresse(html: str) -> Optional[str]:
        """Extrait l'adresse complète (rue + code postal + ville + province)"""
        # Pattern pour adresse dans label avec <br>
        match = re.search(
            r"Localizaci[oó]n.*?<label[^>]*>([^<]+)<br\s*/?>([^<]+)</label>",
            html, re.DOTALL | re.IGNORECASE
        )
        if match:
            ligne1 = match.group(1).strip()
            ligne2 = match.group(2).strip()
            return f"{ligne1}, {ligne2}"
        
        # Fallback: pattern simple avec ldt
        match = re.search(r'<ldt>([^<]+)</ldt>', html)
        return match.group(1).strip() if match else None
    
    @staticmethod
    def extraire_codes_del_mun(html: str) -> Tuple[Optional[str], Optional[str]]:
        """Extrait les codes del/mun depuis le HTML"""
        # Pattern: CargarBien('5','22',...)
        match = re.search(r"CargarBien\s*\(\s*'(\d+)'\s*,\s*'(\d+)'", html)
        if match:
            return match.group(1), match.group(2)
        
        # Pattern: del=5&mun=22
        del_match = re.search(r'del=(\d+)', html)
        mun_match = re.search(r'mun=(\d+)', html)
        if del_match and mun_match:
            return del_match.group(1), mun_match.group(1)
        
        return None, None


# ============================================================================
# ANALYSEUR PRINCIPAL
# ============================================================================

class AnalyseurCE3X:
    """Analyseur principal pour CE3X"""
    
    # Pattern de validation: 14 ou 20 caractères alphanumériques
    _REF_PATTERN = re.compile(r'^[0-9A-Z]{14}([0-9A-Z]{6})?$')

    def __init__(self, referencia: str):
        self.ref_input = referencia.strip().upper().replace(' ', '')

        # Validation du format de la référence cadastrale
        if not self._REF_PATTERN.match(self.ref_input):
            raise ValueError(
                f"Référence cadastrale invalide: '{referencia}'. "
                f"Format attendu: 14 ou 20 caractères alphanumériques (ex: 0983320QG3808S)"
            )

        self.ref_14 = self.ref_input[:14]
        # Si référence 20 caractères → analyser UN SEUL appartement
        self.ref_20_cible = self.ref_input if len(self.ref_input) == 20 else None
        self.mode_appartement_unique = self.ref_20_cible is not None
        self.resultat = ResultatAnalyse(referencia=self.ref_14, type_batiment=TypeBatiment.INCONNU)
    
    def analyser(self) -> ResultatAnalyse:
        """Lance l'analyse complète"""
        if self.mode_appartement_unique:
            print(f"\n{'═'*70}")
            print(f"  ANALYSE CE3X - APPARTEMENT {self.ref_20_cible}")
            print(f"{'═'*70}")
        else:
            print(f"\n{'═'*70}")
            print(f"  ANALYSE CE3X - {self.ref_14}")
            print(f"{'═'*70}")
        
        # Étape 1: Récupérer les codes province/municipalité
        self._etape_1_codes()
        
        # Étape 2: Détecter le type de bâtiment et collecter les inmuebles
        self._etape_2_type_et_inmuebles()
        
        # Étape 3: Collecter les données de construction détaillées
        self._etape_3_construcciones()
        
        # Étape 4: Récupérer la géométrie
        self._etape_4_geometrie()
        
        # Étape 5: Calculer l'enveloppe thermique
        if self.mode_appartement_unique:
            self._etape_5_enveloppe_appartement_unique()
        else:
            self._etape_5_enveloppe()
        
        return self.resultat
    
    def _etape_1_codes(self):
        """Étape 1: Récupérer les codes province/municipalité"""
        print("\n[1/5] Identification province/municipalité...")
        
        prov, mun = CadastreService.get_codes_province_municipalite(self.ref_14)
        self.resultat.province = prov
        self.resultat.municipalite = mun
        
        if prov:
            print(f"      Province: {prov}, Municipalité: {mun}")
        else:
            print("      ⚠ Codes non trouvés (mode dégradé)")
    
    def _etape_2_type_et_inmuebles(self):
        """Étape 2: Détecter type de bâtiment et lister les inmuebles"""
        print("\n[2/5] Détection du type de bâtiment...")
        
        html, est_detail = HTMLScrapingService.get_page_inmuebles(self.ref_14)
        self._html_liste = html  # Stocker pour extraction codes
        
        # Extraire codes del/mun depuis HTML (toujours, pour FXCC KML)
        del_code, mun_code = HTMLScrapingService.extraire_codes_del_mun(html)
        if del_code:
            self.resultat.del_code = del_code
            self.resultat.mun_code = mun_code
            # Fallback province/municipalite si pas trouvés via CPMRC
            if not self.resultat.province or not self.resultat.municipalite:
                self.resultat.province = del_code
                self.resultat.municipalite = mun_code
                print(f"      Codes extraits du HTML: del={del_code}, mun={mun_code}")
        
        if est_detail:
            # Bien unique → MAISON
            self.resultat.type_batiment = TypeBatiment.MAISON
            ref20 = HTMLScrapingService.extraire_referencia_detail(html)
            if ref20:
                self.resultat.inmuebles.append(Inmueble(referencia_20=ref20))
            print(f"      ➜ Type: {self.resultat.type_batiment.value}")
            print(f"      ➜ 1 bien immobilier")
            
            # Stocker le HTML pour l'étape 3
            self._html_detail = html
        else:
            # Plusieurs biens → APPARTEMENT
            refs = HTMLScrapingService.extraire_referencias_20(html)
            
            if len(refs) > 1:
                self.resultat.type_batiment = TypeBatiment.APPARTEMENT
            elif len(refs) == 1:
                self.resultat.type_batiment = TypeBatiment.MAISON
            
            for ref20 in refs:
                self.resultat.inmuebles.append(Inmueble(referencia_20=ref20))
            
            print(f"      ➜ Type: {self.resultat.type_batiment.value}")
            print(f"      ➜ {len(refs)} bien(s) immobilier(s)")
            
            self._html_detail = None
        
        # Extraire année et adresse
        self.resultat.annee_construction = HTMLScrapingService.extraire_annee_construction(html)
        self.resultat.adresse = HTMLScrapingService.extraire_adresse(html)
        
        # Générer URL photo de façade via API OVCFotoFachada
        if self.resultat.inmuebles:
            ref14 = self.ref_14
            self.resultat.url_photo_facade = f"https://ovc.catastro.meh.es/OVCServWeb/OVCWcfLibres/OVCFotoFachada.svc/RecuperarFotoFachadaGet?ReferenciaCatastral={ref14}"
    
    def _etape_3_construcciones(self):
        """Étape 3: Collecter les détails de construction"""
        print("\n[3/5] Collecte des données de construction...")
        
        for inmueble in self.resultat.inmuebles:
            print(f"      - {inmueble.referencia_20}...")
            
            # Récupérer le HTML détaillé
            if hasattr(self, '_html_detail') and self._html_detail:
                html = self._html_detail
            elif self.resultat.province and self.resultat.municipalite:
                html = HTMLScrapingService.get_page_detail_inmueble(
                    inmueble.referencia_20,
                    self.resultat.province,
                    self.resultat.municipalite
                )
            else:
                continue
            
            # Extraire les constructions
            construcciones = HTMLScrapingService.extraire_construcciones(html, inmueble.referencia_20)
            inmueble.construcciones = construcciones
            
            # Afficher
            for c in construcciones:
                symbole = "✓" if c.est_chauffee else "✗"
                print(f"        [{symbole}] {c.uso}: {c.superficie_m2} m²", end='')
                if c.planta != "00":
                    print(f" (Pl:{c.planta})", end='')
                print()
    
    def _etape_4_geometrie(self):
        """Étape 4: Récupérer la géométrie du bâtiment"""
        print("\n[4/5] Analyse géométrique...")
        
        # Périmètre et façades
        perimetre, facades, coords, zone_utm = CadastreService.get_geometrie_batiment(self.ref_14)
        self.resultat.perimetre = round(perimetre, 2)
        self.resultat.utm_zone = zone_utm
        self._facades = facades
        self._coords = coords
        
        # Calculer centroïde UTM
        if coords and len(coords) > 0:
            self.resultat.utm_x = round(sum(c[0] for c in coords) / len(coords), 0)
            self.resultat.utm_y = round(sum(c[1] for c in coords) / len(coords), 0)
            print(f"      UTM = {zone_utm} X : {int(self.resultat.utm_x)} m, Y : {int(self.resultat.utm_y)} m")
        
        # Récupérer coordonnées WGS84
        lon, lat = BuildingPartService.get_coordonnees_wgs84(self.ref_14)
        if lon and lat:
            self.resultat.coord_wgs84_lon = round(lon, 6)
            self.resultat.coord_wgs84_lat = round(lat, 6)
            print(f"      WGS84: Lon={lon:.6f}°, Lat={lat:.6f}°")
        
        # Récupérer les parties du bâtiment depuis le WFS (contient les étages!)
        parties = BuildingPartService.get_building_parts(self.ref_14)
        self.resultat.parties_batiment = parties
        
        if parties:
            print(f"      Parties du bâtiment: {len(parties)}")
            for p in parties:
                ss_info = f" + {p.nb_etages_sous_sol} ss ({p.hauteur_sous_sol}m)" if p.nb_etages_sous_sol > 0 else ""
                surf_info = f", sol={p.surface_au_sol:.0f}m²" if p.surface_au_sol > 0 else ""
                print(f"        - {p.nom}: {p.nb_etages_estime} étage(s) (~{p.hauteur_m}m){ss_info}{surf_info}")
            
            # Nombre d'étages = maximum parmi toutes les parties
            self.resultat.nombre_etages = BuildingPartService.get_max_etages_from_parts(parties)
            self.resultat.hauteur_max_gml = max(p.hauteur_m for p in parties)
            
            # Hauteur d'étage estimée
            self.resultat.hauteur_etage = round(self.resultat.hauteur_max_gml / self.resultat.nombre_etages, 2)
        else:
            # Fallback: utiliser l'ancienne méthode
            self.resultat.nombre_etages = CadastreService.get_nombre_etages(self.ref_14)
            self.resultat.hauteur_etage = 2.7
        
        print(f"      Nombre d'étages (max): {self.resultat.nombre_etages}")
        print(f"      Hauteur d'étage: {self.resultat.hauteur_etage}m")
        print(f"      Périmètre: {perimetre:.2f} m")
        if facades:
            print(f"      Façades: N={facades['N']:.1f}m, S={facades['S']:.1f}m, E={facades['E']:.1f}m, O={facades['O']:.1f}m")

        # Rechercher les bâtiments voisins (mitoyenneté)
        if coords and len(coords) >= 3:
            voisins = BuildingPartService.get_batiments_voisins(self.ref_14, coords, zone_utm)
            self.resultat.polygones_voisins = voisins
            if voisins:
                print(f"      Bâtiments voisins détectés: {len(voisins)}")

        # Téléchargement FXCC KML (croquis par planta, optionnel)
        if self.resultat.del_code and self.resultat.mun_code:
            try:
                contenu_kml = telecharger_fxcc_kml(
                    self.ref_14, self.resultat.del_code, self.resultat.mun_code
                )
                if contenu_kml:
                    fxcc = parser_fxcc_kml(contenu_kml)
                    if fxcc and fxcc.etages:
                        self.resultat.fxcc = fxcc
                        print(f"      FXCC KML: {len(fxcc.etages)} étage(s) avec croquis")
                        for planta, locaux in fxcc.etages.items():
                            locaux_str = ", ".join(f"{l.code_uso}({l.description})" for l in locaux)
                            print(f"        Planta {planta}: {locaux_str}")
                    else:
                        print(f"      FXCC KML: pas de données exploitables")
                else:
                    print(f"      FXCC KML: non disponible pour ce bâtiment")
            except Exception as e:
                logger.warning(f"Erreur FXCC KML pour {self.ref_14}: {e}")

    def _calculer_mur_lnc_fxcc(self, planta: str) -> Optional[float]:
        """
        Calcule la longueur du mur entre vivienda et LNC au même étage
        en utilisant les polygones FXCC.
        Retourne la longueur en mètres, ou None si FXCC non dispo pour cet étage.
        """
        fxcc = self.resultat.fxcc
        if not fxcc or planta not in fxcc.etages:
            return None

        locaux = fxcc.etages[planta]
        # Séparer vivienda et LNC
        polys_viv = [l.polygone_sol for l in locaux if l.est_vivienda]
        polys_lnc = [l.polygone_sol for l in locaux if l.est_lnc]

        if not polys_viv or not polys_lnc:
            return None

        # Prendre le plus grand polygone vivienda
        poly_viv = max(polys_viv, key=lambda p: calculer_surface_wgs84(p))

        longueur = calculer_mur_mitoyen_fxcc(poly_viv, polys_lnc)
        return longueur if longueur > 0 else None

    def _etape_5_enveloppe(self):
        """
        Étape 5: Calculer l'enveloppe thermique en combinant GML et données construction.
        
        Logique:
        - Les murs extérieurs sont calculés à partir du périmètre estimé de la VIVIENDA
          (pas du bâtiment entier qui inclut les ALMACEN)
        - Les murs mitoyens sont les parois entre VIVIENDA et LNC (ALMACEN)
        - Le plancher et la toiture sont basés sur les surfaces VIVIENDA par étage
        """
        print("\n[5/5] Calcul de l'enveloppe thermique...")
        
        h = self.resultat.hauteur_etage
        perimetre_total = self.resultat.perimetre
        facades = getattr(self, '_facades', {})
        parties_batiment = self.resultat.parties_batiment
        
        # Organiser les constructions par étage
        plantas = self._organiser_par_planta()
        
        # Déterminer les étages chauffés et non chauffés
        plantas_chauffees = [p for p, info in plantas.items() if info['vivienda'] > 0]
        plantas_non_chauffees = [p for p, info in plantas.items() if info['vivienda'] == 0 and info['otros'] > 0]
        
        if not plantas_chauffees:
            print("      ⚠ Aucune surface VIVIENDA détectée")
            return
        
        env = self.resultat.enveloppe
        
        # ================================================================
        # ANALYSE DE LA STRUCTURE DU BÂTIMENT
        # ================================================================
        
        # Surface VIVIENDA par étage et totale
        surface_vivienda_par_etage = {p: plantas[p].get('vivienda', 0) for p in plantas_chauffees}
        surface_vivienda_max = max(surface_vivienda_par_etage.values()) if surface_vivienda_par_etage else 0
        surface_lnc_par_etage = {p: plantas.get(p, {}).get('otros', 0) for p in plantas}
        
        # Surface totale du bâtiment et ratio VIVIENDA
        surface_totale_rdc = plantas.get('00', {}).get('vivienda', 0) + plantas.get('00', {}).get('otros', 0)
        ratio_vivienda = surface_vivienda_max / surface_totale_rdc if surface_totale_rdc > 0 else 1.0
        
        print(f"      Surface VIVIENDA max par étage: {surface_vivienda_max} m²")
        print(f"      Ratio VIVIENDA/Total: {ratio_vivienda:.1%}")
        
        # ================================================================
        # CALCUL DU PÉRIMÈTRE DE LA PARTIE VIVIENDA
        # ================================================================
        
        # Déterminer quelle partie du bâtiment contient la VIVIENDA (celle avec le plus d'étages)
        partie_vivienda = None
        if parties_batiment:
            partie_vivienda = max(parties_batiment, key=lambda p: p.nb_etages_estime)
            hauteur_partie_vivienda = partie_vivienda.hauteur_m

            # Utiliser le périmètre réel du polygone GML si disponible
            if partie_vivienda.polygone:
                perimetre_vivienda_estime = calculer_perimetre_polygone(partie_vivienda.polygone)
                print(f"      Partie VIVIENDA: {partie_vivienda.nom} ({partie_vivienda.nb_etages_estime} ét., "
                      f"{hauteur_partie_vivienda}m, périmètre GML={perimetre_vivienda_estime:.1f}m, "
                      f"sol={partie_vivienda.surface_au_sol:.0f}m²)")
            else:
                perimetre_vivienda_estime = 4 * math.sqrt(surface_vivienda_max)
                print(f"      Partie VIVIENDA: {partie_vivienda.nom} ({partie_vivienda.nb_etages_estime} ét., "
                      f"périmètre estimé={perimetre_vivienda_estime:.1f}m)")
        else:
            perimetre_vivienda_estime = 4 * math.sqrt(surface_vivienda_max)
            hauteur_partie_vivienda = h * len(plantas_chauffees)
        
        # ================================================================
        # 1. MURS MITOYENS AVEC BÂTIMENTS VOISINS (chauffés)
        # ================================================================

        coords_batiment = getattr(self, '_coords', [])
        longueur_mitoyens_voisins = 0.0
        orientations_mitoyens = {'N': 0.0, 'S': 0.0, 'E': 0.0, 'O': 0.0}

        if coords_batiment and self.resultat.polygones_voisins:
            longueur_mitoyens_voisins, orientations_mitoyens = calculer_mitoyennete_voisins(
                coords_batiment, self.resultat.polygones_voisins
            )
            if longueur_mitoyens_voisins > 0:
                n_etages_chauffes_tmp = len(plantas_chauffees)
                env.murs_mitoyens_chauffes = round(longueur_mitoyens_voisins * h * n_etages_chauffes_tmp, 1)
                print(f"      Murs mitoyens voisins: {longueur_mitoyens_voisins:.1f}m × {h}m × {n_etages_chauffes_tmp} = {env.murs_mitoyens_chauffes:.1f} m²")
                for orient, longueur in orientations_mitoyens.items():
                    if longueur > 0:
                        print(f"        {orient}: {longueur:.1f}m")

        # ================================================================
        # 2. MURS EXTÉRIEURS DE LA VIVIENDA
        # ================================================================

        # Méthode: périmètre estimé de la VIVIENDA × hauteur totale chauffée
        # On déduit les murs mitoyens avec voisins

        n_etages_chauffes = len(plantas_chauffees)
        hauteur_murs_ext = h * n_etages_chauffes

        # Soustraire les murs mitoyens voisins du périmètre extérieur
        perimetre_ext = perimetre_vivienda_estime - longueur_mitoyens_voisins
        perimetre_ext = max(perimetre_ext, 0)

        # Calculer les murs extérieurs basés sur le ratio de façade
        # Les façades GML donnent la répartition par orientation
        total_facades = sum(facades.values()) if facades else perimetre_total

        if total_facades > 0 and facades:
            # Répartir le périmètre VIVIENDA selon les proportions des façades
            ratio_n = facades.get('N', 0) / total_facades
            ratio_s = facades.get('S', 0) / total_facades
            ratio_e = facades.get('E', 0) / total_facades
            ratio_o = facades.get('O', 0) / total_facades

            env.murs_exterieurs_nord = round(perimetre_ext * ratio_n * hauteur_murs_ext, 1)
            env.murs_exterieurs_sud = round(perimetre_ext * ratio_s * hauteur_murs_ext, 1)
            env.murs_exterieurs_est = round(perimetre_ext * ratio_e * hauteur_murs_ext, 1)
            env.murs_exterieurs_ouest = round(perimetre_ext * ratio_o * hauteur_murs_ext, 1)
        else:
            # Répartition égale si pas de données d'orientation
            mur_par_orient = perimetre_ext * hauteur_murs_ext / 4
            env.murs_exterieurs_nord = round(mur_par_orient, 1)
            env.murs_exterieurs_sud = round(mur_par_orient, 1)
            env.murs_exterieurs_est = round(mur_par_orient, 1)
            env.murs_exterieurs_ouest = round(mur_par_orient, 1)

        env.murs_exterieurs = round(
            env.murs_exterieurs_nord + env.murs_exterieurs_sud +
            env.murs_exterieurs_est + env.murs_exterieurs_ouest, 1
        )
        
        # ================================================================
        # 2. MURS MITOYENS VIVIENDA ↔ LNC (ALMACEN)
        # ================================================================

        # D'abord, calculer le mur mitoyen entre parties via les polygones GML
        longueur_mur_entre_parties = 0.0
        if len(parties_batiment) >= 2:
            for i in range(len(parties_batiment)):
                for j in range(i + 1, len(parties_batiment)):
                    if parties_batiment[i].polygone and parties_batiment[j].polygone:
                        mur = trouver_mur_mitoyen(parties_batiment[i].polygone, parties_batiment[j].polygone)
                        if mur > 0:
                            longueur_mur_entre_parties += mur
                            print(f"      Mur entre {parties_batiment[i].nom} <-> {parties_batiment[j].nom}: {mur:.1f}m (GML)")

        # Pour chaque étage chauffé, calculer la paroi entre VIVIENDA et LNC
        # Priorité: FXCC (polygones réels) → GML (mur entre parties) → √surface (estimation)
        for p in plantas_chauffees:
            sup_viv = plantas[p].get('vivienda', 0)
            sup_lnc = plantas[p].get('otros', 0)

            if sup_viv > 0 and sup_lnc > 0:
                mur_fxcc = self._calculer_mur_lnc_fxcc(p)
                if mur_fxcc and mur_fxcc > 0:
                    env.murs_mitoyens_lnc += mur_fxcc * h
                    print(f"      Mur LNC FXCC (planta {p}): {mur_fxcc:.1f}m × {h}m = {round(mur_fxcc * h, 1)} m²")
                elif longueur_mur_entre_parties > 0:
                    # Utiliser la longueur réelle du mur entre parties (GML)
                    env.murs_mitoyens_lnc += longueur_mur_entre_parties * h
                else:
                    # Estimation géométrique (fallback)
                    cote_viv = math.sqrt(sup_viv)
                    cote_lnc = math.sqrt(sup_lnc)
                    longueur_mitoyenne = min(cote_viv, cote_lnc)
                    env.murs_mitoyens_lnc += longueur_mitoyenne * h

        env.murs_mitoyens_lnc = round(env.murs_mitoyens_lnc, 1)

        # ================================================================
        # 3. PLANCHER SUR TERRE-PLEIN (avec détection sous-sol GML)
        # ================================================================

        # Détecter si le bâtiment a un sous-sol (via GML)
        a_sous_sol = any(p.nb_etages_sous_sol > 0 for p in parties_batiment)

        if '00' in plantas_chauffees:
            if a_sous_sol:
                # Il y a un sous-sol → le plancher du RDC n'est PAS sur terre-plein
                env.plancher_sur_lnc = plantas['00'].get('vivienda', 0)
                print(f"      Plancher RDC: sur LNC (sous-sol GML détecté)")
            else:
                # Pas de sous-sol dans le GML → vérifier aussi les construcciones
                has_basement_constr = any(
                    p_key in ('-1', 'SM', '-2', 'SO')
                    for p_key in plantas_non_chauffees
                )
                if has_basement_constr:
                    env.plancher_sur_lnc = plantas['00'].get('vivienda', 0)
                    print(f"      Plancher RDC: sur LNC (sous-sol dans construcciones)")
                else:
                    env.plancher_terre_plein = plantas['00'].get('vivienda', 0)
                    print(f"      Plancher RDC: sur terre-plein")
        
        # ================================================================
        # 4. PLANCHER SUR LNC (VIVIENDA au-dessus d'un espace non chauffé)
        # ================================================================
        
        for p in plantas_chauffees:
            if p == '00':
                continue
            p_dessous = str(int(p) - 1).zfill(2)
            # Plancher sur LNC si l'étage en dessous a du LNC mais pas de VIVIENDA
            if p_dessous in plantas_non_chauffees:
                env.plancher_sur_lnc += plantas[p].get('vivienda', 0)
            # OU si l'étage en dessous a du LNC ET de la VIVIENDA (cas mixte)
            elif p_dessous in plantas and plantas[p_dessous].get('otros', 0) > 0:
                # Seulement la partie au-dessus du LNC
                # Estimation: proportionnelle au ratio LNC/total
                sup_lnc_dessous = plantas[p_dessous].get('otros', 0)
                sup_total_dessous = sup_lnc_dessous + plantas[p_dessous].get('vivienda', 0)
                ratio_lnc = sup_lnc_dessous / sup_total_dessous if sup_total_dessous > 0 else 0
                env.plancher_sur_lnc += plantas[p].get('vivienda', 0) * ratio_lnc
        
        env.plancher_sur_lnc = round(env.plancher_sur_lnc, 1)
        
        # ================================================================
        # 5. TOITURE (VIVIENDA au dernier étage)
        # ================================================================
        
        if plantas_chauffees:
            planta_max = max(plantas_chauffees)
            p_dessus = str(int(planta_max) + 1).zfill(2)
            
            # Toiture si pas d'étage au-dessus
            if p_dessus not in plantas:
                env.toiture = plantas[planta_max].get('vivienda', 0)
        
        # ================================================================
        # 7. MURS MITOYENS AVEC ESPACES CHAUFFÉS (appartements / maisons mitoyennes)
        # ================================================================
        
        self._calculer_mitoyennete_chauffee(env, plantas, h)
        
        # ================================================================
        # 8. DÉTECTION COMBLES / DERNIER ÉTAGE (pour appartements)
        # ================================================================
        
        self._verifier_position_combles(plantas, plantas_chauffees)

        # ================================================================
        # 9. HUECOS (FENÊTRES) — estimation normative
        # ================================================================

        estimer_huecos(self.resultat.annee_construction, env)

        # ================================================================
        # AFFICHAGE DU RÉSUMÉ
        # ================================================================

        print(f"      Périmètre VIVIENDA estimé: {perimetre_vivienda_estime:.1f} m (vs {perimetre_total:.1f} m total)")
        print(f"      Hauteur partie chauffée: {hauteur_murs_ext:.1f} m")
        if env.murs_mitoyens_chauffes > 0:
            print(f"      Mitoyenneté chauffée détectée: {env.murs_mitoyens_chauffes:.1f} m²")
        print("      ✓ Calculs terminés")
    
    def _organiser_par_planta(self) -> Dict[str, Dict[str, int]]:
        """Organise les constructions par étage"""
        plantas = {}
        
        for inmueble in self.resultat.inmuebles:
            for c in inmueble.construcciones:
                # Ignorer ELEMENTOS COMUNES
                if 'ELEMENTOS COMUNES' in c.uso.upper():
                    continue
                
                p = c.planta
                if p not in plantas:
                    plantas[p] = {'vivienda': 0, 'otros': 0}
                
                if c.est_chauffee:
                    plantas[p]['vivienda'] += c.superficie_m2
                else:
                    plantas[p]['otros'] += c.superficie_m2
        
        return plantas
    
    def _calculer_mitoyennete_chauffee(self, env: EnveloppeThermique, plantas: Dict, h: float):
        """
        Calcule les surfaces mitoyennes avec d'autres espaces chauffés.
        
        Cas détectés:
        1. APPARTEMENTS: Plusieurs inmuebles dans le même bâtiment
           → Murs mitoyens entre appartements au même étage
           → Plancher/plafond entre appartements à des étages différents
        
        2. MAISONS EN RANGÉE: Bâtiment avec plusieurs VIVIENDA au même niveau
           → Estimation des murs mitoyens latéraux
        """
        nb_inmuebles = len(self.resultat.inmuebles)
        type_bat = self.resultat.type_batiment
        
        # ================================================================
        # CAS 1: APPARTEMENTS (plusieurs inmuebles)
        # ================================================================
        
        if type_bat == TypeBatiment.APPARTEMENT and nb_inmuebles > 1:
            print(f"      Détection mitoyenneté: {nb_inmuebles} appartements")
            
            # Organiser les inmuebles par étage
            inmuebles_par_etage = {}
            for inm in self.resultat.inmuebles:
                for c in inm.construcciones:
                    if c.est_chauffee:
                        p = c.planta
                        if p not in inmuebles_par_etage:
                            inmuebles_par_etage[p] = []
                        if inm.referencia_20 not in [i['ref'] for i in inmuebles_par_etage[p]]:
                            inmuebles_par_etage[p].append({
                                'ref': inm.referencia_20,
                                'surface': c.superficie_m2
                            })
            
            # Calculer les murs mitoyens horizontaux (entre appartements au même étage)
            for p, inmuebles in inmuebles_par_etage.items():
                if len(inmuebles) > 1:
                    # Plusieurs appartements au même étage = murs mitoyens entre eux
                    # Estimation: chaque paire d'appartements adjacents partage un mur
                    nb_paires = len(inmuebles) - 1
                    
                    # Longueur du mur mitoyen estimée (côté de l'appartement)
                    surface_moyenne = sum(i['surface'] for i in inmuebles) / len(inmuebles)
                    cote_estime = math.sqrt(surface_moyenne)
                    
                    # Mur mitoyen = côté × hauteur × nombre de paires
                    surface_mur_mitoyen = cote_estime * h * nb_paires
                    env.murs_mitoyens_chauffes += surface_mur_mitoyen
                    
                    print(f"        Étage {p}: {len(inmuebles)} appts → murs mitoyens: {surface_mur_mitoyen:.1f} m²")
            
            # Calculer les planchers/plafonds entre appartements (étages différents)
            etages_tries = sorted(inmuebles_par_etage.keys())
            for i, p in enumerate(etages_tries):
                if i > 0:
                    # Il y a un étage en dessous avec des appartements
                    p_dessous = etages_tries[i-1]
                    if int(p) - int(p_dessous) == 1:
                        # Étages consécutifs = plancher/plafond mitoyen
                        # Surface = min des deux étages
                        surf_actuel = sum(inm['surface'] for inm in inmuebles_par_etage[p])
                        surf_dessous = sum(inm['surface'] for inm in inmuebles_par_etage[p_dessous])
                        surface_contact = min(surf_actuel, surf_dessous)
                        
                        env.plancher_sur_local_chauffe += surface_contact
                        print(f"        Plancher {p} sur appts {p_dessous}: {surface_contact:.1f} m²")
            
            # Plafond sous local chauffé
            for i, p in enumerate(etages_tries):
                if i < len(etages_tries) - 1:
                    p_dessus = etages_tries[i+1]
                    if int(p_dessus) - int(p) == 1:
                        surf_actuel = sum(inm['surface'] for inm in inmuebles_par_etage[p])
                        surf_dessus = sum(inm['surface'] for inm in inmuebles_par_etage[p_dessus])
                        surface_contact = min(surf_actuel, surf_dessus)
                        env.plafond_sous_local_chauffe += surface_contact
        
        # ================================================================
        # CAS 2: MAISONS EN RANGÉE (détection heuristique)
        # ================================================================
        
        elif type_bat == TypeBatiment.MAISON:
            # Heuristique: si le bâtiment est très allongé (périmètre élevé vs surface)
            # il pourrait être mitoyen avec d'autres maisons
            
            perimetre = self.resultat.perimetre
            surface_totale = self.resultat.surface_totale
            
            if surface_totale > 0 and perimetre > 0:
                # Ratio périmètre/surface pour détecter forme allongée
                # Un carré parfait a ratio = 4/√S
                # Une maison en rangée a un ratio plus élevé
                ratio_attendu_carre = 4 / math.sqrt(surface_totale)
                ratio_reel = perimetre / surface_totale
                
                # Si le ratio réel est significativement plus bas que attendu,
                # cela peut indiquer des murs mitoyens (périmètre réduit)
                if ratio_reel < ratio_attendu_carre * 0.7:
                    # Estimation: 2 côtés mitoyens (maison entre deux autres)
                    cote_estime = math.sqrt(surface_totale / self.resultat.nombre_etages)
                    hauteur_totale = self.resultat.hauteur_etage * self.resultat.nombre_etages
                    
                    # Réduction de périmètre = murs mitoyens
                    perimetre_theorique = 4 * cote_estime
                    difference = max(0, perimetre_theorique - perimetre)
                    
                    if difference > 2:  # Seuil minimal
                        surface_mitoyenne = difference * hauteur_totale
                        env.murs_mitoyens_chauffes += surface_mitoyenne
                        print(f"      Maison potentiellement mitoyenne: {surface_mitoyenne:.1f} m² de murs partagés")
        
        # Arrondir les valeurs finales
        env.murs_mitoyens_chauffes = round(env.murs_mitoyens_chauffes, 1)
        env.plancher_sur_local_chauffe = round(env.plancher_sur_local_chauffe, 1)
        env.plafond_sous_local_chauffe = round(env.plafond_sous_local_chauffe, 1)
    
    def _etape_5_enveloppe_appartement_unique(self):
        """
        Calcul de l'enveloppe thermique pour UN SEUL appartement/bien spécifique.

        Traite chaque étage séparément pour calculer correctement :
        - Plancher : surface de la vivienda au RDC (terre-plein ou sur LNC)
        - Toiture : surface de la vivienda au dernier étage
        - Murs : périmètre réel par étage

        Utilise les données GML INSPIRE complètes :
        - numberOfFloorsBelowGround / heightBelowGround → détection sous-sol
        - Polygones individuels des parties → murs mitoyens entre parties
        - Construcciones par étage → LNC au même étage
        """
        print("\n[5/5] Calcul de l'enveloppe thermique (BIEN UNIQUE)...")

        h = self.resultat.hauteur_etage
        parties = self.resultat.parties_batiment

        # Trouver l'appartement cible
        appt_cible = None
        for inm in self.resultat.inmuebles:
            if inm.referencia_20 == self.ref_20_cible:
                appt_cible = inm
                break

        if not appt_cible:
            print(f"      ⚠ Bien {self.ref_20_cible} non trouvé!")
            return

        # ================================================================
        # ORGANISER LES CONSTRUCCIONES PAR ÉTAGE
        # ================================================================

        # Regrouper vivienda et LNC par étage
        etages_vivienda = {}  # {planta: surface_vivienda}
        etages_lnc = {}       # {planta: surface_lnc}
        surface_appt_total = 0

        for c in appt_cible.construcciones:
            planta = c.planta
            if c.est_chauffee:
                etages_vivienda[planta] = etages_vivienda.get(planta, 0) + c.superficie_m2
                surface_appt_total += c.superficie_m2
            else:
                etages_lnc[planta] = etages_lnc.get(planta, 0) + c.superficie_m2

        if surface_appt_total == 0:
            print(f"      ⚠ Pas de VIVIENDA dans ce bien!")
            return

        # Trier les étages
        def _planta_to_int(p):
            """Convertit un identifiant de planta en entier pour le tri."""
            if p.lstrip('-').isdigit():
                return int(p)
            if p.upper() in ('SM', 'SO', 'SS'):
                return -1
            return 0

        etages_tries = sorted(etages_vivienda.keys(), key=_planta_to_int)
        etage_min = etages_tries[0]
        etage_max = etages_tries[-1]
        etage_min_int = _planta_to_int(etage_min)
        etage_max_int = _planta_to_int(etage_max)
        nb_etages_vivienda = len(etages_vivienda)

        print(f"      Bien cible: {self.ref_20_cible}")
        print(f"      Surface VIVIENDA totale: {surface_appt_total} m²")
        for planta in etages_tries:
            lnc_info = f" + LNC {etages_lnc[planta]}m²" if planta in etages_lnc else ""
            print(f"        Planta {planta}: VIVIENDA {etages_vivienda[planta]} m²{lnc_info}")

        # Surface vivienda par étage clé
        surface_rdc = etages_vivienda.get("00", 0)
        surface_dernier = etages_vivienda.get(etage_max, 0)
        surface_lnc_total = sum(etages_lnc.get(p, 0) for p in etages_vivienda)

        # Mettre à jour la référence dans le résultat
        self.resultat.referencia = self.ref_20_cible

        env = self.resultat.enveloppe

        # ================================================================
        # DÉTECTER LE SOUS-SOL VIA LES DONNÉES GML
        # ================================================================

        a_sous_sol = False
        surface_sous_sol = 0.0
        for p in parties:
            if p.nb_etages_sous_sol > 0:
                a_sous_sol = True
                surface_sous_sol = p.surface_au_sol if p.surface_au_sol > 0 else 0
                print(f"      SOUS-SOL DÉTECTÉ (GML): {p.nb_etages_sous_sol} niveau(x), "
                      f"profondeur={p.hauteur_sous_sol}m, emprise={p.surface_au_sol:.0f}m²")
                break

        # Vérifier aussi via les construcciones (planta -1, -2, SO)
        # SM : considéré sous-sol seulement s'il n'y a PAS de vivienda à SM
        # (si SM a vivienda + parking, c'est un RDC effectif, pas un sous-sol)
        if not a_sous_sol:
            for c in appt_cible.construcciones:
                if c.planta in ('-1', '-2', 'SO') and not c.est_chauffee:
                    a_sous_sol = True
                    surface_sous_sol = c.superficie_m2
                    print(f"      SOUS-SOL DÉTECTÉ (construcciones): {c.uso} {c.superficie_m2}m² à planta {c.planta}")
                    break
                if c.planta == 'SM' and not c.est_chauffee and 'SM' not in etages_vivienda:
                    a_sous_sol = True
                    surface_sous_sol = c.superficie_m2
                    print(f"      SOUS-SOL DÉTECTÉ (construcciones): {c.uso} {c.superficie_m2}m² à planta {c.planta}")
                    break

        # ================================================================
        # IDENTIFIER LA PARTIE PRINCIPALE (vivienda) PARMI LES PARTIES GML
        # ================================================================
        # La partie principale est celle dont la surface correspond le mieux
        # à la surface vivienda d'un étage, ou la plus grande si pas de match

        partie_principale = None
        surface_un_etage_viv = max(etages_vivienda.values())
        if parties:
            # Chercher la partie dont la surface au sol est la plus proche de la vivienda
            partie_principale = min(
                [p for p in parties if p.surface_au_sol > 0] or parties,
                key=lambda p: abs(p.surface_au_sol - surface_un_etage_viv)
            )
            print(f"      Partie principale (vivienda): {partie_principale.nom} "
                  f"({partie_principale.surface_au_sol:.0f}m² sol)")

        # ================================================================
        # CALCULER LES MURS MITOYENS ENTRE PARTIE PRINCIPALE ET PARTIES LNC
        # ================================================================
        # On ne compte que les murs entre la partie principale (vivienda)
        # et les parties qui contiennent UNIQUEMENT du LNC.
        # Si vivienda et LNC sont dans la MÊME partie GML (ex: SM vivienda+parking),
        # le mur entre parties GML n'est pas le mur LNC.

        # Déterminer quelles parties sont purement LNC (aucun étage vivienda)
        # Pour cela, on compare les surfaces GML aux surfaces vivienda
        parties_lnc_pures = []
        if partie_principale and len(parties) >= 2:
            for p in parties:
                if p is partie_principale:
                    continue
                # Une partie est "LNC pure" si sa surface correspond
                # à la surface LNC et pas à la vivienda
                est_lnc_pure = False
                # Vérifier si la surface de cette partie est dans etages_lnc mais pas vivienda
                for planta_lnc, surf_lnc in etages_lnc.items():
                    if planta_lnc not in etages_vivienda and abs(p.surface_au_sol - surf_lnc) < 5:
                        est_lnc_pure = True
                        break
                if est_lnc_pure:
                    parties_lnc_pures.append(p)

        longueur_mur_principal_lnc = 0.0
        for p in parties_lnc_pures:
            if partie_principale.polygone and p.polygone:
                mur = trouver_mur_mitoyen(partie_principale.polygone, p.polygone)
                if mur > 0:
                    longueur_mur_principal_lnc += mur
                    print(f"      Mur mitoyen {partie_principale.nom} <-> {p.nom} (LNC): {mur:.1f}m")

        # ================================================================
        # CALCULER LES MURS MITOYENS AVEC LNC (au même étage)
        # ================================================================
        # Cas 1: Parties GML séparées (vivienda / LNC) → mur réel entre polygones
        # Cas 2: Vivienda + LNC dans la même partie (ex: SM) → estimation géométrique interne

        # Vérifier si vivienda et LNC cohabitent au même étage (même partie GML)
        lnc_meme_etage_que_vivienda = {p: s for p, s in etages_lnc.items() if p in etages_vivienda}

        if surface_lnc_total > 0:
            if lnc_meme_etage_que_vivienda:
                # Vivienda + LNC au même étage → FXCC si dispo, sinon estimation √surface
                for planta, surf_lnc in lnc_meme_etage_que_vivienda.items():
                    surf_viv = etages_vivienda[planta]
                    mur_fxcc = self._calculer_mur_lnc_fxcc(planta)
                    if mur_fxcc and mur_fxcc > 0:
                        env.murs_mitoyens_lnc += round(mur_fxcc * h, 1)
                        print(f"      Mur LNC FXCC (planta {planta}): {mur_fxcc:.1f}m × {h}m = {round(mur_fxcc * h, 1)} m²")
                    else:
                        longueur_cloison = min(math.sqrt(surf_viv), math.sqrt(surf_lnc))
                        env.murs_mitoyens_lnc += round(longueur_cloison * h, 1)
                        print(f"      Mur LNC interne (planta {planta}): {longueur_cloison:.1f}m × {h}m = {round(longueur_cloison * h, 1)} m²")
            if longueur_mur_principal_lnc > 0:
                # Mur réel entre partie principale et parties LNC pures
                nb_etages_lnc_pur = sum(1 for p in etages_lnc if p not in etages_vivienda)
                nb_etages_lnc_pur = max(nb_etages_lnc_pur, 1)
                env.murs_mitoyens_lnc += round(longueur_mur_principal_lnc * h * nb_etages_lnc_pur, 1)
            elif not lnc_meme_etage_que_vivienda:
                # Fallback: estimation géométrique si pas de mur GML et pas de cohabitation
                cote_viv = math.sqrt(surface_appt_total / nb_etages_vivienda)
                cote_lnc = math.sqrt(surface_lnc_total / nb_etages_vivienda)
                longueur_mitoyenne = min(cote_viv, cote_lnc)
                env.murs_mitoyens_lnc = round(longueur_mitoyenne * h * nb_etages_vivienda, 1)
            print(f"      Murs mitoyens LNC total: {env.murs_mitoyens_lnc:.1f} m²")

        # ================================================================
        # TROUVER LES VOISINS CHAUFFÉS (même étage, autres appartements)
        # ================================================================

        voisins_meme_etage = []
        for inm in self.resultat.inmuebles:
            if inm.referencia_20 == self.ref_20_cible:
                continue
            for c in inm.construcciones:
                if c.est_chauffee and c.planta in etages_vivienda:
                    voisins_meme_etage.append({
                        'ref': inm.referencia_20,
                        'surface': c.superficie_m2
                    })
                    break

        if voisins_meme_etage:
            print(f"      Voisins chauffés au même étage: {len(voisins_meme_etage)}")

        # ================================================================
        # TROUVER L'ÉTAGE MAXIMUM DU BÂTIMENT
        # ================================================================

        etage_max_batiment = 0
        for inm in self.resultat.inmuebles:
            for c in inm.construcciones:
                try:
                    etage = int(c.planta)
                    etage_max_batiment = max(etage_max_batiment, etage)
                except ValueError:
                    pass

        est_dernier_etage = (etage_max_int >= etage_max_batiment)

        print(f"      Étage min vivienda: {etage_min}, Étage max vivienda: {etage_max}")
        print(f"      Étage max bâtiment: {etage_max_batiment:02d}")
        print(f"      {'✅' if est_dernier_etage else '❌'} Dernier étage: {est_dernier_etage}")

        # ================================================================
        # 1. MURS MITOYENS AVEC BÂTIMENTS VOISINS (chauffés)
        # ================================================================

        coords_batiment = getattr(self, '_coords', [])
        longueur_mitoyens_voisins = 0.0

        if coords_batiment and self.resultat.polygones_voisins:
            longueur_mitoyens_voisins, orient_voisins = calculer_mitoyennete_voisins(
                coords_batiment, self.resultat.polygones_voisins
            )
            if longueur_mitoyens_voisins > 0:
                # Prorata si plusieurs appartements au même étage
                # Les murs voisins concernent tout le bâtiment, pas un seul appartement
                if voisins_meme_etage:
                    surface_un_etage = surface_appt_total / nb_etages_vivienda
                    surface_totale_etage = surface_un_etage + sum(
                        v['surface'] for v in voisins_meme_etage
                    )
                    ratio_appt = surface_un_etage / surface_totale_etage if surface_totale_etage > 0 else 1.0
                    longueur_mitoyens_voisins *= ratio_appt
                    print(f"      Prorata voisins: {ratio_appt:.0%} ({surface_un_etage:.0f}/{surface_totale_etage:.0f} m²)")
                env.murs_mitoyens_chauffes = round(longueur_mitoyens_voisins * h * nb_etages_vivienda, 1)
                print(f"      Murs mitoyens voisins: {longueur_mitoyens_voisins:.1f}m × {h}m × {nb_etages_vivienda} = {env.murs_mitoyens_chauffes:.1f} m²")
                for orient, longueur in orient_voisins.items():
                    if longueur > 0:
                        print(f"        {orient}: {longueur:.1f}m")

        # ================================================================
        # 2. MURS EXTÉRIEURS (périmètre × hauteur totale des étages chauffés)
        # ================================================================

        if partie_principale and partie_principale.polygone:
            # Périmètre réel de la partie principale (GML)
            perimetre_partie = calculer_perimetre_polygone(partie_principale.polygone)
            # Soustraire les murs mitoyens LNC + murs mitoyens voisins
            perimetre_ext = perimetre_partie - longueur_mur_principal_lnc - longueur_mitoyens_voisins
            perimetre_ext = max(perimetre_ext, 0)
            print(f"      Périmètre partie principale (GML): {perimetre_partie:.1f}m")
            print(f"      Périmètre extérieur (- LNC {longueur_mur_principal_lnc:.1f}m - voisins {longueur_mitoyens_voisins:.1f}m): {perimetre_ext:.1f}m")
        else:
            # Fallback: estimation carrée basée sur la surface d'un étage
            surface_un_etage = surface_appt_total / nb_etages_vivienda
            perimetre_appt = 4 * math.sqrt(surface_un_etage)
            perimetre_ext = perimetre_appt - longueur_mitoyens_voisins
            perimetre_ext = max(perimetre_ext, 0)
            print(f"      Périmètre estimé (carré): {perimetre_ext:.1f}m")

        # Réduire pour les voisins chauffés internes (autres appartements)
        if voisins_meme_etage:
            surface_un_etage = surface_appt_total / nb_etages_vivienda
            cote_appt = math.sqrt(surface_un_etage)
            perimetre_ext -= cote_appt

        # Murs extérieurs = périmètre × hauteur × nombre d'étages chauffés
        env.murs_exterieurs = round(perimetre_ext * h * nb_etages_vivienda, 1)
        print(f"      Murs extérieurs: {perimetre_ext:.1f}m × {h}m × {nb_etages_vivienda} étages = {env.murs_exterieurs:.1f} m²")

        # Répartition par orientation (proportionnelle aux façades GML)
        facades = getattr(self, '_facades', {})
        total_facades = sum(facades.values()) if facades else 1

        if total_facades > 0 and facades:
            ratio_n = facades.get('N', 0) / total_facades
            ratio_s = facades.get('S', 0) / total_facades
            ratio_e = facades.get('E', 0) / total_facades
            ratio_o = facades.get('O', 0) / total_facades

            env.murs_exterieurs_nord = round(env.murs_exterieurs * ratio_n, 1)
            env.murs_exterieurs_sud = round(env.murs_exterieurs * ratio_s, 1)
            env.murs_exterieurs_est = round(env.murs_exterieurs * ratio_e, 1)
            env.murs_exterieurs_ouest = round(env.murs_exterieurs * ratio_o, 1)
        else:
            quart = env.murs_exterieurs / 4
            env.murs_exterieurs_nord = round(quart, 1)
            env.murs_exterieurs_sud = round(quart, 1)
            env.murs_exterieurs_est = round(quart, 1)
            env.murs_exterieurs_ouest = round(quart, 1)

        # ================================================================
        # 3. MURS MITOYENS CHAUFFÉS INTERNES (avec les voisins du même étage)
        # ================================================================

        if voisins_meme_etage:
            surface_un_etage = surface_appt_total / nb_etages_vivienda
            cote_appt = math.sqrt(surface_un_etage)
            env.murs_mitoyens_chauffes += round(cote_appt * h * len(voisins_meme_etage), 1)

        # ================================================================
        # 3. PLANCHER — basé sur l'étage le plus bas de la vivienda
        # ================================================================

        if etage_min_int <= -1:
            # Semi-sous-sol (SM/SO/SS) : vivienda posée sur le sol → terre-plein
            surface_sm_viv = etages_vivienda.get(etage_min, 0)
            env.plancher_terre_plein = surface_sm_viv
            print(f"      Plancher: {surface_sm_viv} m² sur terre-plein (planta {etage_min})")
            # Si LNC au même étage SM → plancher sur LNC pour l'étage au-dessus
            surface_lnc_sm = etages_lnc.get(etage_min, 0)
            if surface_lnc_sm > 0:
                env.plancher_sur_lnc = surface_lnc_sm
                print(f"      Plancher: {surface_lnc_sm} m² sur LNC (au-dessus parking {etage_min})")
        elif etage_min_int == 0 and a_sous_sol:
            # RDC avec sous-sol en dessous → plancher sur LNC
            surface_rdc = etages_vivienda.get("00", 0)
            env.plancher_sur_lnc = surface_rdc
            print(f"      Plancher: {surface_rdc} m² sur LNC (sous-sol détecté)")
        elif etage_min_int == 0:
            # RDC sans sous-sol → terre-plein
            surface_rdc = etages_vivienda.get("00", 0)
            env.plancher_terre_plein = surface_rdc
            print(f"      Plancher: {surface_rdc} m² sur terre-plein")
        elif etage_min_int >= 1:
            # Étage supérieur → vérifier ce qui est en dessous
            surface_etage_bas = etages_vivienda.get(etage_min, surface_appt_total)
            # Chercher si étage en dessous a des locaux chauffés
            planta_dessous = f"{etage_min_int - 1:02d}"
            chauffes_dessous = any(
                c.est_chauffee and c.planta == planta_dessous
                for inm in self.resultat.inmuebles
                for c in inm.construcciones
            )
            lnc_dessous = any(
                not c.est_chauffee and c.planta == planta_dessous
                for inm in self.resultat.inmuebles
                for c in inm.construcciones
            )
            if chauffes_dessous:
                env.plancher_sur_local_chauffe = surface_etage_bas
                print(f"      Plancher: {surface_etage_bas} m² sur local chauffé (adiabatique)")
            elif lnc_dessous:
                env.plancher_sur_lnc = surface_etage_bas
                print(f"      Plancher: {surface_etage_bas} m² sur LNC")
            else:
                env.plancher_terre_plein = surface_etage_bas
                print(f"      Plancher: {surface_etage_bas} m² sur terre-plein (pas d'info sous)")

        # ================================================================
        # 4. TOITURE — basée sur les toits exposés au-dessus de la vivienda
        # ================================================================
        # Pour un bâtiment en escalier (parties de hauteurs différentes),
        # la toiture inclut le toit de chaque partie au-dessus d'un étage vivienda.
        # On soustrait l'emprise des parties plus hautes (elles couvrent le plancher).

        if est_dernier_etage:
            env.toiture = surface_dernier
            self.resultat.est_dernier_etage = True
            self.resultat.alerte_combles = None

            # Bâtiment en escalier : la partie principale est plus basse que la plus haute
            if partie_principale and len(parties) >= 2:
                max_etages = max(p.nb_etages_estime for p in parties)
                if partie_principale.nb_etages_estime < max_etages:
                    pp_top = f"{partie_principale.nb_etages_estime - 1:02d}"
                    viv_pp_top = etages_vivienda.get(pp_top, 0)
                    # Soustraire l'emprise des parties plus hautes (elles couvrent cette zone)
                    emprise_plus_haute = sum(
                        p.surface_au_sol for p in parties
                        if p.nb_etages_estime > partie_principale.nb_etages_estime
                    )
                    toiture_pp = max(0, viv_pp_top - emprise_plus_haute)
                    if toiture_pp > 0:
                        env.toiture += toiture_pp
                        print(f"      Toiture basse (Part principale, planta {pp_top}): {toiture_pp} m²")

            print(f"      Toiture: {env.toiture:.0f} m² (planta {etage_max}: {surface_dernier}m²"
                  f"{f' + toit partie principale' if env.toiture > surface_dernier else ''})")
        else:
            env.plafond_sous_local_chauffe = surface_dernier
            self.resultat.est_dernier_etage = False
            self.resultat.etage_combles = etage_max_batiment
            self.resultat.alerte_combles = (
                f"CET APPARTEMENT N'A PAS DE COMBLES A ISOLER !\n"
                f"   -> Votre appartement est a l'etage {etage_max_int:02d}\n"
                f"   -> Les combles sont au-dessus de l'etage {etage_max_batiment:02d}\n"
                f"   -> Le plafond donne sur un autre logement chauffe (adiabatique)"
            )

        # ================================================================
        # 5. HUECOS (FENÊTRES) — estimation normative
        # ================================================================

        estimer_huecos(self.resultat.annee_construction, env)

        print("      Calculs termines")

    def _verifier_position_combles(self, plantas: Dict, plantas_chauffees: List[str]):
        """
        Vérifie si l'appartement/VIVIENDA est au dernier étage (accès aux combles).
        
        Pour les appartements:
        - Si l'appartement n'est PAS au dernier étage → alerte "pas de combles"
        - Seuls les appartements au dernier étage ont accès à la toiture/combles
        """
        if not plantas_chauffees:
            return
        
        # Déterminer l'étage maximum du bâtiment (selon les données de construction)
        tous_les_etages = list(plantas.keys())
        if not tous_les_etages:
            return
        
        etage_max_batiment = max(int(p) for p in tous_les_etages)
        
        # Déterminer l'étage maximum de la VIVIENDA analysée
        etage_max_vivienda = max(int(p) for p in plantas_chauffees)
        
        # Stocker l'étage des combles
        self.resultat.etage_combles = etage_max_batiment
        
        # Vérifier si la VIVIENDA est au dernier étage
        if etage_max_vivienda >= etage_max_batiment:
            self.resultat.est_dernier_etage = True
            self.resultat.alerte_combles = None
        else:
            self.resultat.est_dernier_etage = False
            
            # Générer l'alerte
            if self.resultat.type_batiment == TypeBatiment.APPARTEMENT:
                self.resultat.alerte_combles = (
                    f"⚠️ CET APPARTEMENT N'A PAS DE COMBLES À ISOLER !\n"
                    f"   → L'appartement est à l'étage {etage_max_vivienda:02d}\n"
                    f"   → Les combles sont au-dessus de l'étage {etage_max_batiment:02d}\n"
                    f"   → Pas d'isolation de toiture/combles nécessaire pour cet appartement\n"
                    f"   → Le plafond donne sur un autre logement chauffé (adiabatique)"
                )
            else:
                # Pour les maisons avec plusieurs étages mais VIVIENDA pas au dernier
                if etage_max_vivienda < etage_max_batiment:
                    self.resultat.alerte_combles = (
                        f"⚠️ LA VIVIENDA N'EST PAS AU DERNIER ÉTAGE !\n"
                        f"   → La VIVIENDA est à l'étage {etage_max_vivienda:02d}\n"
                        f"   → Il y a des espaces au-dessus (étage {etage_max_batiment:02d})\n"
                        f"   → Vérifier si le plafond donne sur LNC ou local chauffé"
                    )


# ============================================================================
# AFFICHAGE DES RÉSULTATS
# ============================================================================

def afficher_resultats(r: ResultatAnalyse):
    """Affiche les résultats de manière formatée"""
    
    print(f"\n{'═'*70}")
    print(f"  RÉSULTATS DE L'ANALYSE")
    print(f"{'═'*70}")
    
    # Informations générales
    utm_str = f"{r.utm_zone} X : {int(r.utm_x)} m, Y : {int(r.utm_y)} m" if r.utm_x else "N/A"
    wgs84_str = f"Lon: {r.coord_wgs84_lon}°, Lat: {r.coord_wgs84_lat}°" if r.coord_wgs84_lon else "N/A"
    adresse_str = (r.adresse or 'N/A')[:42]
    hauteur_str = f"{r.hauteur_etage}m" + (f" (max GML: {r.hauteur_max_gml}m)" if r.hauteur_max_gml else "")
    print(f"""
┌─────────────────────────────────────────────────────────────────────┐
│ INFORMATIONS GÉNÉRALES                                              │
├─────────────────────────────────────────────────────────────────────┤
│ Référence cadastrale    │ {r.referencia:<42} │
│ Type de bâtiment        │ {r.type_batiment.value:<42} │
│ Adresse                 │ {adresse_str:<42} │
│ Année de construction   │ {str(r.annee_construction or 'N/A'):<42} │
│ Nombre d'étages         │ {r.nombre_etages:<42} │
│ Hauteur d'étage         │ {hauteur_str:<42} │
│ UTM                     │ {utm_str:<42} │
│ WGS84                   │ {wgs84_str:<42} │
└─────────────────────────────────────────────────────────────────────┘
""")
    
    # Afficher lien photo façade
    if r.url_photo_facade:
        print(f"📷 Photo façade: {r.url_photo_facade}\n")
    
    # Surfaces
    print(f"""
┌─────────────────────────────────────────────────────────────────────┐
│ SURFACES                                                            │
├─────────────────────────────────────────────────────────────────────┤
│ Surface habitable (VIVIENDA)     │ {r.surface_utile:>10} m²                    │
│ Surface construite totale        │ {r.surface_totale:>10} m²                    │
└─────────────────────────────────────────────────────────────────────┘
""")
    
    # Détail par inmueble
    if r.inmuebles:
        print("┌─────────────────────────────────────────────────────────────────────┐")
        print("│ DÉTAIL PAR UNITÉ                                                    │")
        print("├─────────────────────────────────────────────────────────────────────┤")
        
        for i, inm in enumerate(r.inmuebles, 1):
            print(f"│ [{i}] {inm.referencia_20:<62} │")
            for c in inm.construcciones:
                symbole = "✓" if c.est_chauffee else "✗"
                ligne = f"│     [{symbole}] {c.uso}: {c.superficie_m2} m²"
                if c.planta and c.planta != "00":
                    ligne += f" (Planta {c.planta})"
                print(f"{ligne:<70}│")
        
        print("└─────────────────────────────────────────────────────────────────────┘")
    
    # Enveloppe thermique
    env = r.enveloppe
    print(f"""
┌─────────────────────────────────────────────────────────────────────┐
│ ENVELOPPE THERMIQUE CE3X                                            │
├─────────────────────────────────────────────────────────────────────┤
│ Murs extérieurs                  │ {env.murs_exterieurs:>10.1f} m²                    │
│   - Nord                         │ {env.murs_exterieurs_nord:>10.1f} m²                    │
│   - Sud                          │ {env.murs_exterieurs_sud:>10.1f} m²                    │
│   - Est                          │ {env.murs_exterieurs_est:>10.1f} m²                    │
│   - Ouest                        │ {env.murs_exterieurs_ouest:>10.1f} m²                    │
│ Murs mitoyens avec LNC           │ {env.murs_mitoyens_lnc:>10.1f} m²                    │
│ Murs mitoyens chauffés           │ {env.murs_mitoyens_chauffes:>10.1f} m²  (adiabatique)  │
│ Plancher sur terre-plein         │ {env.plancher_terre_plein:>10.0f} m²                    │
│ Plancher sur LNC                 │ {env.plancher_sur_lnc:>10.0f} m²                    │
│ Plancher sur local chauffé       │ {env.plancher_sur_local_chauffe:>10.0f} m²  (adiabatique)  │
│ Plafond sous local chauffé       │ {env.plafond_sous_local_chauffe:>10.0f} m²  (adiabatique)  │
│ Toiture                          │ {env.toiture:>10.0f} m²                    │
├─────────────────────────────────────────────────────────────────────┤
│ Huecos (fenêtres)               │ {env.huecos_total:>10.1f} m²  (ratio {env.ratio_huecos_murs:.0%})     │
│   - Nord                         │ {env.huecos_nord:>10.1f} m²                    │
│   - Sud                          │ {env.huecos_sud:>10.1f} m²                    │
│   - Est                          │ {env.huecos_est:>10.1f} m²                    │
│   - Ouest                        │ {env.huecos_ouest:>10.1f} m²                    │
│ Vitrage estimé                   │ {env.tipo_vidrio:>24s}    │
│ Menuiserie estimée               │ {env.tipo_marco:>24s}    │
└─────────────────────────────────────────────────────────────────────┘
""")
    
    # Alerte combles (si applicable)
    if r.alerte_combles:
        print("""
┌─────────────────────────────────────────────────────────────────────┐
│ 🚨 ALERTE ISOLATION COMBLES                                         │
├─────────────────────────────────────────────────────────────────────┤""")
        for ligne in r.alerte_combles.split('\n'):
            print(f"│ {ligne:<67} │")
        print("└─────────────────────────────────────────────────────────────────────┘")
    elif r.est_dernier_etage and r.type_batiment == TypeBatiment.APPARTEMENT:
        print("""
┌─────────────────────────────────────────────────────────────────────┐
│ ✅ APPARTEMENT AU DERNIER ÉTAGE                                      │
├─────────────────────────────────────────────────────────────────────┤
│ Cet appartement a accès aux combles/toiture.                        │
│ → Isolation de toiture/combles NÉCESSAIRE                           │
└─────────────────────────────────────────────────────────────────────┘
""")
    
    # Notes
    print("""
┌─────────────────────────────────────────────────────────────────────┐
│ ⚠ NOTES                                                             │
│ - Les surfaces sont des ESTIMATIONS basées sur les données          │
│   cadastrales publiques.                                            │
│ - Pour des valeurs exactes, consulter les plans architecturaux.     │
│ - LNC = Local Non Chauffé                                           │
└─────────────────────────────────────────────────────────────────────┘
""")


def telecharger_photo_facade(ref: str, output_dir: str = ".") -> Optional[str]:
    """Télécharge la photo de façade et retourne le chemin du fichier"""
    ref14 = ref[:14]
    url = f"https://ovc.catastro.meh.es/OVCServWeb/OVCWcfLibres/OVCFotoFachada.svc/RecuperarFotoFachadaGet?ReferenciaCatastral={ref14}"
    
    try:
        r = faire_requete(url, timeout=15)
        if not r:
            return None

        if r.status_code == 200 and 'image' in r.headers.get('Content-Type', ''):
            filename = os.path.join(output_dir, "photo_facade.jpg")
            with open(filename, 'wb') as f:
                f.write(r.content)
            return filename
        return None
    except Exception as e:
        logger.warning(f"Erreur téléchargement photo facade pour {ref14}: {e}")
        return None


def telecharger_carte_localisation(resultat: ResultatAnalyse, output_dir: str = ".") -> Optional[str]:
    """
    Télécharge une carte de localisation depuis les WMS cadastral + ortho PNOA.
    Superpose la photo aérienne et les parcelles cadastrales.
    """
    if not resultat.utm_x or not resultat.utm_y:
        return None
    
    x = resultat.utm_x
    y = resultat.utm_y
    zone = resultat.utm_zone
    
    taille = 500  # pixels
    marge = 80    # mètres autour du point
    
    # Bounding box autour du point (en mètres UTM)
    bbox = f"{x - marge},{y - marge},{x + marge},{y + marge}"
    epsg = f"258{zone}"  # 25829 pour zone 29, 25830 pour zone 30
    
    # URLs des services WMS
    pnoa_url = "https://www.ign.es/wms-inspire/pnoa-ma"
    cadastre_url = "https://ovc.catastro.meh.es/Cartografia/WMS/ServidorWMS.aspx"
    
    params_pnoa = {
        "SERVICE": "WMS",
        "VERSION": "1.1.1",
        "REQUEST": "GetMap",
        "LAYERS": "OI.OrthoimageCoverage",
        "SRS": f"EPSG:{epsg}",
        "BBOX": bbox,
        "WIDTH": taille,
        "HEIGHT": taille,
        "FORMAT": "image/png"
    }
    
    params_cadastre = {
        "SERVICE": "WMS",
        "VERSION": "1.1.1",
        "REQUEST": "GetMap",
        "LAYERS": "Catastro",
        "SRS": f"EPSG:{epsg}",
        "BBOX": bbox,
        "WIDTH": taille,
        "HEIGHT": taille,
        "FORMAT": "image/png",
        "TRANSPARENT": "TRUE"
    }
    
    filename = os.path.join(output_dir, "carte_localisation.png")
    
    try:
        # Essayer de superposer ortho + cadastre avec PIL
        from PIL import Image
        from io import BytesIO
        
        resp_pnoa = faire_requete(pnoa_url, params=params_pnoa, timeout=30)
        resp_cadastre = faire_requete(cadastre_url, params=params_cadastre, timeout=30)
        if not resp_pnoa or not resp_cadastre:
            return None
        
        if "image" in resp_pnoa.headers.get("Content-Type", "") and "image" in resp_cadastre.headers.get("Content-Type", ""):
            img_pnoa = Image.open(BytesIO(resp_pnoa.content)).convert("RGBA")
            img_cadastre = Image.open(BytesIO(resp_cadastre.content)).convert("RGBA")
            img_final = Image.alpha_composite(img_pnoa, img_cadastre)
            img_final.save(filename, "PNG")
            return filename
        
        # Fallback: cadastre seul si ortho échoue
        if "image" in resp_cadastre.headers.get("Content-Type", ""):
            with open(filename, "wb") as f:
                f.write(resp_cadastre.content)
            return filename
            
        return None
        
    except ImportError:
        # PIL non installé - télécharger juste le cadastre
        logger.info("Pillow non installé, téléchargement carte cadastre seule")
        try:
            resp = faire_requete(cadastre_url, params=params_cadastre, timeout=30)
            if resp and "image" in resp.headers.get("Content-Type", ""):
                with open(filename, "wb") as f:
                    f.write(resp.content)
                return filename
        except Exception as e:
            logger.warning(f"Erreur téléchargement carte cadastre (fallback): {e}")
        return None
    except Exception as e:
        logger.warning(f"Erreur téléchargement carte localisation: {e}")
        return None


def sauvegarder_json(r: ResultatAnalyse, fichier: str = "resultat_ce3x.json"):
    """Sauvegarde les résultats en JSON"""
    
    data = {
        'referencia': r.referencia,
        'type_batiment': r.type_batiment.value,
        'province': r.province,
        'municipalite': r.municipalite,
        'adresse': r.adresse,
        'annee_construction': r.annee_construction,
        'nombre_etages': r.nombre_etages,
        'hauteur_etage': r.hauteur_etage,
        'hauteur_max_gml': r.hauteur_max_gml,
        'perimetre': r.perimetre,
        'coordonnees': {
            'utm': {
                'zone': r.utm_zone,
                'x': int(r.utm_x) if r.utm_x else None,
                'y': int(r.utm_y) if r.utm_y else None,
                'unite': 'm',
                'systeme': f'ETRS89 / UTM zone {r.utm_zone}N (EPSG:258{r.utm_zone})'
            },
            'wgs84': {
                'longitude': r.coord_wgs84_lon,
                'latitude': r.coord_wgs84_lat
            }
        },
        'photo_facade': {
            'url': r.url_photo_facade,
            'fichier_local': r.fichier_photo_facade
        },
        'carte_localisation': {
            'fichier_local': r.fichier_carte_localisation
        },
        'parties_batiment_gml': [
            {
                'nom': p.nom,
                'hauteur_m': p.hauteur_m,
                'style': p.style,
                'nb_etages_dessus': p.nb_etages_estime,
                'nb_etages_sous_sol': p.nb_etages_sous_sol,
                'hauteur_sous_sol_m': p.hauteur_sous_sol,
                'surface_au_sol_m2': p.surface_au_sol,
            }
            for p in r.parties_batiment
        ],
        'surfaces': {
            'habitable_vivienda': r.surface_utile,
            'construite_totale': r.surface_totale
        },
        'position_combles': {
            'est_dernier_etage': r.est_dernier_etage,
            'etage_combles': r.etage_combles,
            'alerte': r.alerte_combles
        },
        'batiments_voisins': len(r.polygones_voisins),
        'inmuebles': [
            {
                'referencia_20': inm.referencia_20,
                'construcciones': [asdict(c) for c in inm.construcciones]
            }
            for inm in r.inmuebles
        ],
        'enveloppe_thermique': asdict(r.enveloppe),
        'fxcc': {
            'disponible': r.fxcc is not None,
            'del_code': r.del_code,
            'mun_code': r.mun_code,
        }
    }
    
    with open(fichier, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    print(f"\n[SAVE] {fichier}")


# ============================================================================
# POINT D'ENTRÉE
# ============================================================================

def main():
    """Point d'entrée principal"""
    
    print("""
╔══════════════════════════════════════════════════════════════════════════════╗
║                    ANALYSE THERMIQUE CE3X - CADASTRE ESPAGNOL                ║
╚══════════════════════════════════════════════════════════════════════════════╝
    """)
    
    # Récupérer la référence cadastrale
    if len(sys.argv) > 1:
        referencia = sys.argv[1]
    else:
        referencia = input("Entrez la référence cadastrale: ").strip()
    
    if not referencia:
        print("Erreur: référence cadastrale requise")
        sys.exit(1)
    
    # Lancer l'analyse
    analyseur = AnalyseurCE3X(referencia)
    resultat = analyseur.analyser()
    
    # Créer le dossier de résultats pour cette référence
    # Utiliser la référence complète (20 chars si disponible, sinon 14)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    dossier_resultats = os.path.join(script_dir, "resultats", resultat.referencia)
    os.makedirs(dossier_resultats, exist_ok=True)
    print(f"\n[DOSSIER] {dossier_resultats}/")
    
    # Afficher les résultats
    afficher_resultats(resultat)
    
    # Télécharger la photo de façade dans le dossier
    photo_path = telecharger_photo_facade(resultat.referencia, dossier_resultats)
    if photo_path:
        resultat.fichier_photo_facade = photo_path
        print(f"[PHOTO] {photo_path}")
    
    # Télécharger la carte de localisation dans le dossier
    carte_path = telecharger_carte_localisation(resultat, dossier_resultats)
    if carte_path:
        resultat.fichier_carte_localisation = carte_path
        print(f"[CARTE] {carte_path}")

    # Sauvegarder le JSON dans le dossier
    json_path = os.path.join(dossier_resultats, "resultat_ce3x.json")
    sauvegarder_json(resultat, json_path)
    
    return resultat


if __name__ == '__main__':
    main()

