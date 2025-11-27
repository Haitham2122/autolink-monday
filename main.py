from typing import Dict, Any
from fastapi import FastAPI


app = FastAPI()

apiKey = "eyJhbGciOiJIUzI1NiJ9.eyJ0aWQiOjUyNTUxMDkxOCwiYWFpIjoxMSwidWlkIjo3NjM3MTkxNiwiaWFkIjoiMjAyNS0wNi0xMlQxMjowMjowNi4wMDBaIiwicGVyIjoibWU6d3JpdGUiLCJhY3RpZCI6MTQ5ODgzMDQsInJnbiI6InVzZTEifQ.g8M5fmXYZ3eNUQWiPpnKmPHf1K0wrwdqi2HJFFl1P0Q"
apiUrl = "https://api.monday.com/v2"
headers = {"Authorization" : apiKey}
#------------------------------------------------ KIZEO platforme -----------------------------------------------------





@app.post("/Gendoc")
async def gen(request: Dict[Any, Any]):
    print(request) 
    print('-----------------------------------')
    
    id_=request['event']['pulseId']
    ss=get_info(id_)
    Nom_   =ss['items'][0]['name']
    gender=ss['items'][0]['column_values'][0]['text']
    Address=ss['items'][0]['column_values'][1]['text']
    email =ss['items'][0]['column_values'][3]['text']
    Devis =ss['items'][0]['column_values'][5]['text']
    if len(Devis.split(',')) > 1 :
        pass
    else :
        send_msg(Nom_,Address,gender,Devis,email)
    return request
