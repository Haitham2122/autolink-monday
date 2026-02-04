"""
Test de recherche de la régie Euroenergy
"""
import requests

API_KEY = 'eyJhbGciOiJIUzI1NiJ9.eyJ0aWQiOjUyNTUxMDkxOCwiYWFpIjoxMSwidWlkIjo3NjM3MTkxNiwiaWFkIjoiMjAyNS0wNi0xMlQxMjowMjowNi4wMDBaIiwicGVyIjoibWU6d3JpdGUiLCJhY3RpZCI6MTQ5ODgzMDQsInJnbiI6InVzZTEifQ.g8M5fmXYZ3eNUQWiPpnKmPHf1K0wrwdqi2HJFFl1P0Q'
HEADERS = {'Authorization': API_KEY, 'Content-Type': 'application/json', 'API-Version': '2023-07'}
WORKSPACE_ID = 10987132

# 1. Trouver le dossier Régies
print("1. Recherche du dossier Régies...")
query = '''query { folders (workspace_ids: [10987132]) { id name } }'''
r = requests.post('https://api.monday.com/v2', headers=HEADERS, json={'query': query})
folders = r.json().get('data', {}).get('folders', [])
print(f"   Dossiers trouvés: {[f['name'] for f in folders]}")

folder_id = None
for f in folders:
    if 'régie' in f['name'].lower() or 'regie' in f['name'].lower():
        folder_id = f['id']
        print(f"   ✓ Dossier Régies trouvé: ID {folder_id}")
        break

# 2. Récupérer les boards du dossier
if folder_id:
    print("\n2. Récupération des boards...")
    all_boards = []
    page = 1
    while page <= 5:
        query = f'''query {{ boards (folder_ids: [{folder_id}], limit: 50, page: {page}) {{ id name }} }}'''
        r = requests.post('https://api.monday.com/v2', headers=HEADERS, json={'query': query})
        boards = r.json().get('data', {}).get('boards', [])
        if not boards:
            break
        all_boards.extend(boards)
        page += 1
    
    print(f"   ✓ Total boards: {len(all_boards)}")
    
    # Chercher Euroenergy
    print("\n3. Recherche 'Euroenergy':")
    found = False
    for b in all_boards:
        if 'euro' in b['name'].lower():
            print(f"   ✓ TROUVÉ: {b['name']} (ID: {b['id']})")
            found = True
    
    if not found:
        print("   ✗ Non trouvé!")
        print("\n   Premiers 20 boards:")
        for b in all_boards[:20]:
            print(f"      - {b['name']}")
