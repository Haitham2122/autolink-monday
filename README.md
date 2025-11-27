# Monday.com Webhook Receiver - FastAPI

Application FastAPI pour recevoir et traiter les webhooks de monday.com.

## 🚀 Installation

1. **Installer les dépendances :**
```bash
pip install -r requirements.txt
```

2. **Lancer l'application :**
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

### `GET /health`
Health check endpoint.

### `POST /webhook`
Endpoint principal pour recevoir les webhooks de monday.com.

**Headers optionnels :**
- `X-Monday-Signature`: Signature du webhook (pour vérification)

**Body :** JSON avec les données du webhook

**Réponse :**
```json
{
  "success": true,
  "message": "Webhook received and processed",
  "event_type": "change_column_value",
  "timestamp": "2024-01-15T10:30:00"
}
```

### `POST /webhook/test`
Endpoint de test pour simuler un webhook (utile pour le développement).

## 🔧 Configuration Monday.com

1. Allez dans votre board monday.com
2. Ouvrez les paramètres du board
3. Allez dans "Integrations" → "Webhooks"
4. Ajoutez une nouvelle intégration webhook
5. Configurez l'URL : `https://votre-domaine.com/webhook`
6. Sélectionnez les événements que vous souhaitez recevoir

## 📝 Structure des Webhooks

Les webhooks de monday.com peuvent contenir différents types d'événements :

- `create_pulse` : Création d'un nouveau pulse
- `change_column_value` : Modification d'une valeur de colonne
- `change_status` : Changement de statut
- `change_name` : Changement de nom
- Et plus selon vos configurations

## 🔒 Sécurité

### Vérification de signature (à implémenter)

Si vous configurez un secret de signature dans monday.com, vous devrez implémenter la vérification :

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

## 🛠️ Personnalisation

### Ajouter votre logique de traitement

Modifiez la fonction `process_webhook()` dans `main.py` pour ajouter votre logique métier :

```python
def process_webhook(payload: Dict[str, Any], event_type: Optional[str]):
    # Votre logique ici
    # Exemples :
    # - Sauvegarder en base de données
    # - Appeler d'autres APIs
    # - Envoyer des notifications
    # - Déclencher des workflows
    pass
```

## 📊 Documentation API

Une fois l'application lancée, accédez à :
- **Swagger UI** : http://localhost:8000/docs
- **ReDoc** : http://localhost:8000/redoc

## 🧪 Tests

Testez votre webhook localement avec curl :

```bash
curl -X POST http://localhost:8000/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "event": {
      "type": "change_column_value",
      "pulseId": "123",
      "boardId": "456"
    },
    "data": {
      "column_id": "status",
      "value": "Done"
    }
  }'
```

## 📦 Déploiement

### Avec Docker (optionnel)

Créez un `Dockerfile` :

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Avec ngrok (pour développement local)

Pour tester les webhooks localement, utilisez ngrok :

```bash
ngrok http 8000
```

Utilisez l'URL ngrok dans la configuration webhook de monday.com.

## 📚 Ressources

- [Documentation FastAPI](https://fastapi.tiangolo.com/)
- [Documentation Monday.com Webhooks](https://developer.monday.com/api-reference/docs/webhooks)

## ⚠️ Notes

- Les webhooks doivent répondre rapidement (< 5 secondes)
- Implémentez un système de retry pour les traitements longs
- Utilisez une file d'attente (Redis, RabbitMQ) pour les traitements asynchrones si nécessaire

