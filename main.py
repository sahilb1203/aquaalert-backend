# main.py
from fastapi import FastAPI, Query

app = FastAPI()

from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)


@app.get("/")
def root():
    return {"message": "Hello AquaAlert!"}

@app.get("/risk")
def risk(address: str = Query(..., min_length=3)):
    return {
        "address": address,
        "lat": 40.74,
        "lon": -74.02,
        "elevation_m": 7.0,
        "avg_monthly_rain_mm": 82.0,
        "risk_level": "Moderate",
        "tips": [
            "Consider a French drain.",
            "Regrade soil away from the house.",
            "Use native plants to absorb water."
        ]
    }
