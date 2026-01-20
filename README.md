# autolink-monday

Application FastAPI pour recevoir et traiter les webhooks de monday.com.

## 🚀 Installation

1. **Cloner le dépôt :**
```bash
git clone https://github.com/Haitham2122/autolink-monday.git
cd autolink-monday
```

2. **Installer les dépendances :**
```bash
pip install -r requirements.txt
```

3. **Lancer l'application :**
```bash
python main.py
```

Ou avec uvicorn directement :
```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

## 📡 Endpoints

### `GET /`
Endpoint de base pour vérifier que l'API fonctionne.

**Réponse :**
```json
{
  "message": "Monday.com Webhook Receiver API",
  "status": "running",
  "timestamp": "2026-01-20T10:30:00",
  "endpoints": {
    "webhook": "/webhook",
    "gendoc": "/Gendoc",
    "health": "/health"
  }
}
```

### `GET /health`
Health check endpoint pour vérifier l'état de l'API.

### `POST /webhook`
Endpoint principal pour recevoir les webhooks de monday.com.

**Headers optionnels :**
- `X-Monday-Signature`: Signature du webhook (pour vérification de sécurité)

**Body :** JSON avec les données du webhook

**Exemple de payload :**
```json
{
  "event": {
    "type": "change_column_value",
    "pulseId": "123456789",
    "boardId": "987654321",
    "userId": "111222333",
    "triggerTime": "2026-01-20T10:30:00"
  },
  "data": {
    "column_id": "status",
    "value": "Done"
  }
}
```

**Réponse :**
```json
{
  "success": true,
  "message": "Webhook received and processed",
  "event_type": "change_column_value",
  "pulse_id": "123456789",
  "timestamp": "2026-01-20T10:30:00"
}
```

### `POST /Gendoc`
Endpoint spécifique pour la génération de documents (compatible avec l'ancien format).

## 🔧 Configuration Monday.com

### 1. Créer un webhook dans Monday.com

1. Allez dans votre board monday.com
2. Cliquez sur l'icône du board (en haut à droite) → **Integrations**
3. Cherchez "**Webhooks**" et sélectionnez-le
4. Cliquez sur "**New Integration**"
5. Configurez l'URL : `https://votre-domaine.com/webhook`
6. Sélectionnez les événements que vous souhaitez recevoir :
   - `create_pulse` : Création d'un nouveau pulse
   - `change_column_value` : Modification d'une valeur de colonne
   - `change_status` : Changement de statut
   - `create_update` : Nouvelle mise à jour
7. Sauvegardez l'intégration

### 2. Configuration de la clé API

La clé API Monday.com est déjà configurée dans `main.py`. Pour la modifier :

```python
apiKey = "votre_cle_api_monday"
apiUrl = "https://api.monday.com/v2"
headers = {"Authorization": apiKey}
```

## 🛠️ Personnalisation

### Ajouter votre logique de traitement

Modifiez la fonction `process_monday_webhook()` dans `main.py` pour ajouter votre logique métier :

```python
def process_monday_webhook(payload: Dict[str, Any]):
    event = payload.get("event", {})
    event_type = event.get("type")
    
    if event_type == "change_column_value":
        # Votre logique personnalisée ici
        # Exemple : envoyer un email, générer un document, etc.
        pass
```

## 📊 Documentation API

Une fois l'application lancée, accédez à la documentation interactive :
- **Swagger UI** : http://localhost:8000/docs
- **ReDoc** : http://localhost:8000/redoc

## 🧪 Tests

### Test local avec curl

```bash
curl -X POST http://localhost:8000/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "event": {
      "type": "change_column_value",
      "pulseId": "123456789",
      "boardId": "987654321",
      "userId": "111222333"
    },
    "data": {
      "column_id": "status",
      "value": "Done"
    }
  }'
```

### Test avec ngrok (pour développement local)

Pour tester les webhooks localement avec Monday.com, utilisez ngrok :

```bash
ngrok http 8000
```

Utilisez l'URL ngrok (ex: `https://abc123.ngrok.io/webhook`) dans la configuration webhook de monday.com.

## 📦 Déploiement

### Heroku

L'application est prête pour être déployée sur Heroku avec :
- `Procfile` : Configuration pour lancer l'application
- `runtime.txt` : Spécification de la version Python
- `requirements.txt` : Dépendances Python

```bash
heroku create votre-app-name
git push heroku main
```

### Render / Railway / Fly.io

L'application est compatible avec toutes les plateformes PaaS qui supportent Python et FastAPI.

## 🔒 Sécurité

### Variables d'environnement

Pour une meilleure sécurité, utilisez des variables d'environnement pour les clés API :

1. Créez un fichier `.env` :
```
MONDAY_API_KEY=votre_cle_api
PORT=8000
```

2. Utilisez `python-dotenv` :
```python
from dotenv import load_dotenv
import os

load_load_dotenv()
apiKey = os.getenv("MONDAY_API_KEY")
```

### Vérification de signature

Pour vérifier l'authenticité des webhooks, implémentez la vérification de signature :

```python
import hmac
import hashlib

def verify_signature(payload: bytes, signature: str, secret: str) -> bool:
    expected_signature = hmac.new(
        secret.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected_signature, signature)
```

## 📚 Ressources

- [Documentation FastAPI](https://fastapi.tiangolo.com/)
- [Documentation Monday.com API](https://developer.monday.com/api-reference/docs)
- [Documentation Monday.com Webhooks](https://developer.monday.com/api-reference/docs/webhooks)

## 📝 Logs

L'application utilise le module `logging` de Python. Les logs affichent :
- Réception des webhooks
- Type d'événement
- Pulse ID, Board ID, User ID
- Erreurs éventuelles

## ⚠️ Notes

- Les webhooks doivent répondre rapidement (< 5 secondes)
- Monday.com réessaiera l'envoi en cas d'échec
- Implémentez un système de file d'attente pour les traitements longs
- Utilisez Redis ou RabbitMQ pour les traitements asynchrones si nécessaire

## 🤝 Contribution

Les contributions sont les bienvenues ! N'hésitez pas à ouvrir une issue ou une pull request.

## 📄 Licence

MIT License
