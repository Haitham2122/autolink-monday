from typing import Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from datetime import datetime
import json
import logging

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
            "install-to-regie": "/install-to-regie (Install → Régie)"
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
    import re
    return re.sub(r'\s+', ' ', name.lower().strip())


def get_regie_info_from_cache(regie_name: str) -> dict:
    """
    Récupère les infos d'une régie depuis le cache.
    
    Args:
        regie_name: Nom de la régie (valeur du status)
    
    Returns:
        Infos de la régie ou None si non trouvée
    """
    cache_key = normalize_regie_name(regie_name)
    
    # Recherche exacte
    if cache_key in regies_cache:
        return regies_cache[cache_key]
    
    # Recherche partielle
    for key, data in regies_cache.items():
        if cache_key in key or key in cache_key:
            return data
    
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
            error_msg = f"⚠️ ERREUR AUTO-LINK: L'ID de l'item Régie est VIDE. La colonne 'ID item Régie' doit être renseignée pour synchroniser vers le tableau {regie_name}."
            logger.error(f"   ✗ ID item Régie VIDE - Colonne {config_install_regie['regie_item_id_column']}")
            logger.error(f"   Données colonne: {regie_item_id_col}")
            
            # Ajouter un commentaire dans l'item Install
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
            error_msg = f"⚠️ ERREUR AUTO-LINK: L'ID de l'item Régie '{regie_item_id_text}' n'est pas un nombre valide."
            logger.error(f"   ✗ ID item Régie invalide: '{regie_item_id_text}' n'est pas un nombre")
            
            # Ajouter un commentaire dans l'item Install
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
