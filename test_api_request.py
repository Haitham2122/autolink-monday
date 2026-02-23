import requests
import json

# Endpoint de l'API
url = "https://api.caex.tech/api/prospects"

# Données du TagList
tag_list_data = {
    "prenom": "Juan",
    "nom": "García",
    "token": "11304775880",
    "sexe": "M",
    "adresse": "Calle Mayor 123, 2º Izquierda",
    "codePostal": "28001",
    "ville": "Madrid",
    "endWork": "14/06/2025",
    "startWork": "14/06/2025",
    "pays": "España",
    "tel": "+34612345678",
    "email": "juan.garcia@example.com",
    "cadastralReference": "28001A01200001",
    "geoPosition": "40.4168,-3.7038",
    "EquipePose": "RA1 - (28) DPT",
    "installateurId": "cmlqg06rv03udpb0103pbpm50"
}

# Payload avec TagList comme chaîne JSON
payload = {
    "TagList": json.dumps(tag_list_data, ensure_ascii=False)
}

# Headers
headers = {
    "Content-Type": "application/json"
}

try:
    print(f"Envoi de la requête à {url}...")
    print(f"Payload: {json.dumps(payload, indent=2)}")
    print("\n" + "="*50 + "\n")
    
    # Envoi de la requête POST
    response = requests.post(url, json=payload, headers=headers, timeout=10)
    
    print(f"Status Code: {response.status_code}")
    print(f"\nHeaders de la réponse:")
    for key, value in response.headers.items():
        print(f"  {key}: {value}")
    
    print(f"\nCorps de la réponse:")
    try:
        response_json = response.json()
        print(json.dumps(response_json, indent=2, ensure_ascii=False))
    except:
        print(response.text)
        
except requests.exceptions.ConnectionError as e:
    print(f"Erreur de connexion: {e}")
except requests.exceptions.Timeout as e:
    print(f"Timeout: {e}")
except requests.exceptions.RequestException as e:
    print(f"Erreur lors de la requête: {e}")
except Exception as e:
    print(f"Erreur: {e}")
