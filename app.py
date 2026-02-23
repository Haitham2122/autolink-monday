from typing import Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from datetime import datetime
import json
import logging
import requests
import re
import shutil
# Import des fonctions Monday.com
from monday_api import (
    get_column_value_for_item,
    get_item_ids_by_column_value,
    get_all_column_values_for_item,
    update_item_columns,
    clear_item_columns,
    format_column_value_for_update,
    update_status_column,
    add_file_to_column,
    get_item_assets,
    add_update_to_item,
    check_item_exists
)

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Monday.com Auto-Link System",
    description="Système d'auto-link entre deux tableaux Monday.com",
    version="1.0.0"
)

# Configuration Monday.com API
apiKey = "eyJhbGciOiJIUzI1NiJ9.eyJ0aWQiOjUyNTUxMDkxOCwiYWFpIjoxMSwidWlkIjo3NjM3MTkxNiwiaWFkIjoiMjAyNS0wNi0xMlQxMjowMjowNi4wMDBaIiwicGVyIjoibWU6d3JpdGUiLCJhY3RpZCI6MTQ5ODgzMDQsInJnbiI6InVzZTEifQ.g8M5fmXYZ3eNUQWiPpnKmPHf1K0wrwdqi2HJFFl1P0Q"

# Configuration API Monday.com pour récupération dynamique
MONDAY_API_URL = "https://api.monday.com/v2"
WORKSPACE_ID = 10987132

# Chargement de la configuration
with open('config.json', 'r', encoding='utf-8') as f:
    config = json.load(f)

# Chargement du mapping des colonnes
with open('column_mapping.json', 'r', encoding='utf-8') as f:
    column_mapping = json.load(f)

# Chargement de la configuration Install -> Régie
with open('config_install_regie.json', 'r', encoding='utf-8') as f:
    config_install_regie = json.load(f)

# Chargement du cache des régies
with open('regies_cache.json', 'r', encoding='utf-8') as f:
    regies_cache = json.load(f)

# Chargement de la configuration TagList
with open('config_taglist.json', 'r', encoding='utf-8') as f:
    config_taglist = json.load(f)

# Extraction dynamique des IDs de colonnes du tableau principal depuis le mapping
principal_column_ids = [mapping['principal']['id'] for mapping in column_mapping]
logger.info(f"Colonnes à récupérer du tableau principal: {len(principal_column_ids)} colonnes")
logger.info(f"IDs: {principal_column_ids}")
logger.info(f"Régies en cache: {len(regies_cache)} régies")


@app.get("/")
async def root():
    """Endpoint de base pour vérifier que l'API fonctionne"""
    return {
        "message": "Monday.com Auto-Link System",
        "status": "running",
        "timestamp": datetime.utcnow().isoformat(),
        "endpoints": {
            "auto-link": "/auto-link (Principal → Admin)",
            "install-to-regie": "/install-to-regie (Install → Régie)",
            "generate-taglist": "/generate-taglist (Install → TagList JSON)"
        },
        "config": {
            "admin_board_id": config["admin_board_id"],
            "install_board_id": config_install_regie["install_board_id"],
            "regies_in_cache": len(regies_cache)
        }
    }


@app.post("/auto-link")
async def auto_link(request: Dict[Any, Any]):
    """
    Endpoint webhook - Auto-link complet
    
    1. Reçoit le webhook avec l'ID de l'item du tableau principal
    2. Récupère la valeur de la colonne ID_admin de cet item
    3. Cherche l'item correspondant dans le tableau admin
    4. Récupère les colonnes du tableau principal
    5. Met à jour le tableau admin avec les valeurs
    """
    try:
        logger.info("=" * 80)
        logger.info("Webhook Auto-Link reçu - MODE TEST")
        logger.info(f"Payload complet: {json.dumps(request, indent=2)}")
        
        # ÉTAPE 1: Extraire l'ID de l'item du tableau principal (ID_)
        event = request.get('event', {})
        id_ = int(event.get('pulseId'))
        logger.info(f"✓ ÉTAPE 1 - ID_ (item tableau principal): {id_}")
        
        # ÉTAPE 2: Récupérer la valeur de la colonne ID_admin du tableau principal
        logger.info(f"→ ÉTAPE 2 - Récupération de l'ID_admin depuis la colonne '{config['main_id_column']}'")
        id_admin_data = get_column_value_for_item(
            apiKey, 
            id_, 
            config['main_id_column']
        )
        
        if not id_admin_data:
            raise HTTPException(
                status_code=404, 
                detail=f"Colonne ID_admin non trouvée pour l'item {id_}"
            )
        
        id_admin_value = id_admin_data['text']
        logger.info(f"✓ ÉTAPE 2 - Valeur ID_admin trouvée: {id_admin_value}")
        logger.info(f"  Détails: {id_admin_data}")
        
        # ÉTAPE 3: Chercher l'item correspondant dans le tableau admin (ID__)
        logger.info(f"→ ÉTAPE 3 - Recherche de l'item admin avec ID_admin='{id_admin_value}'")
        logger.info(f"  Board admin: {config['admin_board_id']}")
        logger.info(f"  Colonne recherche: {config['admin_id_column']}")
        
        admin_item_ids = get_item_ids_by_column_value(
            apiKey,
            config['admin_board_id'],
            config['admin_id_column'],
            id_admin_value
        )
        
        if not admin_item_ids:
            logger.error(f"✗ ÉTAPE 3 - Aucun item admin trouvé avec ID_admin={id_admin_value}")
            raise HTTPException(
                status_code=404,
                detail=f"Aucun item admin trouvé avec ID_admin={id_admin_value}"
            )
        
        if len(admin_item_ids) > 1:
            logger.warning(f"⚠ ÉTAPE 3 - Plusieurs items admin trouvés: {admin_item_ids}. Utilisation du premier.")
        
        id__ = admin_item_ids[0]
        logger.info(f"✓ ÉTAPE 3 - ID__ (item tableau admin trouvé): {id__}")
        
        # ÉTAPE 4 (BONUS): Récupérer les données du tableau principal pour voir ce qu'on a
        logger.info("=" * 80)
        logger.info("→ ÉTAPE 4 (BONUS) - Récupération des données du tableau principal")
        logger.info(f"  Récupération de {len(principal_column_ids)} colonnes")
        
        item_data = get_all_column_values_for_item(apiKey, id_, principal_column_ids)
        
        logger.info(f"✓ ÉTAPE 4 - Données récupérées")
        logger.info(f"  ID Item: {item_data['id']}")
        logger.info(f"  Nom Item: {item_data['name']}")
        logger.info(f"  Nombre de colonnes récupérées: {len(item_data['columns'])}")
        
        # ÉTAPE 4B: Récupérer les assets (fichiers) de l'item principal
        logger.info(f"→ ÉTAPE 4B - Récupération des assets (fichiers)")
        assets = get_item_assets(apiKey, id_)
        logger.info(f"✓ ÉTAPE 4B - {len(assets)} assets récupérés")
        
        # Créer un dictionnaire assetId -> asset_info pour mapping rapide
        assets_by_id = {}
        for asset in assets:
            assets_by_id[asset['id']] = {
                'name': asset['name'],
                'public_url': asset['public_url'],
                'file_extension': asset.get('file_extension', ''),
                'file_size': asset.get('file_size', 0)
            }
        logger.info(f"  Assets indexés par ID pour mapping")
        
        # Afficher les colonnes avec leurs valeurs
        logger.info("  DÉTAIL DES COLONNES:")
        for col_id, col_data in item_data['columns'].items():
            # Trouver le titre dans le mapping
            col_title = next((m['principal']['title'] for m in column_mapping if m['principal']['id'] == col_id), col_id)
            text_value = col_data['text'] if col_data['text'] else '(vide)'
            logger.info(f"    - {col_title} ({col_id}): {text_value}")
        
        # ÉTAPE 5: Préparer et transférer les colonnes vers le tableau admin
        logger.info("=" * 80)
        logger.info("→ ÉTAPE 5 - Transfert des colonnes vers le tableau admin")
        
        # Préparer les valeurs à transférer selon le mapping
        columns_to_transfer = {}
        status_columns = {}  # Colonnes status à traiter séparément
        file_columns = {}  # Colonnes fichiers à traiter séparément
        transfer_summary = []
        
        for mapping_item in column_mapping:
            principal_col_id = mapping_item['principal']['id']
            admin_col_id = mapping_item['admin']['id']
            col_title = mapping_item['principal']['title']
            
            # Vérifier si la colonne existe dans les données récupérées
            if principal_col_id in item_data['columns']:
                col_data = item_data['columns'][principal_col_id]
                col_type = col_data['type']
                raw_value = col_data['value']
                text_value = col_data['text']
                
                # Formater la valeur selon le type
                formatted_value = format_column_value_for_update(col_type, raw_value, text_value)
                
                # Ignorer si la valeur est None (colonnes read-only, etc.)
                if formatted_value is not None:
                    # Si c'est un status, le traiter séparément
                    if isinstance(formatted_value, dict) and formatted_value.get("use_text"):
                        status_columns[admin_col_id] = formatted_value["text"]
                        transfer_summary.append({
                            'title': col_title,
                            'type': col_type,
                            'principal_id': principal_col_id,
                            'admin_id': admin_col_id,
                            'value': text_value if text_value else '(vide)'
                        })
                        logger.info(f"  ✓ {col_title} ({col_type}): {principal_col_id} → {admin_col_id} [par texte: '{text_value}']")
                    # Si c'est un fichier à copier, le traiter séparément
                    elif isinstance(formatted_value, dict) and formatted_value.get("copy_files"):
                        # Mapper les assetIds vers les public_urls
                        asset_ids = formatted_value['asset_ids']
                        files_info = []
                        
                        for asset_id in asset_ids:
                            if asset_id in assets_by_id:
                                asset_info = assets_by_id[asset_id]
                                files_info.append({
                                    'asset_id': asset_id,
                                    'name': asset_info['name'],
                                    'public_url': asset_info['public_url'],
                                    'file_extension': asset_info['file_extension'],
                                    'file_size': asset_info['file_size']
                                })
                        
                        if files_info:
                            file_columns[admin_col_id] = {
                                'title': col_title,
                                'files': files_info
                            }
                            transfer_summary.append({
                                'title': col_title,
                                'type': col_type,
                                'principal_id': principal_col_id,
                                'admin_id': admin_col_id,
                                'value': f"{len(files_info)} fichier(s)"
                            })
                            logger.info(f"  📎 {col_title} ({col_type}): {principal_col_id} → {admin_col_id} [{len(files_info)} fichier(s) à copier]")
                    else:
                        columns_to_transfer[admin_col_id] = formatted_value
                        transfer_summary.append({
                            'title': col_title,
                            'type': col_type,
                            'principal_id': principal_col_id,
                            'admin_id': admin_col_id,
                            'value': text_value if text_value else '(vide)'
                        })
                        # Log spécial pour les fichiers vidés
                        if col_type == 'file' and isinstance(formatted_value, dict) and formatted_value.get("clear_all"):
                            logger.info(f"  🗑️ {col_title} ({col_type}): {principal_col_id} → {admin_col_id} [VIDÉ]")
                        else:
                            logger.info(f"  ✓ {col_title} ({col_type}): {principal_col_id} → {admin_col_id}")
                else:
                    logger.info(f"  ⊘ {col_title} ({col_type}): ignoré (read-only)")
            else:
                logger.warning(f"  ✗ {col_title}: colonne {principal_col_id} non trouvée")
        
        total_columns = len(columns_to_transfer) + len(status_columns) + len(file_columns)
        logger.info(f"✓ ÉTAPE 5 - {total_columns} colonnes préparées ({len(columns_to_transfer)} normales + {len(status_columns)} status + {len(file_columns)} fichiers)")
        
        # ÉTAPE 6A: Mise à jour des colonnes normales (en batch)
        logger.info("=" * 80)
        logger.info(f"→ ÉTAPE 6A - Mise à jour des colonnes normales ({len(columns_to_transfer)} colonnes)")
        
        if columns_to_transfer:
            update_result = update_item_columns(
                apiKey,
                id__,
                config['admin_board_id'],
                columns_to_transfer
            )
            logger.info(f"✓ ÉTAPE 6A - Colonnes normales mises à jour!")
            logger.info(f"  Item mis à jour: {update_result['id']}")
        else:
            logger.info("⊘ Aucune colonne normale à transférer")
        
        # ÉTAPE 6B: Mise à jour des colonnes status (une par une, par texte)
        if status_columns:
            logger.info("=" * 80)
            logger.info(f"→ ÉTAPE 6B - Mise à jour des colonnes status ({len(status_columns)} colonnes)")
            
            for status_col_id, status_text in status_columns.items():
                try:
                    update_status_column(
                        apiKey,
                        id__,
                        config['admin_board_id'],
                        status_col_id,
                        status_text
                    )
                    logger.info(f"  ✓ Status mis à jour: {status_col_id} = '{status_text}'")
                except Exception as e:
                    logger.error(f"  ✗ Erreur status {status_col_id}: {e}")
            
            logger.info(f"✓ ÉTAPE 6B - Statuts mis à jour par texte!")
        else:
            logger.info("⊘ Aucune colonne status à transférer")
        
        # ÉTAPE 6C: Copie des fichiers (mapping précis par colonne)
        if file_columns:
            logger.info("=" * 80)
            logger.info(f"→ ÉTAPE 6C - Copie des fichiers ({len(file_columns)} colonnes)")
            
            for file_col_id, file_info in file_columns.items():
                col_title = file_info['title']
                files_to_copy = file_info['files']
                
                logger.info(f"  → Colonne '{col_title}' ({file_col_id}): {len(files_to_copy)} fichier(s)")
                
                # ÉTAPE 6C.1: Vider la colonne fichier AVANT de copier
                try:
                    logger.info(f"    🗑️ Vidage de la colonne avant copie...")
                    update_item_columns(
                        apiKey,
                        id__,
                        config['admin_board_id'],
                        {file_col_id: {"clear_all": True}}
                    )
                    logger.info(f"    ✓ Colonne vidée")
                except Exception as e:
                    logger.error(f"    ✗ Erreur vidage colonne: {e}")
                
                # ÉTAPE 6C.2: Copier les nouveaux fichiers via public_url
                for file_data in files_to_copy:
                    file_name = file_data.get('name', 'fichier_sans_nom')
                    public_url = file_data.get('public_url')
                    file_size = file_data.get('file_size', 0)
                    
                    if not public_url:
                        logger.warning(f"    ✗ Fichier '{file_name}': pas de public_url disponible")
                        continue
                    
                    try:
                        # Télécharger et uploader le fichier
                        add_file_to_column(
                            apiKey,
                            id__,
                            file_col_id,
                            public_url,
                            file_name
                        )
                        logger.info(f"    ✓ Fichier copié: {file_name} ({file_size/1024:.2f} KB)")
                    except Exception as e:
                        logger.error(f"    ✗ Erreur copie fichier '{file_name}': {e}")
            
            logger.info(f"✓ ÉTAPE 6C - Fichiers copiés par colonne avec mapping précis!")
        else:
            logger.info("⊘ Aucun fichier à copier")
        
        logger.info("=" * 80)
        logger.info("AUTO-LINK RÉUSSI - Toutes les étapes fonctionnent correctement!")
        logger.info("=" * 80)
        
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "message": "AUTO-LINK RÉUSSI - Synchronisation complète effectuée",
                "results": {
                    "etape_1": {
                        "description": "Réception webhook",
                        "status": "✓ OK",
                        "id_principal": id_
                    },
                    "etape_2": {
                        "description": "Récupération ID_admin",
                        "status": "✓ OK",
                        "id_admin_value": id_admin_value
                    },
                    "etape_3": {
                        "description": "Recherche item admin",
                        "status": "✓ OK",
                        "id_admin_trouve": id__,
                        "nombre_items_trouves": len(admin_item_ids)
                    },
                    "etape_4": {
                        "description": "Récupération données tableau principal",
                        "status": "✓ OK",
                        "item_name": item_data['name'],
                        "colonnes_recuperees": len(item_data['columns'])
                    },
                    "etape_4b": {
                        "description": "Récupération assets (fichiers)",
                        "status": "✓ OK",
                        "assets_recuperes": len(assets)
                    },
                    "etape_5": {
                        "description": "Préparation des colonnes à transférer",
                        "status": "✓ OK",
                        "colonnes_preparees": len(columns_to_transfer)
                    },
                    "etape_6": {
                        "description": "Mise à jour item admin",
                        "status": "✓ OK" if columns_to_transfer else "⚠ SKIP",
                        "colonnes_transferees": len(columns_to_transfer)
                    }
                },
                "transfer_details": {
                    "item_principal": {
                        "id": item_data['id'],
                        "name": item_data['name']
                    },
                    "item_admin": {
                        "id": id__
                    },
                    "colonnes_transferees": transfer_summary
                },
                "configuration": {
                    "main_board_id": config['main_board_id'],
                    "admin_board_id": config['admin_board_id'],
                    "id_admin_value": id_admin_value
                },
                "timestamp": datetime.utcnow().isoformat()
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"ERREUR lors du test: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }
        )


def normalize_regie_name(name: str) -> str:
    """Normalise le nom de la régie pour la recherche dans le cache"""
    return re.sub(r'\s+', ' ', name.lower().strip())


def get_regie_board_from_api(regie_name: str) -> dict:
    """
    Récupère les infos d'une régie depuis l'API Monday.com.
    Cherche dans le workspace les boards dont le nom contient "Régie + nom".
    
    Ex: regie_name = "euroenergy" → cherche "Régie Euroenergy", etc.
    """
    headers = {
        "Authorization": apiKey,
        "Content-Type": "application/json",
        "API-Version": "2023-07"
    }
    
    logger.info(f"   🔎 Recherche API pour régie: '{regie_name}'")
    
    # Récupérer TOUS les tableaux du workspace (avec pagination)
    all_boards = []
    page = 1
    while True:
        query_boards = """
        query ($workspace_id: [ID!], $page: Int!) {
            boards (workspace_ids: $workspace_id, limit: 50, page: $page) {
                id
                name
            }
        }
        """
        
        response = requests.post(
            MONDAY_API_URL,
            headers=headers,
            json={"query": query_boards, "variables": {"workspace_id": [WORKSPACE_ID], "page": page}}
        )
        result = response.json()
        
        boards = result.get("data", {}).get("boards", [])
        if not boards:
            break
        
        all_boards.extend(boards)
        page += 1
        
        if page > 10:  # Sécurité max 500 boards
            break
    
    logger.info(f"   📋 {len(all_boards)} boards trouvés dans le workspace")
    
    # Chercher le tableau correspondant au nom de la régie
    normalized_name = normalize_regie_name(regie_name)
    target_board = None
    
    for board in all_boards:
        board_name = board["name"]
        board_name_lower = board_name.lower()
        
        # Ignorer les sous-éléments
        if "sous-élément" in board_name_lower or "subitems" in board_name_lower:
            continue
        
        # Vérifier si le nom du board contient "régie"
        if "régie" in board_name_lower or "regie" in board_name_lower:
            # Extraire le nom après "Régie "
            extracted = re.sub(r'^r[ée]gie\s+', '', board_name_lower, flags=re.IGNORECASE)
            # Enlever "V2", "V3", etc.
            extracted = re.sub(r'\s*v\d+\s*$', '', extracted, flags=re.IGNORECASE).strip()
            
            if normalized_name == extracted or normalized_name in extracted or extracted in normalized_name:
                target_board = board
                logger.info(f"   🎯 Board trouvé: '{board_name}' pour régie '{regie_name}'")
                break
    
    if not target_board:
        logger.error(f"   ❌ Aucun tableau trouvé pour la régie '{regie_name}'")
        # Logger quelques boards "Régie" pour debug
        regie_boards = [b['name'] for b in all_boards if 'régie' in b['name'].lower() or 'regie' in b['name'].lower()][:10]
        logger.error(f"   📋 Boards Régie disponibles: {regie_boards}")
        return None
    
    board_id = int(target_board["id"])
    board_name = target_board["name"]
    
    # 4. Récupérer les colonnes du tableau
    query_columns = """
    query ($board_id: ID!) {
        boards (ids: [$board_id]) {
            columns {
                id
                title
                type
            }
        }
    }
    """
    
    response = requests.post(
        MONDAY_API_URL,
        headers=headers,
        json={"query": query_columns, "variables": {"board_id": board_id}}
    )
    result = response.json()
    
    columns = result.get("data", {}).get("boards", [{}])[0].get("columns", [])
    
    # 5. Chercher les 3 colonnes cibles
    found_columns = {}
    for col in columns:
        col_title_lower = col["title"].lower()
        
        if "statut" in col_title_lower and "statut" not in found_columns:
            found_columns["statut"] = {"id": col["id"], "title": col["title"], "type": col["type"]}
        elif "surface" in col_title_lower and "comble" in col_title_lower:
            found_columns["surface_comble"] = {"id": col["id"], "title": col["title"], "type": col["type"]}
        elif "isolant" in col_title_lower:
            found_columns["type_isolant"] = {"id": col["id"], "title": col["title"], "type": col["type"]}
    
    logger.info(f"   📊 Colonnes trouvées: {list(found_columns.keys())}")
    
    return {
        "board_id": board_id,
        "board_name": board_name,
        "columns": found_columns
    }


def add_regie_to_cache(regie_name: str, regie_info: dict):
    """Ajoute une régie au cache et sauvegarde le fichier."""
    global regies_cache
    
    cache_key = normalize_regie_name(regie_name)
    regies_cache[cache_key] = regie_info
    
    # Sauvegarder le cache
    with open('regies_cache.json', 'w', encoding='utf-8') as f:
        json.dump(regies_cache, f, ensure_ascii=False, indent=2)
    
    logger.info(f"   💾 Régie '{regie_name}' ajoutée au cache (clé: '{cache_key}')")


def get_regie_info_from_cache(regie_name: str) -> dict:
    """
    Récupère les infos d'une régie depuis le cache.
    Si non trouvée, tente de la récupérer depuis l'API et l'ajoute au cache.
    """
    cache_key = normalize_regie_name(regie_name)
    
    # Recherche exacte
    if cache_key in regies_cache:
        logger.info(f"   📦 Cache HIT: '{cache_key}'")
        return regies_cache[cache_key]
    
    # Recherche partielle
    for key, data in regies_cache.items():
        if cache_key in key or key in cache_key:
            logger.info(f"   📦 Cache HIT (partiel): '{cache_key}' → '{key}'")
            return data
    
    # Non trouvé dans le cache → récupérer depuis l'API
    logger.info(f"   🔍 Cache MISS: '{cache_key}' - Récupération depuis l'API...")
    
    regie_info = get_regie_board_from_api(regie_name)
    
    if regie_info:
        add_regie_to_cache(regie_name, regie_info)
        return regie_info
    
    return None


@app.post("/install-to-regie")
async def install_to_regie(request: Dict[Any, Any]):
    """
    Endpoint webhook - Synchronisation Install → Régie
    
    Flux simplifié:
    1. Reçoit le webhook avec l'ID de l'item Install
    2. Récupère le nom de la régie (status) et l'ID de l'item Régie
    3. Récupère les 3 colonnes sources du tableau Install
    4. Met à jour les 3 colonnes dans le tableau Régie correspondant
    """
    try:
        logger.info("=" * 80)
        logger.info("Webhook Install-to-Régie reçu")
        logger.info(f"Payload: {json.dumps(request, indent=2)}")
        
        # ÉTAPE 1: Extraire l'ID de l'item Install
        event = request.get('event', {})
        install_item_id = int(event.get('pulseId'))
        logger.info(f"✓ ÉTAPE 1 - ID item Install: {install_item_id}")
        
        # ÉTAPE 2: Récupérer le nom de la régie et l'ID de l'item Régie
        logger.info(f"→ ÉTAPE 2 - Récupération des infos de liaison")
        
        # Colonnes à récupérer: nom régie + ID item régie
        columns_to_get = [
            config_install_regie['regie_name_column'],
            config_install_regie['regie_item_id_column']
        ]
        logger.info(f"   Colonnes à récupérer: {columns_to_get}")
        
        # Récupérer les valeurs
        install_data = get_all_column_values_for_item(apiKey, install_item_id, columns_to_get)
        
        if not install_data or not install_data.get('columns'):
            logger.error(f"   ✗ Item Install {install_item_id} non trouvé ou colonnes manquantes")
            logger.error(f"   install_data = {install_data}")
            raise HTTPException(
                status_code=404,
                detail=f"Item Install {install_item_id} non trouvé ou colonnes manquantes"
            )
        
        # Log des colonnes récupérées
        logger.info(f"   Colonnes récupérées: {list(install_data['columns'].keys())}")
        for col_id, col_data in install_data['columns'].items():
            logger.info(f"     - {col_id}: text='{col_data.get('text')}', type={col_data.get('type')}")
        
        # Extraire le nom de la régie
        regie_name_col = install_data['columns'].get(config_install_regie['regie_name_column'])
        regie_name = regie_name_col.get('text') if regie_name_col else None
        
        if not regie_name:
            logger.error(f"   ✗ Nom de la régie VIDE - Colonne {config_install_regie['regie_name_column']}")
            logger.error(f"   Données colonne: {regie_name_col}")
            raise HTTPException(
                status_code=400,
                detail=f"Nom de la régie non renseigné dans l'item Install {install_item_id}"
            )
        logger.info(f"   Nom régie: {regie_name}")
        
        # Extraire l'ID de l'item Régie
        regie_item_id_col = install_data['columns'].get(config_install_regie['regie_item_id_column'])
        regie_item_id_text = regie_item_id_col.get('text') if regie_item_id_col else None
        
        if not regie_item_id_text:
            error_msg = f"⚠️ ERREUR AUTO-LINK: L'ID de l'item Régie est VIDE dans la colonne {config_install_regie['regie_item_id_column']}. Veuillez renseigner l'ID de liaison."
            logger.error(f"   ✗ ID item Régie VIDE - Colonne {config_install_regie['regie_item_id_column']}")
            logger.error(f"   Données colonne: {regie_item_id_col}")
            
            # Ajouter un commentaire dans le tableau Install
            try:
                add_update_to_item(apiKey, install_item_id, error_msg)
                logger.info(f"   📝 Commentaire ajouté dans l'item Install")
            except Exception as e:
                logger.error(f"   ✗ Erreur ajout commentaire: {e}")
            
            # Mettre le status à "Erreur"
            try:
                update_status_column(
                    apiKey,
                    install_item_id,
                    config_install_regie['install_board_id'],
                    "color_mkxv17ya",
                    "Erreur"
                )
                logger.info(f"   ✓ Status Install mis à 'Erreur'")
            except Exception as e:
                logger.error(f"   ✗ Erreur mise à jour status: {e}")
            
            raise HTTPException(
                status_code=400,
                detail=f"ID de l'item Régie non renseigné dans l'item Install {install_item_id}"
            )
        
        try:
            regie_item_id = int(regie_item_id_text)
        except ValueError:
            logger.error(f"   ✗ ID item Régie invalide: '{regie_item_id_text}' n'est pas un nombre")
            raise HTTPException(
                status_code=400,
                detail=f"ID de l'item Régie invalide: '{regie_item_id_text}'"
            )
        logger.info(f"   ID item Régie: {regie_item_id}")
        
        # Récupérer les infos de la régie depuis le cache
        regie_info = get_regie_info_from_cache(regie_name)
        if not regie_info:
            raise HTTPException(
                status_code=404,
                detail=f"Régie '{regie_name}' non trouvée dans le cache"
            )
        
        regie_board_id = regie_info['board_id']
        logger.info(f"   Board Régie: {regie_info['board_name']} (ID: {regie_board_id})")
        logger.info(f"✓ ÉTAPE 2 - Infos de liaison récupérées")
        
        # ÉTAPE 3: Récupérer les 3 colonnes sources du tableau Install
        logger.info(f"→ ÉTAPE 3 - Récupération des 3 colonnes sources")
        
        source_column_ids = [
            config_install_regie['column_mapping']['statut']['install_id'],
            config_install_regie['column_mapping']['surface_comble']['install_id'],
            config_install_regie['column_mapping']['type_isolant']['install_id']
        ]
        
        install_columns_data = get_all_column_values_for_item(apiKey, install_item_id, source_column_ids)
        
        logger.info(f"   Colonnes récupérées:")
        for col_id, col_data in install_columns_data['columns'].items():
            logger.info(f"      {col_id}: {col_data.get('text', '(vide)')}")
        
        logger.info(f"✓ ÉTAPE 3 - Colonnes sources récupérées")
        
        # ÉTAPE 4: Préparer et mettre à jour les colonnes dans le tableau Régie
        logger.info(f"→ ÉTAPE 4 - Mise à jour du tableau Régie")
        
        columns_to_update = {}
        status_columns = {}  # Pour les colonnes status (traitement spécial)
        transfer_summary = []
        
        for mapping_key, mapping_data in config_install_regie['column_mapping'].items():
            install_col_id = mapping_data['install_id']
            regie_col_key = mapping_data['regie_key']
            
            # Récupérer l'ID de la colonne cible depuis le cache
            regie_col_info = regie_info['columns'].get(regie_col_key)
            if not regie_col_info:
                logger.warning(f"   ⚠️ Colonne '{regie_col_key}' non trouvée dans le cache pour cette régie")
                continue
            
            regie_col_id = regie_col_info['id']
            regie_col_type = regie_col_info['type']
            
            # Récupérer la valeur source
            source_col = install_columns_data['columns'].get(install_col_id)
            if not source_col:
                logger.warning(f"   ⚠️ Colonne source '{install_col_id}' non trouvée")
                continue
            
            source_value = source_col.get('value')
            source_text = source_col.get('text')
            source_type = source_col.get('type')
            
            # Formater la valeur selon le type
            formatted_value = format_column_value_for_update(source_type, source_value, source_text)
            
            if formatted_value is not None:
                # Si c'est un status, utiliser le texte
                if isinstance(formatted_value, dict) and formatted_value.get("use_text"):
                    status_columns[regie_col_id] = formatted_value["text"]
                    transfer_summary.append({
                        'source': mapping_data['install_title'],
                        'target': regie_col_key,
                        'value': source_text
                    })
                    logger.info(f"   ✓ {mapping_data['install_title']} → {regie_col_key}: '{source_text}' (status)")
                else:
                    columns_to_update[regie_col_id] = formatted_value
                    transfer_summary.append({
                        'source': mapping_data['install_title'],
                        'target': regie_col_key,
                        'value': source_text
                    })
                    logger.info(f"   ✓ {mapping_data['install_title']} → {regie_col_key}: '{source_text}'")
        
        # Vérifier que l'item Régie existe avant la mise à jour
        if not check_item_exists(apiKey, regie_item_id):
            error_msg = f"⚠️ ERREUR AUTO-LINK: L'item Régie ID {regie_item_id} n'existe pas dans le tableau {regie_info['board_name']} (ID: {regie_board_id}). Veuillez vérifier l'ID de liaison."
            logger.error(f"   ✗ {error_msg}")
            
            # Ajouter un commentaire dans le tableau Install
            try:
                add_update_to_item(apiKey, install_item_id, error_msg)
                logger.info(f"   📝 Commentaire ajouté dans l'item Install")
            except Exception as e:
                logger.error(f"   ✗ Erreur ajout commentaire: {e}")
            
            # Mettre le status à "erreur" ou similaire (optionnel)
            try:
                update_status_column(
                    apiKey,
                    install_item_id,
                    config_install_regie['install_board_id'],
                    "color_mkxv17ya",
                    "Erreur"
                )
                logger.info(f"   ✓ Status Install mis à 'Erreur'")
            except Exception as e:
                logger.error(f"   ✗ Erreur mise à jour status: {e}")
            
            raise HTTPException(
                status_code=404,
                detail=f"Item Régie {regie_item_id} non trouvé dans le tableau {regie_info['board_name']}"
            )
        
        # Mise à jour des colonnes normales (en batch)
        if columns_to_update:
            update_result = update_item_columns(
                apiKey,
                regie_item_id,
                regie_board_id,
                columns_to_update
            )
            logger.info(f"   ✓ Colonnes normales mises à jour")
        
        # Mise à jour des colonnes status (une par une, par texte)
        for status_col_id, status_text in status_columns.items():
            try:
                update_status_column(
                    apiKey,
                    regie_item_id,
                    regie_board_id,
                    status_col_id,
                    status_text
                )
                logger.info(f"   ✓ Status mis à jour: {status_col_id} = '{status_text}'")
            except Exception as e:
                logger.error(f"   ✗ Erreur status {status_col_id}: {e}")
        
        logger.info(f"✓ ÉTAPE 4 - Tableau Régie mis à jour")
        
        # ÉTAPE 5: Mettre à jour le status dans le tableau Install à "no action"
        logger.info(f"→ ÉTAPE 5 - Mise à jour status Install à 'no action'")
        
        try:
            update_status_column(
                apiKey,
                install_item_id,
                config_install_regie['install_board_id'],
                "color_mkxv17ya",
                "no action"
            )
            logger.info(f"   ✓ Status Install mis à jour: 'no action'")
        except Exception as e:
            logger.error(f"   ✗ Erreur mise à jour status Install: {e}")
        
        logger.info(f"✓ ÉTAPE 5 - Status Install mis à jour")
        
        logger.info("=" * 80)
        logger.info("INSTALL-TO-RÉGIE RÉUSSI!")
        logger.info("=" * 80)
        
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "message": "Synchronisation Install → Régie réussie",
                "results": {
                    "install_item_id": install_item_id,
                    "regie_name": regie_name,
                    "regie_board_id": regie_board_id,
                    "regie_item_id": regie_item_id,
                    "columns_updated": len(transfer_summary)
                },
                "transfer_details": transfer_summary,
                "timestamp": datetime.utcnow().isoformat()
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"ERREUR Install-to-Régie: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }
        )




# ========================================================================================================================================================
# CADASTRE CE3X - API FASTAPI
# ========================================================================================================================================================





# -*- coding: utf-8 -*-
"""
API FastAPI pour l'intégration Monday.com ↔ Analyse Cadastrale CE3X.

Reçoit un webhook Monday.com, récupère le numéro cadastral,
lance l'analyse et poste un commentaire avec les résultats.

Lancement : uvicorn app:app --reload --port 8000
"""

import logging
import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import requests
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

# Ajouter le module cadastre au path
sys.path.insert(0, str(Path(__file__).parent / "cadastre"))
from analyse_ce3x import AnalyseurCE3X, ResultatAnalyse, sauvegarder_json

# ============================================================================
# CONFIGURATION
# ============================================================================

MONDAY_API_URL = "https://api.monday.com/v2"
apiKey = "eyJhbGciOiJIUzI1NiJ9.eyJ0aWQiOjUyNTUxMDkxOCwiYWFpIjoxMSwidWlkIjo3NjM3MTkxNiwiaWFkIjoiMjAyNS0wNi0xMlQxMjowMjowNi4wMDBaIiwicGVyIjoibWU6d3JpdGUiLCJhY3RpZCI6MTQ5ODgzMDQsInJnbiI6InVzZTEifQ.g8M5fmXYZ3eNUQWiPpnKmPHf1K0wrwdqi2HJFFl1P0Q"
COLUMN_REF_CADASTRALE = "chiffres_mkmf1x55"
DOSSIER_RESULTATS = "cadastre/resultats"

# ============================================================================
# LOGGING
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("cex_app")

# ============================================================================
# APP FASTAPI
# ============================================================================



# ============================================================================
# FONCTIONS MONDAY.COM
# ============================================================================

def get_cadastral_value_for_item(
    api_token: str, item_id: int, column_id: str
) -> Optional[Dict[str, Any]]:
    """
    Récupère la valeur brute (JSON string) et le texte d'une colonne
    pour un item donné.
    """
    query = """
    query ($item_id: [ID!], $column_id: [String!]) {
      items (ids: $item_id) {
        id
        column_values (ids: $column_id) {
          id
          text
          value
          type
        }
      }
    }
    """
    variables = {"item_id": [item_id], "column_id": [column_id]}
    headers = {"Authorization": api_token, "Content-Type": "application/json"}

    resp = requests.post(
        MONDAY_API_URL,
        json={"query": query, "variables": variables},
        headers=headers,
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    if "errors" in data:
        raise RuntimeError(data["errors"])

    items = data["data"]["items"]
    if not items:
        return None

    cols = items[0]["column_values"]
    if not cols:
        return None

    col = cols[0]
    return {
        "id": col["id"],
        "type": col["type"],
        "text": col["text"],
        "value": col["value"],
    }


def poster_commentaire_monday(item_id: int, body: str) -> Optional[str]:
    """
    Poste un commentaire (update) sur un item Monday.com.
    Retourne l'ID de l'update créé, ou None en cas d'erreur.
    """
    # Échapper les caractères spéciaux pour GraphQL
    body_escaped = body.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")

    query = f"""
    mutation {{
      create_update(
        item_id: {item_id}
        body: "{body_escaped}"
      ) {{
        id
      }}
    }}
    """
    headers = {"Authorization": apiKey, "Content-Type": "application/json"}

    try:
        resp = requests.post(
            MONDAY_API_URL,
            json={"query": query},
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        if "errors" in data:
            logger.error(f"Erreur GraphQL Monday: {data['errors']}")
            return None

        update_id = data.get("data", {}).get("create_update", {}).get("id")
        if update_id:
            logger.info(f"Commentaire posté sur item {item_id}: update_id={update_id}")
        return update_id

    except Exception as e:
        logger.error(f"Erreur post commentaire Monday item {item_id}: {e}")
        return None


def _ligne(label: str, valeur: str, indent: bool = False) -> str:
    """Génère une ligne de tableau HTML label/valeur."""
    prefix = "&nbsp;&nbsp;- " if indent else ""
    return f'<tr><td>{prefix}{label}</td><td style="text-align:right">{valeur}</td></tr>'


def formater_commentaire_monday(r: ResultatAnalyse) -> str:
    """
    Formate les résultats de l'analyse cadastrale en HTML pour Monday.com.
    Style : tableaux bordés avec sections titrées, orientations indentées.
    """
    env = r.enveloppe
    type_str = r.type_batiment.value if hasattr(r.type_batiment, 'value') else r.type_batiment
    T = '<table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;width:100%;margin-bottom:12px">'

    html = ''

    # ── INFORMATIONS GÉNÉRALES ──
    hauteur_txt = f'{r.hauteur_etage} m'
    if r.hauteur_max_gml:
        hauteur_txt += f' (max GML: {r.hauteur_max_gml}m)'

    html += T
    html += '<tr><td colspan="2" style="background:#e0e0e0"><b>INFORMATIONS GÉNÉRALES</b></td></tr>'
    html += _ligne('Référence cadastrale', r.referencia)
    html += _ligne('Type de bâtiment', type_str)
    if r.adresse:
        html += _ligne('Adresse', r.adresse)
    if r.annee_construction:
        html += _ligne('Année de construction', str(r.annee_construction))
    html += _ligne('Nombre d\'étages', str(r.nombre_etages))
    html += _ligne('Hauteur d\'étage', hauteur_txt)
    if r.utm_x and r.utm_y:
        html += _ligne('UTM', f'{r.utm_zone} X : {r.utm_x:.0f} m, Y : {r.utm_y:.0f} m')
    if r.coord_wgs84_lat and r.coord_wgs84_lon:
        html += _ligne('WGS84', f'Lon: {r.coord_wgs84_lon:.6f}, Lat: {r.coord_wgs84_lat:.6f}')
    html += '</table>'

    # ── SURFACES ──
    html += T
    html += '<tr><td colspan="2" style="background:#e0e0e0"><b>SURFACES</b></td></tr>'
    html += _ligne('Surface habitable (VIVIENDA)', f'{r.surface_utile} m²')
    html += _ligne('Surface construite totale', f'{r.surface_totale} m²')
    html += '</table>'

    # ── DÉTAIL PAR UNITÉ ──
    if r.inmuebles:
        html += T
        html += '<tr><td colspan="2" style="background:#e0e0e0"><b>DÉTAIL PAR UNITÉ</b></td></tr>'
        for idx, inm in enumerate(r.inmuebles, 1):
            html += f'<tr><td colspan="2"><b>[{idx}] {inm.referencia_20}</b></td></tr>'
            for c in inm.construcciones:
                est_viv = 'VIVIENDA' in c.uso.upper()
                icone = '&#10003;' if est_viv else '&#10007;'
                planta = f' (Planta {c.planta})' if c.planta != '00' else ''
                html += f'<tr><td>&nbsp;&nbsp;[{icone}] {c.uso}{planta}</td><td style="text-align:right">{c.superficie_m2} m²</td></tr>'
        html += '</table>'

    # ── ENVELOPPE THERMIQUE CE3X ──
    html += T
    html += '<tr><td colspan="2" style="background:#e0e0e0"><b>ENVELOPPE THERMIQUE CE3X</b></td></tr>'
    html += _ligne('Murs extérieurs', f'{env.murs_exterieurs:.1f} m²')
    html += _ligne('Nord', f'{env.murs_exterieurs_nord:.1f} m²', indent=True)
    html += _ligne('Sud', f'{env.murs_exterieurs_sud:.1f} m²', indent=True)
    html += _ligne('Est', f'{env.murs_exterieurs_est:.1f} m²', indent=True)
    html += _ligne('Ouest', f'{env.murs_exterieurs_ouest:.1f} m²', indent=True)
    html += _ligne('Murs mitoyens avec LNC', f'{env.murs_mitoyens_lnc:.1f} m²')
    html += _ligne('Murs mitoyens chauffés', f'{env.murs_mitoyens_chauffes:.1f} m² (adiabatique)')
    html += _ligne('Plancher sur terre-plein', f'{env.plancher_terre_plein:.0f} m²')
    html += _ligne('Plancher sur LNC', f'{env.plancher_sur_lnc:.0f} m²')
    html += _ligne('Plancher sur local chauffé', f'{env.plancher_sur_local_chauffe:.0f} m² (adiabatique)')
    html += _ligne('Plafond sous local chauffé', f'{env.plafond_sous_local_chauffe:.0f} m² (adiabatique)')
    html += _ligne('Toiture', f'{env.toiture:.0f} m²')
    # Séparateur visuel
    html += '<tr><td colspan="2">&nbsp;</td></tr>'
    html += _ligne('Huecos (fenêtres)', f'{env.huecos_total:.1f} m² (ratio {env.ratio_huecos_murs:.0%})')
    html += _ligne('Nord', f'{env.huecos_nord:.1f} m²', indent=True)
    html += _ligne('Sud', f'{env.huecos_sud:.1f} m²', indent=True)
    html += _ligne('Est', f'{env.huecos_est:.1f} m²', indent=True)
    html += _ligne('Ouest', f'{env.huecos_ouest:.1f} m²', indent=True)
    html += _ligne('Vitrage estimé', env.tipo_vidrio)
    html += _ligne('Menuiserie estimée', env.tipo_marco)
    html += '</table>'

    # ── PHOTOS ──
    if r.url_photo_facade or (r.utm_x and r.utm_y):
        html += T
        html += '<tr><td colspan="2" style="background:#e0e0e0"><b>PHOTOS</b></td></tr>'
        images = ''
        if r.url_photo_facade:
            images += f'<img src="{r.url_photo_facade}" alt="Facade" width="400"><br>'
        if r.utm_x and r.utm_y:
            marge = 80
            bbox = f"{r.utm_x - marge},{r.utm_y - marge},{r.utm_x + marge},{r.utm_y + marge}"
            epsg = f"258{r.utm_zone}"
            url_carte = (
                f"https://ovc.catastro.meh.es/Cartografia/WMS/ServidorWMS.aspx"
                f"?SERVICE=WMS&VERSION=1.1.1&REQUEST=GetMap&LAYERS=Catastro"
                f"&SRS=EPSG:{epsg}&BBOX={bbox}&WIDTH=500&HEIGHT=500&FORMAT=image/png"
            )
            images += f'<img src="{url_carte}" alt="Localisation" width="400">'
        html += f'<tr><td colspan="2" style="text-align:center">{images}</td></tr>'
        html += '</table>'

    return html


# ============================================================================
# ENDPOINT WEBHOOK
# ============================================================================

RE_REF_CADASTRALE = re.compile(r"^[A-Za-z0-9]{14}([A-Za-z0-9]{6})?$")


@app.post("/analyse_cadastre")
async def analyse_cadastre(request: Request):
    """
    Endpoint webhook Monday.com :
    1. Challenge handling (vérification webhook)
    2. Récupère le numéro cadastral depuis la colonne Monday
    3. Lance l'analyse cadastrale
    4. Poste le résumé en commentaire sur l'item
    """
    data = await request.json()

    # --- Challenge Monday.com ---
    if "challenge" in data:
        return JSONResponse({"challenge": data["challenge"]})

    # --- Extraction de l'item ID ---
    event = data.get("event", data)
    item_id = event.get("pulseId") or event.get("itemId")

    if not item_id:
        logger.warning(f"Webhook sans pulseId/itemId: {data}")
        return JSONResponse({"error": "pulseId manquant"}, status_code=400)

    item_id = int(item_id)
    logger.info(f"Webhook recu pour item {item_id}")

    # --- Récupération de la référence cadastrale ---
    try:
        col_data = get_cadastral_value_for_item(
            apiKey, item_id, COLUMN_REF_CADASTRALE
        )
    except Exception as e:
        logger.error(f"Erreur API Monday item {item_id}: {e}")
        return JSONResponse({"error": f"Erreur API Monday: {e}"}, status_code=502)

    if not col_data or not col_data.get("text"):
        logger.warning(f"Colonne {COLUMN_REF_CADASTRALE} vide pour item {item_id}")
        return JSONResponse({"status": "skip", "reason": "ref cadastrale vide"})

    ref_cadastrale = col_data["text"].strip().upper()
    logger.info(f"Reference cadastrale: {ref_cadastrale}")

    # --- Validation ---
    if not RE_REF_CADASTRALE.match(ref_cadastrale):
        msg = f"Reference cadastrale invalide: {ref_cadastrale}"
        logger.warning(msg)
        poster_commentaire_monday(item_id, f"Erreur : {msg}")
        return JSONResponse({"error": msg}, status_code=400)

    # --- Analyse cadastrale ---
    try:
        analyseur = AnalyseurCE3X(ref_cadastrale)
        resultat = analyseur.analyser()
    except Exception as e:
        msg = f"Erreur analyse cadastrale {ref_cadastrale}: {e}"
        logger.error(msg)
        poster_commentaire_monday(item_id, f"Erreur analyse : {e}")
        return JSONResponse({"error": msg}, status_code=500)

    # --- Sauvegarde JSON ---
    try:
        dossier = Path(DOSSIER_RESULTATS)
        dossier = dossier / resultat.referencia
        dossier.mkdir(parents=True, exist_ok=True)
        sauvegarder_json(resultat, str(dossier / "resultat_ce3x.json"))
    except Exception as e:
        logger.warning(f"Erreur sauvegarde JSON: {e}")

    # --- Post commentaire Monday ---
    commentaire = formater_commentaire_monday(resultat)
    poster_commentaire_monday(item_id, commentaire)

    # --- Nettoyage du dossier résultats ---
    try:
        if dossier.exists():
            shutil.rmtree(dossier)
            logger.info(f"Dossier supprimé: {dossier}")
    except Exception as e:
        logger.warning(f"Erreur suppression dossier {dossier}: {e}")

    return JSONResponse({
        "status": "ok",
        "referencia": ref_cadastrale,
        "surface_utile": resultat.surface_utile,
    })


# ============================================================================
# ENDPOINT: Generate TagList JSON
# ============================================================================

def extract_taglist_value(col_data: dict, col_type: str) -> str:
    """Extrait la valeur d'une colonne Monday.com selon son type pour le TagList."""
    if not col_data:
        return ""

    text = col_data.get('text', '') or ''
    value_raw = col_data.get('value', '')

    if col_type == "phone":
        if value_raw:
            try:
                parsed = json.loads(value_raw) if isinstance(value_raw, str) else value_raw
                return parsed.get('phone', '') or text
            except (json.JSONDecodeError, AttributeError):
                return text
        return text

    elif col_type == "email":
        if value_raw:
            try:
                parsed = json.loads(value_raw) if isinstance(value_raw, str) else value_raw
                return parsed.get('email', '') or text
            except (json.JSONDecodeError, AttributeError):
                return text
        return text

    elif col_type == "date":
        if value_raw:
            try:
                parsed = json.loads(value_raw) if isinstance(value_raw, str) else value_raw
                date_str = parsed.get('date', '')
                if date_str:
                    dt = datetime.strptime(date_str, "%Y-%m-%d")
                    return dt.strftime("%d/%m/%Y")
            except (json.JSONDecodeError, AttributeError, ValueError):
                pass
        return text

    elif col_type == "status":
        return text

    else:
        return text


@app.post("/generate-taglist")
async def generate_taglist(request: Dict[Any, Any]):
    """
    Endpoint webhook - Génération du JSON TagList

    1. Reçoit le webhook avec l'ID de l'item Install
    2. Récupère les colonnes configurées dans config_taglist.json
    3. Construit le JSON TagList
    4. Retourne le JSON (destination à définir)
    """
    try:
        logger.info("=" * 80)
        logger.info("Webhook Generate-TagList reçu")
        logger.info(f"Payload: {json.dumps(request, indent=2)}")

        # Gestion du challenge Monday.com
        if 'challenge' in request:
            logger.info(f"Challenge reçu: {request['challenge']}")
            return {"challenge": request['challenge']}

        # ÉTAPE 1: Extraire l'ID de l'item
        event = request.get('event', {})
        item_id = int(event.get('pulseId'))
        logger.info(f"✓ ÉTAPE 1 - ID item Install: {item_id}")

        # ÉTAPE 2: Récupérer les colonnes depuis Monday.com
        logger.info("→ ÉTAPE 2 - Récupération des colonnes")

        mapping = config_taglist['column_mapping']
        column_ids = list(set(
            m['column_id'] for m in mapping.values() if m['column_id'] != 'name'
        ))
        logger.info(f"  Colonnes à récupérer: {column_ids}")

        item_data = get_all_column_values_for_item(apiKey, item_id, column_ids)

        if not item_data or not item_data.get('columns'):
            logger.error(f"  ✗ Item {item_id} non trouvé ou colonnes manquantes")
            raise HTTPException(
                status_code=404,
                detail=f"Item {item_id} non trouvé ou colonnes manquantes"
            )

        logger.info(f"  ✓ Données récupérées - Item: {item_data['name']}")
        for col_id, col_data in item_data['columns'].items():
            logger.info(f"    - {col_id}: text='{col_data.get('text')}', type={col_data.get('type')}")

        # ÉTAPE 3: Extraire les données structurées de la colonne location
        logger.info("→ ÉTAPE 3 - Extraction des données location")

        location_data = {}
        location_col_id = mapping.get('adresse', {}).get('column_id', '')
        lieu_col = item_data['columns'].get(location_col_id) if location_col_id else None
        if lieu_col and lieu_col.get('value'):
            try:
                location_data = json.loads(lieu_col['value']) if isinstance(lieu_col['value'], str) else lieu_col['value']
            except (json.JSONDecodeError, TypeError):
                pass

        ville = location_data.get('city', {}).get('long_name', '') if location_data else ''
        pays = location_data.get('country', {}).get('long_name', '') if location_data else ''
        lat = location_data.get('lat', '')
        lng = location_data.get('lng', '')
        geo_from_location = f"{lat},{lng}" if lat and lng else ''

        logger.info(f"  ville (location): '{ville}'")
        logger.info(f"  pays (location): '{pays}'")
        logger.info(f"  geo (location): '{geo_from_location}'")

        # ÉTAPE 4: Construire le TagList
        logger.info("→ ÉTAPE 4 - Construction du TagList")

        taglist = {}

        for field_name, field_config in mapping.items():
            col_id = field_config['column_id']
            col_type = field_config['type']

            if col_id == 'name':
                taglist[field_name] = item_data.get('name', '') or ''
            else:
                col_data = item_data['columns'].get(col_id)
                taglist[field_name] = extract_taglist_value(col_data, col_type)

            logger.info(f"  {field_name}: '{taglist[field_name]}'")

        # Remplir ville et pays depuis location
        taglist['ville'] = ville
        taglist['pays'] = pays
        logger.info(f"  ville: '{ville}' (depuis location)")
        logger.info(f"  pays: '{pays}' (depuis location)")

        # geoPosition: priorité à la colonne dédiée, sinon depuis location
        if not taglist.get('geoPosition'):
            taglist['geoPosition'] = geo_from_location
            logger.info(f"  geoPosition: '{geo_from_location}' (depuis location)")

        # codePostal: fallback espace si vide
        if not taglist.get('codePostal'):
            taglist['codePostal'] = ' '
            logger.info(f"  codePostal: ' ' (fallback)")

        # Ajouter les valeurs par défaut pour les champs non encore remplis
        defaults = config_taglist.get('defaults', {})
        for field_name, default_value in defaults.items():
            if field_name not in taglist:
                # Remplacer __PULSE_ID__ par l'ID réel de l'item
                if default_value == '__PULSE_ID__':
                    default_value = str(item_id)
                taglist[field_name] = default_value
                logger.info(f"  {field_name}: '{default_value}' (défaut)")

        logger.info("=" * 80)
        logger.info(f"✓ TagList généré: {json.dumps({'TagList': taglist}, indent=2, ensure_ascii=False)}")

        # ÉTAPE 5: Envoi vers l'API CAEX
        caex_url = config_taglist.get('caex_api_url', 'https://api.caex.tech/api/prospects')
        payload = {"TagList": json.dumps(taglist, ensure_ascii=False)}

        logger.info(f"→ ÉTAPE 5 - Envoi vers {caex_url}")
        caex_resp = requests.post(
            caex_url,
            json=payload,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
                "Origin": "https://autolink-monday.onrender.com",
                "Referer": "https://api.caex.tech/"
            },
            timeout=60
        )

        logger.info(f"  Status CAEX: {caex_resp.status_code}")
        logger.info(f"  Réponse CAEX: {caex_resp.text[:500]}")

        return JSONResponse({
            "status": "ok",
            "taglist": taglist,
            "caex_status": caex_resp.status_code,
            "caex_response": caex_resp.json() if caex_resp.headers.get('content-type', '').startswith('application/json') else caex_resp.text
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"✗ Erreur generate-taglist: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erreur génération TagList: {str(e)}")
