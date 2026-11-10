import requests

r = requests.get(
    "https://api.weather.gov/stations/KBOS/observations",
    headers={"User-Agent": "shuttle-analysis (you@example.com)"},
    params={"limit": 10},
    timeout=10,
)
print(r.status_code)
for f in r.json()["features"]:
    p = f["properties"]
    print(p["timestamp"], p["temperature"]["value"], p["textDescription"])