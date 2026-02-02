"""
Liste les formulaires d'un tableau Monday.com
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

# Nouveau tableau créé
BOARD_ID = 18398227869  # Régie HAITHAM TEST


def get_board_views(board_id: int) -> list:
    """Récupère toutes les vues d'un tableau"""
    query = """
    query ($board_id: ID!) {
        boards (ids: [$board_id]) {
            name
            views {
                id
                name
                type
            }
        }
    }
    """
    
    variables = {"board_id": board_id}
    response = requests.post(API_URL, headers=HEADERS, json={"query": query, "variables": variables})
    response.raise_for_status()
    result = response.json()
    
    if "errors" in result:
        raise Exception(f"Erreur API: {result['errors']}")
    
    boards = result.get("data", {}).get("boards", [])
    if not boards:
        return [], None
    
    return boards[0].get("views", []), boards[0].get("name")


if __name__ == "__main__":
    print("=" * 60)
    print("LISTE DES VUES/FORMULAIRES DU TABLEAU")
    print("=" * 60)
    print(f"Board ID: {BOARD_ID}")
    print("=" * 60)
    
    try:
        views, board_name = get_board_views(BOARD_ID)
        print(f"\nTableau: {board_name}")
        print(f"Nombre de vues: {len(views)}")
        print("\nDétail des vues:")
        print("-" * 60)
        
        for view in views:
            view_type = view.get('type', 'inconnu')
            icon = "📝" if view_type == "form" else "📊"
            print(f"  {icon} ID: {view['id']}")
            print(f"     Nom: {view['name']}")
            print(f"     Type: {view_type}")
            print()
        
        # Filtrer les formulaires
        forms = [v for v in views if v.get('type') == 'form']
        print("-" * 60)
        print(f"Formulaires trouvés: {len(forms)}")
        for form in forms:
            print(f"  → {form['name']} (ID: {form['id']})")
            
    except Exception as e:
        print(f"\n✗ ERREUR: {e}")
