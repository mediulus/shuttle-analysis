from pathlib import Path
import pandas as pd


CSV = Path(__file__).resolve().parent.parent / "data" / "route_log.csv"
df = pd.read_csv(CSV, parse_dates=["collected_at_utc"])

# Per-leg congestion measures
df["delay_s"] = df["travel_time_s"] - df["no_traffic_time_s"]
df["slowdown_ratio"] = (df["travel_time_s"] / df["no_traffic_time_s"]).round(3)

# Boston local time, so "hour" means what you expect
df["local_time"] = df["collected_at_utc"].dt.tz_convert("America/New_York")
df["hour"] = df["local_time"].dt.hour

# Readable leg label; zero-padded so leg 10 sorts after leg 9
df["leg_name"] = (
    df["leg"].astype(int).map("{:02d}".format) + ": " + df["from_stop"] + " -> " + df["to_stop"]
)

# 1) Latest snapshot: how is each leg doing right now?
latest = df[df["collected_at_utc"] == df["collected_at_utc"].max()]
print(latest[["leg_name", "travel_time_s", "no_traffic_time_s", "delay_s", "slowdown_ratio"]]
      .to_string(index=False))

# 2) Overall summary per leg across everything collected
summary = df.groupby("leg_name").agg(
    samples=("delay_s", "size"),
    mean_delay_s=("delay_s", "mean"),
    max_delay_s=("delay_s", "max"),
    mean_slowdown=("slowdown_ratio", "mean"),
).round(2)
print("\n", summary)

# 3) Average delay per leg by hour of day (rows = legs, columns = hours)
by_hour = df.pivot_table(index="leg_name", columns="hour", values="delay_s", aggfunc="mean").round(1)
print("\n", by_hour)

# Save the per-leg results next to your raw data
df.to_csv(CSV.with_name("route_log_with_delay.csv"), index=False)