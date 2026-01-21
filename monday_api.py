"""
Module pour interagir avec l'API Monday.com
"""
import requests
from typing import Dict, List, Any, Optional

MONDAY_API_URL = "https://api.monday.com/v2"


def get_column_value_for_item(api_token: str,
                              item_id: int,
                              column_id: str) -> Optional[Dict[str, Any]]:
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

    variables = {
        "item_id": [item_id],
        "column_id": [column_id]
    }

    headers = {
        "Authorization": api_token,
        "Content-Type": "application/json"
    }

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
        return None  # item non trouvé

    cols = items[0]["column_values"]
    if not cols:
        return None  # colonne non trouvée sur cet item

    col = cols[0]
    return {
        "id": col["id"],
        "type": col["type"],
        "text": col["text"],
        "value": col["value"],
    }


def get_item_ids_by_column_value(api_token: str,
                                 board_id: int,
                                 column_id: str,
                                 value: str,
                                 limit: int = 50) -> List[int]:
    """
    Return a list of item IDs on `board_id` where `column_id` == `value`
    using items_page_by_column_values.
    """
    query = """
    query ($board_id: ID!, $column_id: String!, $value: String!, $limit: Int!) {
      items_page_by_column_values(
        board_id: $board_id
        limit: $limit
        columns: [
          {
            column_id: $column_id
            column_values: [$value]
          }
        ]
      ) {
        items {
          id
        }
      }
    }
    """

    variables = {
        "board_id": board_id,
        "column_id": column_id,
        "value": value,
        "limit": limit
    }

    headers = {
        "Authorization": api_token,
        "Content-Type": "application/json"
    }

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

    items = data["data"]["items_page_by_column_values"]["items"]
    return [int(item["id"]) for item in items]


def get_all_column_values_for_item(api_token: str,
                                   item_id: int,
                                   column_ids: List[str]) -> Dict[str, Any]:
    """
    Récupère les colonnes spécifiques d'un item.
    
    Args:
        api_token: Token d'authentification Monday.com
        item_id: ID de l'item à récupérer
        column_ids: Liste des IDs de colonnes à récupérer
    
    Retourne: {
        "id": item_id,
        "name": item_name,
        "columns": {column_id: {id, type, text, value}}
    }
    """
    query = """
    query ($item_id: [ID!], $column_ids: [String!]) {
      items (ids: $item_id) {
        id
        name
        column_values (ids: $column_ids) {
          id
          text
          value
          type
        }
      }
    }
    """

    variables = {
        "item_id": [item_id],
        "column_ids": column_ids
    }

    headers = {
        "Authorization": api_token,
        "Content-Type": "application/json"
    }

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
        return {
            "id": None,
            "name": None,
            "columns": {}
        }

    item = items[0]
    cols = item["column_values"]
    
    # Créer un dictionnaire des colonnes
    cols_by_id = {}
    for c in cols:
        cols_by_id[c["id"]] = {
            "id": c["id"],
            "type": c["type"],
            "text": c["text"],
            "value": c["value"]
        }

    return {
        "id": item["id"],
        "name": item["name"],
        "columns": cols_by_id
    }


def update_status_column(api_token: str,
                        item_id: int,
                        board_id: int,
                        column_id: str,
                        label_value: str) -> str:
    """
    Met à jour une colonne status en utilisant le label (texte) au lieu de l'index.
    Crée le label s'il n'existe pas.
    
    Args:
        api_token: Token d'authentification Monday.com
        item_id: ID de l'item
        board_id: ID du board
        column_id: ID de la colonne status
        label_value: Texte du statut (ex: "Terminé", "En cours")
    
    Returns:
        ID de l'item mis à jour
    """
    query = """
    mutation ($boardId: ID!, $itemId: ID!, $columnId: String!, $value: String, $create: Boolean) {
      change_simple_column_value(
        board_id: $boardId,
        item_id: $itemId,
        column_id: $columnId,
        value: $value,
        create_labels_if_missing: $create
      ) { id }
    }
    """
    
    variables = {
        "boardId": str(board_id),
        "itemId": str(item_id),
        "columnId": column_id,
        "value": label_value,
        "create": True
    }
    
    headers = {
        "Authorization": api_token,
        "Content-Type": "application/json"
    }
    
    resp = requests.post(
        MONDAY_API_URL,
        headers=headers,
        json={"query": query, "variables": variables},
        timeout=60
    )
    resp.raise_for_status()
    data = resp.json()
    
    if "errors" in data:
        raise RuntimeError(data["errors"])
    
    return data["data"]["change_simple_column_value"]["id"]


def format_column_value_for_update(column_type: str, raw_value: str, text_value: str = None) -> Any:
    """
    Formate la valeur d'une colonne selon son type pour Monday.com.
    
    Args:
        column_type: Type de la colonne (text, numbers, status, etc.)
        raw_value: Valeur brute (JSON string) venant de Monday.com
        text_value: Valeur texte lisible (utilisée pour les status)
    
    Returns:
        Valeur formatée prête pour change_multiple_column_values
        Pour les status: dict spécial {"use_text": True, "text": "..."}
    """
    import json
    
    # Si la valeur est None ou vide, retourner une string vide
    if raw_value is None or raw_value == '':
        return ""
    
    # Pour les types simples (text, numbers), retourner directement la valeur parsée
    if column_type in ['text', 'numbers', 'numeric']:
        try:
            # Essayer de parser le JSON pour extraire la valeur
            parsed = json.loads(raw_value)
            return parsed if isinstance(parsed, str) else str(parsed)
        except:
            return raw_value
    
    # Pour STATUS : retourner le texte au lieu de l'index !
    if column_type == 'status':
        # Si on a le text_value, l'utiliser (c'est le label visible)
        if text_value:
            return {
                "use_text": True,  # Flag pour traitement spécial
                "text": text_value  # Le label du statut
            }
        # Sinon, ignorer (on ne peut pas transférer sans le texte)
        return None
    
    # Pour les types complexes (sauf status), parser le JSON et retourner l'objet
    if column_type in ['phone', 'email', 'location', 'people', 'date', 'checkbox']:
        try:
            return json.loads(raw_value)
        except:
            return raw_value
    
    # Pour les fichiers, vider la colonne dans le tableau admin
    if column_type == 'file':
        return {"clear_all": True}
    
    # Pour les formules et autres colonnes read-only, ignorer
    # Liste complète des types non modifiables
    read_only_types = [
        'formula',           # Formules
        'item_id',          # ID de l'item
        'subtasks',         # Sous-tâches
        'mirror',           # Colonnes miroir
        'dependency',       # Dépendances
        'auto_number',      # Numérotation auto
        'creation_log',     # Log de création
        'last_updated'      # Dernière mise à jour
    ]
    
    # Vérifier aussi en lowercase car Monday peut retourner différents formats
    if column_type.lower() in read_only_types or 'formula' in column_type.lower():
        return None
    
    # Par défaut, essayer de parser le JSON
    try:
        return json.loads(raw_value)
    except:
        return raw_value


def update_item_columns(api_token: str,
                       item_id: int,
                       board_id: int,
                       column_values: Dict[str, Any]) -> Dict[str, Any]:
    """
    Met à jour plusieurs colonnes d'un item en une seule fois.
    
    Args:
        api_token: Token d'authentification Monday.com
        item_id: ID de l'item à mettre à jour
        board_id: ID du board
        column_values: Dictionnaire {column_id: valeur_formatée}
    
    Returns:
        Résultat de la mutation
    """
    import json
    
    mutation = """
    mutation ($board_id: ID!, $item_id: ID!, $column_values: JSON!) {
      change_multiple_column_values(
        board_id: $board_id
        item_id: $item_id
        column_values: $column_values
      ) {
        id
      }
    }
    """

    # Convertir le dictionnaire en JSON string pour Monday.com
    column_values_json = json.dumps(column_values)

    variables = {
        "board_id": str(board_id),
        "item_id": str(item_id),
        "column_values": column_values_json
    }

    headers = {
        "Authorization": api_token,
        "Content-Type": "application/json"
    }

    resp = requests.post(
        MONDAY_API_URL,
        json={"query": mutation, "variables": variables},
        headers=headers,
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    if "errors" in data:
        raise RuntimeError(data["errors"])

    return data["data"]["change_multiple_column_values"]


def clear_item_columns(api_token: str,
                      item_id: int,
                      board_id: int,
                      column_ids: List[str]) -> Dict[str, Any]:
    """
    Efface les valeurs de colonnes spécifiques en les mettant à vide.
    
    Args:
        api_token: Token d'authentification Monday.com
        item_id: ID de l'item
        board_id: ID du board
        column_ids: Liste des IDs de colonnes à effacer
    
    Returns:
        Résultat de la mutation
    """
    # Créer un dictionnaire avec des valeurs vides pour chaque colonne
    empty_values = {}
    for col_id in column_ids:
        empty_values[col_id] = ""
    
    return update_item_columns(api_token, item_id, board_id, empty_values)
