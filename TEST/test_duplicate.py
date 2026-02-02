"""
Test de duplication d'un tableau Monday.com
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

# Configuration du test
SOURCE_BOARD_ID = 9147989500  # Régie JADEL V2
NEW_BOARD_NAME = "Régie HAITHAM TEST"
WORKSPACE_ID = 10987132


def duplicate_board(board_id: int, new_name: str, workspace_id: int = None) -> dict:
    """Duplique un tableau avec un nouveau nom"""
    query = """
    mutation ($board_id: ID!, $new_name: String!, $workspace_id: ID) {
        duplicate_board (
            board_id: $board_id,
            duplicate_type: duplicate_board_with_structure,
            board_name: $new_name,
            workspace_id: $workspace_id
        ) {
            board {
                id
                name
            }
        }
    }
    """
    
    variables = {
        "board_id": board_id,
        "new_name": new_name
    }
    
    if workspace_id:
        variables["workspace_id"] = workspace_id
    
    response = requests.post(API_URL, headers=HEADERS, json={"query": query, "variables": variables})
    response.raise_for_status()
    result = response.json()
    
    print(f"Réponse API: {json.dumps(result, indent=2)}")
    
    if "errors" in result:
        raise Exception(f"Erreur API: {result['errors']}")
    
    return result["data"]["duplicate_board"]["board"]


if __name__ == "__main__":
    print("=" * 60)
    print("TEST DE DUPLICATION DE TABLEAU")
    print("=" * 60)
    print(f"Source: {SOURCE_BOARD_ID} (Régie JADEL V2)")
    print(f"Nouveau nom: {NEW_BOARD_NAME}")
    print(f"Workspace: {WORKSPACE_ID}")
    print("=" * 60)
    
    try:
        new_board = duplicate_board(SOURCE_BOARD_ID, NEW_BOARD_NAME, WORKSPACE_ID)
        print(f"\n✓ SUCCÈS!")
        print(f"  Nouveau tableau créé:")
        print(f"  - ID: {new_board['id']}")
        print(f"  - Nom: {new_board['name']}")
    except Exception as e:
        print(f"\n✗ ERREUR: {e}")
