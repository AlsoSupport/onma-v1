"""
Punto de entrada para bot-hosting.net.
bot-hosting.net normalmente ejecuta `python main.py`, así que acá levantamos
uvicorn manualmente en el puerto que la plataforma indique via variable de
entorno PORT (o 8000 si no está definida, para pruebas locales).
"""
import os
import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("api_server:app", host="0.0.0.0", port=port, reload=False)
