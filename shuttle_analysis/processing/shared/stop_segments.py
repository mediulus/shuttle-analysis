"""Stop segments for the saved Boston Daytime and Saferide route shapes.

Listed in route order. Silber Way (3042) uses outbound segment 114, on the
same side of Commonwealth Avenue as 487 Comm. Ave. (969), before the turnaround.
The nearby return pass at segment 150 is not its boarding pass. These placements
still need field validation for precise boarding locations.
"""

BOSTON_DAYTIME_STOPS = [
    ("979", 0), ("991", 45), ("969", 62), ("3042", 114),
    ("968", 175), ("992", 222), ("976", 276), ("1002", 326),
    ("3039", 333), ("177583", 343), ("979", 382),
]

# Pin Boston East placements to the saved Passio geometry and stop order.
# Keys are actual API stop positions, including gaps.
SAFERIDE_SEGMENTS = {
    "70113": ("a5585cbc6d14", {
        "1": 0, "4": 52, "5": 84, "6": 232, "7": 284, "8": 329,
        "9": 357, "10": 411, "11": 442, "12": 0,
    }),
}
