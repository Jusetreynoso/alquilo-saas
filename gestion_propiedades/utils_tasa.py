import urllib.request
import json
from django.core.cache import cache

def obtener_tasa_dolar():
    tasa = cache.get('tasa_dolar_bhd')
    if tasa:
        return tasa
        
    try:
        # Usamos ExchangeRate-API como fuente estable para la tasa del dólar (DOP)
        # ya que los portales bancarios dominicanos suelen bloquear scrapers.
        req = urllib.request.Request('https://api.exchangerate-api.com/v4/latest/USD')
        r = urllib.request.urlopen(req, timeout=5)
        data = json.loads(r.read().decode('utf-8'))
        tasa = data['rates']['DOP']
        
        # Guardar en cache por 12 horas para no hacer peticiones lentas constantemente
        cache.set('tasa_dolar_bhd', tasa, 60 * 60 * 12)
        return tasa
    except Exception:
        # Tasa de fallback en caso de error de conexión
        return 60.00
