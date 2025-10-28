from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from services.ai import generate_advice
import os, requests

# ---- Config ----
OPENCAGE_API_KEY = os.getenv("OPENCAGE_API_KEY")  # set this on Render

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
    """
    Returns (lat, lon, state_code) when available.
    """
    if not OPENCAGE_API_KEY:
        raise HTTPException(500, "Server missing OPENCAGE_API_KEY")
    url = "https://api.opencagedata.com/geocode/v1/json"
    r = requests.get(
        url,
        params={"key": OPENCAGE_API_KEY, "q": address, "limit": 1},
        timeout=12,
    )
    r.raise_for_status()
    data = r.json()
    if not data.get("results"):
        return None, None, None
    res0 = data["results"][0]
    g = res0["geometry"]
    comps = res0.get("components", {}) or {}
    # OpenCage gives `state_code` for US results; if absent we leave None
    state_code = comps.get("state_code")
    return g["lat"], g["lng"], state_code

def get_elevation(lat: float, lon: float):
    r = requests.get(
        f"https://api.open-elevation.com/api/v1/lookup?locations={lat},{lon}",
        timeout=12,
    )
    r.raise_for_status()
    return r.json()["results"][0]["elevation"]

def get_avg_monthly_rain(lat: float, lon: float):
    url = (
        "https://archive-api.open-meteo.com/v1/archive"
        f"?latitude={lat}&longitude={lon}"
        "&start_date=2023-01-01&end_date=2023-12-31"
        "&daily=precipitation_sum&timezone=auto"
    )
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
        return [
            "Install a sump pump w/ backup power.",
            "Seal foundation cracks & window wells.",
            "Redirect downspouts 3–6 ft from foundation.",
        ]
    if level == "Moderate":
        return [
            "Consider a French drain.",
            "Regrade soil to slope away from the house.",
            "Use native plants for absorption.",
        ]
    return [
        "Maintain gutters/downspouts.",
        "Keep a basic emergency kit.",
        "Sign up for local weather alerts.",
    ]

# Helpers for live-alert bump
def bump_risk(level: str) -> str:
    order = ["Very Low", "Low", "Moderate", "High", "Very High"]
    try:
        i = order.index(level)
    except ValueError:
        i = 0
    return order[min(i + 1, len(order) - 1)]

def floodish(event: str) -> bool:
    e = (event or "").lower()
    return any(k in e for k in ["flood", "flash", "coastal", "surge"])

# --- Endpoint ---
@app.get("/risk")
def risk(address: str = Query(..., min_length=3)):
    try:
        lat, lon, state_code = geocode(address)
        if lat is None:
            raise HTTPException(400, "Address not found")

        elev = get_elevation(lat, lon)
        avg_rain = get_avg_monthly_rain(lat, lon)
        level = calc_risk(elev, avg_rain)

        # -------- LIVE NWS ALERT BUMP (place AFTER base score, BEFORE return) --------
        alert_bump_applied = False
        debug_alerts_count = 0

        try:
            headers = {
                "User-Agent": "AquaAlert/1.0 (contact: you@example.com)",
                "Accept": "application/geo+json",
            }

            # 1) precise point query
            r = requests.get(
                "https://api.weather.gov/alerts/active",
                params={"status": "actual", "point": f"{lat},{lon}"},
                headers=headers,
                timeout=8,
            )
            feats = r.json().get("features", []) if r.ok else []

            # 2) fallback to state-wide if nothing at the exact point and we have a 2-letter code
            if not feats and state_code and len(state_code) == 2:
                r2 = requests.get(
                    "https://api.weather.gov/alerts/active",
                    params={"status": "actual", "area": state_code.upper()},
                    headers=headers,
                    timeout=8,
                )
                if r2.ok:
                    feats = r2.json().get("features", []) or []

            flood_feats = [
                f for f in feats
                if floodish((f.get("properties") or {}).get("event"))
            ]
            debug_alerts_count = len(flood_feats)

            if flood_feats:
                severities = [
                    ((f.get("properties") or {}).get("severity") or "").lower()
                    for f in flood_feats
                ]
                if any(s in ("severe", "extreme") for s in severities):
                    level = "High"
                else:
                    level = bump_risk(level)
                alert_bump_applied = True
        except Exception:
            # keep service resilient even if NWS hiccups
            pass
        # --------------------------- END BUMP ----------------------------------------

        return {
            "address": address,
            "lat": lat,
            "lon": lon,
            "elevation_m": elev,
            "avg_monthly_rain_mm": avg_rain,
            "risk_level": level,
            "tips": tips_for(level),
            # debug fields (leave while testing, remove later if you want)
            "alert_bump_applied": alert_bump_applied,
            "debug_alerts_count": debug_alerts_count,
            "state_code": state_code,
        }

    except HTTPException:
        raise
    except requests.HTTPError as e:
        raise HTTPException(502, f"Upstream API failed: {e}")
    except Exception as e:
        raise HTTPException(500, f"Server error: {e}")

class AdvisorRequest(BaseModel):
    address: str
    elevation_m: float
    avg_monthly_rain_mm: float
    risk_level: str
    specs: str | None = None  # user-provided extra details via chat

@app.post("/advisor")
def advisor(body: AdvisorRequest):
    try:
        advice = generate_advice(
            address=body.address,
            elevation_m=body.elevation_m,
            avg_rain_mm=body.avg_monthly_rain_mm,
            risk_level=body.risk_level,
            specs=body.specs or "",
        )
        return {"advice": advice}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM error: {e}")
