from typing import Dict, Any
from fastapi import FastAPI, Response, Request,Form
from fastapi.responses import HTMLResponse, StreamingResponse
from datetime import datetime

app = FastAPI(
    title="Monday.com Webhook Receiver",
    description="API pour recevoir et traiter les webhooks de monday.com",
    version="1.0.0"
)

# Configuration Monday.com API
apiKey = "eyJhbGciOiJIUzI1NiJ9.eyJ0aWQiOjUyNTUxMDkxOCwiYWFpIjoxMSwidWlkIjo3NjM3MTkxNiwiaWFkIjoiMjAyNS0wNi0xMlQxMjowMjowNi4wMDBaIiwicGVyIjoibWU6d3JpdGUiLCJhY3RpZCI6MTQ5ODgzMDQsInJnbiI6InVzZTEifQ.g8M5fmXYZ3eNUQWiPpnKmPHf1K0wrwdqi2HJFFl1P0Q"
apiUrl = "https://api.monday.com/v2"
headers = {"Authorization": apiKey}


@app.get("/")
async def root():
    """Endpoint de base pour vérifier que l'API fonctionne"""
    return {
        "message": "Monday.com Webhook Receiver API",
        "status": "running",
        "timestamp": datetime.utcnow().isoformat()
    }


@app.post("/auto-link")
async def projets(request: Dict[Any, Any]):
    try:
        print(request)
        id_ = request['event']['pulseId']
        
        
        
    except:
        return request


