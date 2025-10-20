from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import os, requests

# ---- Config ----
OPENCAGE_API_KEY = os.getenv("OPENCAGE_API_KEY")  # set this on Render later

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

@app.get("/health")
def health():
    return {"status": "ok"}

# --- Services ---
def geocode(address: str):
    if not OPENCAGE_API_KEY:
        raise HTTPException(500, "Server missing OPENCAGE_API_KEY")
    url = "https://api.opencagedata.com/geocode/v1/json"
    r = requests.get(url, params={"key": OPENCAGE_API_KEY, "q": address, "limit": 1}, timeout=12)
    r.raise_for_status()
    data = r.json()
    if not data.get("results"):
        return None, None
    g = data["results"][0]["geometry"]
    return g["lat"], g["lng"]

def get_elevation(lat: float, lon: float):
    # Open-Elevation: no API key needed
    r = requests.get(f"https://api.open-elevation.com/api/v1/lookup?locations={lat},{lon}", timeout=12)
    r.raise_for_status()
    return r.json()["results"][0]["elevation"]

def get_avg_monthly_rain(lat: float, lon: float):
    url = ("https://archive-api.open-meteo.com/v1/archive"
           f"?latitude={lat}&longitude={lon}"
           "&start_date=2023-01-01&end_date=2023-12-31"
           "&daily=precipitation_sum&timezone=auto")
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    daily = r.json()["daily"]["precipitation_sum"]
    return sum(daily) / 12.0

def calc_risk(elev_m: float, avg_mm: float):
    e = 0 if elev_m >= 20 else 1 if elev_m >= 10 else 2 if elev_m >= 5 else 3
    r = 0 if avg_mm <= 50 else 1 if avg_mm <= 90 else 2 if avg_mm <= 120 else 3
    t = e + r
    return ("Very Low" if t <= 1 else
            "Low"      if t <= 3 else
            "Moderate" if t <= 4 else
            "High"     if t <= 5 else
            "Very High")

def tips_for(level: str):
    if level in ("High", "Very High"):
        return ["Install a sump pump w/ backup power.",
                "Seal foundation cracks & window wells.",
                "Redirect downspouts 3–6 ft from foundation."]
    if level == "Moderate":
        return ["Consider a French drain.",
                "Regrade soil to slope away from the house.",
                "Use native plants for absorption."]
    return ["Maintain gutters/downspouts.",
            "Keep a basic emergency kit.",
            "Sign up for local weather alerts."]

# --- Endpoint ---
@app.get("/risk")
def risk(address: str = Query(..., min_length=3)):
    try:
        lat, lon = geocode(address)
        if lat is None:
            raise HTTPException(400, "Address not found")
        elev = get_elevation(lat, lon)
        avg_rain = get_avg_monthly_rain(lat, lon)
        level = calc_risk(elev, avg_rain)
        return {
            "address": address, "lat": lat, "lon": lon,
            "elevation_m": elev, "avg_monthly_rain_mm": avg_rain,
            "risk_level": level, "tips": tips_for(level)
        }
    except HTTPException:
        raise
    except requests.HTTPError as e:
        # Bubble up useful upstream error info
        raise HTTPException(502, f"Upstream API failed: {e}")
    except Exception as e:
        raise HTTPException(500, f"Server error: {e}")
