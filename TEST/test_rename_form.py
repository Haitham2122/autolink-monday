"""
Renommer un formulaire d'un tableau Monday.com
"""
import requests
import json

API_KEY = "eyJhbGciOiJIUzI1NiJ9.eyJ0aWQiOjUyNTUxMDkxOCwiYWFpIjoxMSwidWlkIjo3NjM3MTkxNiwiaWFkIjoiMjAyNS0wNi0xMlQxMjowMjowNi4wMDBaIiwicGVyIjoibWU6d3JpdGUiLCJhY3RpZCI6MTQ5ODgzMDQsInJnbiI6InVzZTEifQ.g8M5fmXYZ3eNUQWiPpnKmPHf1K0wrwdqi2HJFFl1P0Q"
API_URL = "https://api.monday.com/v2"
HEADERS = {
    "Authorization": API_KEY,
    "Content-Type": "application/json",
    "API-Version": "2023-07"
}

# Configuration
BOARD_ID = 18398227869  # Régie HAITHAM TEST
FORM_VIEW_ID = 234031993  # Formulaire
NEW_FORM_NAME = "Formulaire HAITHAM TEST"


def rename_view_method1(board_id: int, view_id: int, new_name: str):
    """Méthode 1: update_board_view (si supportée)"""
    query = """
    mutation ($board_id: ID!, $view_id: ID!, $new_name: String!) {
        update_board_view (
            board_id: $board_id,
            view_id: $view_id,
            attribute: name,
            new_value: $new_name
        )
    }
    """
    
    variables = {
        "board_id": str(board_id),
        "view_id": str(view_id),
        "new_name": new_name
    }
    
    response = requests.post(API_URL, headers=HEADERS, json={"query": query, "variables": variables})
    return response.json()


def rename_view_method2(view_id: int, new_name: str):
    """Méthode 2: mutation directe sur la vue"""
    query = """
    mutation ($view_id: ID!, $view_name: String!) {
        update_view (
            view_id: $view_id,
            view_name: $view_name
        ) {
            id
            name
        }
    }
    """
    
    variables = {
        "view_id": str(view_id),
        "view_name": new_name
    }
    
    response = requests.post(API_URL, headers=HEADERS, json={"query": query, "variables": variables})
    return response.json()


def rename_view_method3(board_id: int, view_id: int, new_name: str):
    """Méthode 3: via change_column_value style"""
    query = """
    mutation {
        change_board_view_name (
            board_id: %s,
            view_id: %s,
            name: "%s"
        ) {
            id
            name
        }
    }
    """ % (board_id, view_id, new_name)
    
    response = requests.post(API_URL, headers=HEADERS, json={"query": query})
    return response.json()


if __name__ == "__main__":
    print("=" * 60)
    print("TEST DE RENOMMAGE DE FORMULAIRE")
    print("=" * 60)
    print(f"Board ID: {BOARD_ID}")
    print(f"View ID: {FORM_VIEW_ID}")
    print(f"Nouveau nom: {NEW_FORM_NAME}")
    print("=" * 60)
    
    # Test méthode 1
    print("\n[Méthode 1] update_board_view...")
    result1 = rename_view_method1(BOARD_ID, FORM_VIEW_ID, NEW_FORM_NAME)
    print(f"Résultat: {json.dumps(result1, indent=2)}")
    
    if "errors" in result1:
        # Test méthode 2
        print("\n[Méthode 2] update_view...")
        result2 = rename_view_method2(FORM_VIEW_ID, NEW_FORM_NAME)
        print(f"Résultat: {json.dumps(result2, indent=2)}")
        
        if "errors" in result2:
            # Test méthode 3
            print("\n[Méthode 3] change_board_view_name...")
            result3 = rename_view_method3(BOARD_ID, FORM_VIEW_ID, NEW_FORM_NAME)
            print(f"Résultat: {json.dumps(result3, indent=2)}")
    
    print("\n" + "=" * 60)
    print("FIN DES TESTS")
    print("=" * 60)
