"""
Test de recherche de la régie Euroenergy - Méthode 2
"""
import requests

API_KEY = 'eyJhbGciOiJIUzI1NiJ9.eyJ0aWQiOjUyNTUxMDkxOCwiYWFpIjoxMSwidWlkIjo3NjM3MTkxNiwiaWFkIjoiMjAyNS0wNi0xMlQxMjowMjowNi4wMDBaIiwicGVyIjoibWU6d3JpdGUiLCJhY3RpZCI6MTQ5ODgzMDQsInJnbiI6InVzZTEifQ.g8M5fmXYZ3eNUQWiPpnKmPHf1K0wrwdqi2HJFFl1P0Q'
HEADERS = {'Authorization': API_KEY, 'Content-Type': 'application/json', 'API-Version': '2023-07'}
WORKSPACE_ID = 10987132

# Méthode 1: Chercher tous les boards du workspace
print("1. Recherche de tous les boards du workspace...")
all_boards = []
page = 1
while page <= 10:
    query = f'''query {{ boards (workspace_ids: [{WORKSPACE_ID}], limit: 50, page: {page}) {{ id name }} }}'''
    r = requests.post('https://api.monday.com/v2', headers=HEADERS, json={'query': query})
    result = r.json()
    boards = result.get('data', {}).get('boards', [])
    if not boards:
        break
    all_boards.extend(boards)
    print(f"   Page {page}: {len(boards)} boards")
    page += 1

print(f"\n   ✓ Total boards dans workspace: {len(all_boards)}")

# Chercher Euroenergy
print("\n2. Recherche 'euro' dans les noms:")
for b in all_boards:
    if 'euro' in b['name'].lower():
        print(f"   ✓ TROUVÉ: {b['name']} (ID: {b['id']})")

# Méthode 2: Recherche directe par nom
print("\n3. Recherche directe 'Régie Euroenergy'...")
query = '''
query {
    boards (limit: 10) {
        id
        name
    }
}
'''
# On ne peut pas filtrer par nom directement, mais on peut lister

# Méthode 3: Chercher dans le dossier avec board_kind
print("\n4. Test avec board_kind...")
query = '''
query ($folder_id: [ID!]) {
    boards (folder_ids: $folder_id, board_kind: public, limit: 100) {
        id
        name
    }
}
'''
r = requests.post('https://api.monday.com/v2', headers=HEADERS, json={'query': query, 'variables': {'folder_id': [17252518]}})
result = r.json()
print(f"   Résultat: {result}")
