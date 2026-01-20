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
    clear_item_columns
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

# Extraction dynamique des IDs de colonnes du tableau principal depuis le mapping
principal_column_ids = [mapping['principal']['id'] for mapping in column_mapping]
logger.info(f"Colonnes à récupérer du tableau principal: {len(principal_column_ids)} colonnes")
logger.info(f"IDs: {principal_column_ids}")


@app.get("/")
async def root():
    """Endpoint de base pour vérifier que l'API fonctionne"""
    return {
        "message": "Monday.com Auto-Link System",
        "status": "running",
        "timestamp": datetime.utcnow().isoformat(),
        "config": {
            "admin_board_id": config["admin_board_id"],
            "excluded_columns": config["excluded_columns"]
        }
    }


@app.post("/auto-link")
async def auto_link(request: Dict[Any, Any]):
    """
    Endpoint webhook - TEST des 3 premières étapes
    
    1. Reçoit le webhook avec l'ID de l'item du tableau principal
    2. Récupère la valeur de la colonne ID_admin de cet item
    3. Cherche l'item correspondant dans le tableau admin
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
        
        # Afficher les colonnes avec leurs valeurs
        logger.info("  DÉTAIL DES COLONNES:")
        for col_id, col_data in item_data['columns'].items():
            # Trouver le titre dans le mapping
            col_title = next((m['principal']['title'] for m in column_mapping if m['principal']['id'] == col_id), col_id)
            text_value = col_data['text'] if col_data['text'] else '(vide)'
            logger.info(f"    - {col_title} ({col_id}): {text_value}")
        
        logger.info("=" * 80)
        logger.info("TEST RÉUSSI - Les 4 étapes fonctionnent correctement!")
        logger.info("=" * 80)
        
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "message": "TEST RÉUSSI - 4 étapes validées",
                "test_results": {
                    "etape_1": {
                        "description": "Réception webhook",
                        "status": "✓ OK",
                        "id_principal": id_
                    },
                    "etape_2": {
                        "description": "Récupération ID_admin",
                        "status": "✓ OK",
                        "id_admin_value": id_admin_value,
                        "column_data": id_admin_data
                    },
                    "etape_3": {
                        "description": "Recherche item admin",
                        "status": "✓ OK",
                        "id_admin_trouve": id__,
                        "nombre_items_trouves": len(admin_item_ids),
                        "tous_les_ids": admin_item_ids
                    },
                    "etape_4": {
                        "description": "Récupération données tableau principal",
                        "status": "✓ OK",
                        "item_name": item_data['name'],
                        "colonnes_recuperees": len(item_data['columns']),
                        "colonnes_attendues": len(principal_column_ids)
                    }
                },
                "item_data": {
                    "id": item_data['id'],
                    "name": item_data['name'],
                    "colonnes": {
                        col_id: {
                            "titre": next((m['principal']['title'] for m in column_mapping if m['principal']['id'] == col_id), col_id),
                            "type": col_data['type'],
                            "text": col_data['text'],
                            "value": col_data['value']
                        }
                        for col_id, col_data in item_data['columns'].items()
                    }
                },
                "configuration": {
                    "main_board_id": config['main_board_id'],
                    "admin_board_id": config['admin_board_id'],
                    "main_id_column": config['main_id_column'],
                    "admin_id_column": config['admin_id_column'],
                    "colonnes_a_recuperer": len(principal_column_ids)
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
