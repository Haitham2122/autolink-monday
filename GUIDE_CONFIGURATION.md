# Guide de Configuration - Auto-Link Monday.com

## 📋 Vue d'ensemble

Ce système synchronise automatiquement les colonnes entre deux tableaux Monday.com :
- **Tableau Principal** : Celui qui envoie le webhook
- **Tableau Admin** : Celui qui reçoit les mises à jour

## 🔧 Configuration Initiale

### 1. Modifier `config.json`

Ouvrez le fichier `config.json` et remplissez les informations :

```json
{
  "main_board_id": "VOTRE_BOARD_ID_PRINCIPAL",
  "admin_board_id": 9962467444,
  "main_id_column": "text_mkrctj55",
  "admin_id_column": "text_mkregyd5",
  "excluded_columns": [
    "name"
  ]
}
```

**Comment trouver ces valeurs :**

#### `main_board_id` - ID du tableau principal
1. Allez sur votre tableau principal dans Monday.com
2. L'URL ressemble à : `https://yourcompany.monday.com/boards/123456789`
3. Le nombre après `/boards/` est votre `main_board_id`

#### `admin_board_id` - ID du tableau admin
- Même procédure que ci-dessus
- Déjà configuré : `9962467444`

#### `main_id_column` - ID de la colonne ID_admin dans le tableau principal
1. Sur le tableau principal, cliquez sur une colonne
2. Allez dans les paramètres de la colonne
3. L'ID de la colonne apparaît dans l'URL ou dans les paramètres avancés
4. Déjà configuré : `text_mkrctj55`

#### `admin_id_column` - ID de la colonne ID_admin dans le tableau admin
- Même procédure que ci-dessus
- Déjà configuré : `text_mkregyd5`

#### `excluded_columns` - Colonnes à ne PAS transférer
Liste des IDs de colonnes que vous ne voulez PAS synchroniser.

**Exemples de colonnes à exclure :**
- `"name"` : Le nom de l'item
- Mirror columns (colonnes miroir)
- Colonnes de formules
- Colonnes auto-calculées

**Pour trouver l'ID d'une colonne à exclure :**
1. Utilisez l'API Monday.com pour lister toutes les colonnes
2. Ou inspectez les colonnes via la documentation Monday.com

### 2. Vérifier la clé API

Dans `app.py`, la clé API est déjà configurée :
```python
apiKey = "eyJhbGciOiJIUzI1NiJ9..."
```

⚠️ **Sécurité** : Pour la production, utilisez plutôt des variables d'environnement.

## 🚀 Déploiement

### Installation locale

```bash
# Installer les dépendances
pip install -r requirements.txt

# Lancer l'application
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

### Déploiement sur Heroku/Render/Railway

```bash
git add .
git commit -m "Configuration auto-link"
git push origin main
```

L'application sera accessible à : `https://votre-app.herokuapp.com`

## 🔗 Configuration du Webhook Monday.com

### 1. Créer l'intégration webhook

1. Allez sur votre **tableau principal** dans Monday.com
2. Cliquez sur l'icône en haut à droite → **Integrations**
3. Cherchez "**Webhooks**" et sélectionnez
4. Cliquez sur "**New Integration**"

### 2. Configurer l'URL

```
https://votre-app.herokuapp.com/auto-link
```

### 3. Sélectionner les événements

Cochez les événements qui doivent déclencher la synchronisation :

✅ **Événements recommandés :**
- `change_column_value` : Quand une colonne change
- `change_specific_column_value` : Quand une colonne spécifique change
- `create_pulse` : Quand un nouvel item est créé

### 4. Tester le webhook

1. Modifiez un item dans le tableau principal
2. Vérifiez les logs de votre application
3. Vérifiez que l'item correspondant dans le tableau admin a été mis à jour

## 📊 Flux de Données

```
Tableau Principal (Item modifié)
  ↓ Webhook
  ↓ Extraction ID_ (pulseId)
  ↓ Récupération ID_admin de la colonne text_mkrctj55
  ↓ Recherche dans Tableau Admin
  ↓ Récupération item avec ID_admin correspondant (ID__)
  ↓ Copie de toutes les colonnes (sauf exclusions)
  ↓ Effacement colonnes de l'item admin
  ↓ Mise à jour avec nouvelles valeurs
  ↓ Succès ✅
```

## 🧪 Tests

### Test manuel avec curl

```bash
curl -X POST https://votre-app.herokuapp.com/auto-link \
  -H "Content-Type: application/json" \
  -d '{
    "event": {
      "pulseId": "10974880446",
      "type": "change_column_value",
      "boardId": "VOTRE_BOARD_ID"
    }
  }'
```

### Vérifier les logs

Les logs afficheront :
- ID de l'item principal (ID_)
- Valeur de l'ID_admin récupéré
- ID de l'item admin trouvé (ID__)
- Nombre de colonnes transférées
- Détails des opérations

## ⚠️ Points d'Attention

### 1. Types de colonnes

Certains types de colonnes peuvent nécessiter un traitement spécial :
- **People** : Format JSON spécifique
- **Date** : Format ISO
- **Status** : Doit correspondre aux statuts disponibles
- **Dropdown** : Doit correspondre aux options disponibles

### 2. Performance

- L'API Monday.com a des limites de rate limiting
- Évitez de déclencher trop de webhooks simultanément
- Les colonnes miroir ne peuvent pas être modifiées directement

### 3. Erreurs courantes

**"Aucun item admin trouvé"**
- Vérifiez que la valeur ID_admin existe dans le tableau admin
- Vérifiez que l'ID de colonne est correct

**"Colonne ID_admin non trouvée"**
- Vérifiez l'ID de la colonne dans config.json
- Assurez-vous que la colonne existe dans le tableau principal

**"Erreur lors de la mise à jour"**
- Certaines colonnes peuvent être en lecture seule
- Ajoutez-les à `excluded_columns`

## 📝 Exemples de Configuration

### Exemple 1 : Exclure plusieurs colonnes

```json
{
  "excluded_columns": [
    "name",
    "mirror_column_id",
    "formula_column_id",
    "text_mkrctj55"
  ]
}
```

### Exemple 2 : Configuration complète

```json
{
  "main_board_id": "123456789",
  "admin_board_id": 9962467444,
  "main_id_column": "text_mkrctj55",
  "admin_id_column": "text_mkregyd5",
  "excluded_columns": [
    "name",
    "subitems",
    "mirror_id",
    "formula_id"
  ]
}
```

## 🐛 Debugging

### Activer les logs détaillés

Les logs sont déjà activés. Pour les voir :

```bash
# En local
tail -f logs/app.log

# Sur Heroku
heroku logs --tail

# Sur Render
Voir les logs dans le dashboard
```

### Tester une fonction isolée

```python
from monday_api import get_column_value_for_item

result = get_column_value_for_item(
    api_token="votre_token",
    item_id=10974880446,
    column_id="text_mkrctj55"
)
print(result)
```

## 📚 Ressources

- [Documentation Monday.com API](https://developer.monday.com/api-reference/docs)
- [Documentation Webhooks](https://developer.monday.com/api-reference/docs/webhooks)
- [Types de colonnes Monday.com](https://developer.monday.com/api-reference/docs/column-types)
