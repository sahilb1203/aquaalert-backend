# services/ai.py
import os
from openai import OpenAI

SYSTEM_PROMPT = (
    "You are an AI assistant that gives recommendations to people "
    "about what to do for flood preparedness and response based on their address and home details. "
    "First, output 2–4 bullet points (no intro text). Then add one blank line and provide a concise explanation "
    "(max 2 paragraphs) covering how to execute the recommendations and why you chose them. "
    "Keep tone clear, calm, and practical. Avoid medical or emergency claims; focus on general safety tips."
)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def generate_advice(address: str, elevation_m: float, avg_rain_mm: float, risk_level: str, specs: str = "") -> str:
    user_payload = (
        f"Address: {address}\n"
        f"Elevation: {elevation_m:.2f} meters\n"
        f"Average Monthly Rainfall: {avg_rain_mm:.2f} millimeters\n"
        f"Flood Risk: {risk_level}\n"
        f"Home Specs / Notes: {specs or 'N/A'}"
    )

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_payload},
        ],
        temperature=0.6,
    )
    return resp.choices[0].message.content.strip()
