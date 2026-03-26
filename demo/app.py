from flask import Flask, render_template, jsonify, request
import threading, time, requests
from ais_worker import start_ais_listener

app = Flask(__name__)

# ===== AIS (memoria condivisa) =====
navi = {}

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/navi")
def get_navi():
    # Filtra solo navi tra Venezia e Trieste
    filtered = []
    for nave in navi.values():
        if (nave.get("lat") is not None and nave.get("lon") is not None and
            45.2 <= nave["lat"] <= 46.0 and 12.0 <= nave["lon"] <= 14.0):
            filtered.append({
                "mmsi": nave["mmsi"],
                "lat": nave["lat"],
                "lon": nave["lon"],
                "name": nave.get("name", "N/A"),
                "type": nave.get("type", "N/A")
            })
    return jsonify(filtered)

@app.route("/get_ship_position")
def get_ship_position():
    mmsi = request.args.get("mmsi")
    if not mmsi:
        return jsonify({"error": "Parametro mmsi mancante"}), 400

    mmsi = str(mmsi)
    nave = None
    for k, v in navi.items():
        if str(k) == mmsi:
            nave = v
            break

    if nave and nave.get("lat") is not None and nave.get("lon") is not None:
        return jsonify({"lat": nave["lat"], "lng": nave["lon"]})
    else:
        return jsonify({"error": "Nave non trovata"}), 404

# ===== Open-Meteo proxy con cache (10 min) =====
OPENMETEO_HEADERS = {"User-Agent": "adriatic-forecast/1.0"}
CACHE_TTL = 600  # secondi
_cache = {}      # key: "lat,lon" -> {"t": epoch, "data": json}

@app.get("/openmeteo")
def openmeteo_proxy():
    try:
        lat = float(request.args["lat"])
        lon = float(request.args["lon"])
    except Exception:
        return jsonify({"error": "Parametri lat/lon non validi"}), 400

    key = f"{lat:.4f},{lon:.4f}"
    now = time.time()

    # cache hit
    if key in _cache and (now - _cache[key]["t"] < CACHE_TTL):
        return jsonify(_cache[key]["data"])

    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": ",".join([
            "precipitation",
            "precipitation_probability",
            "weathercode",
            "cape",
            "windspeed_10m",
            "windgusts_10m"
        ]),
        "forecast_hours": 72,
        "precipitation_unit": "mm",
        "timezone": "Europe/Amsterdam"
    }

    try:
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params=params,
            headers=OPENMETEO_HEADERS,
            timeout=20
        )
        r.raise_for_status()
        data = r.json()
    except requests.RequestException as e:
        return jsonify({"error": f"Open-Meteo request failed: {e}"}), 502

    _cache[key] = {"t": now, "data": data}
    return jsonify(data)

# ===== avvia AIS worker =====
threading.Thread(target=start_ais_listener, args=(navi,), daemon=True).start()

if __name__ == "__main__":
    app.run(debug=True, threaded=True)