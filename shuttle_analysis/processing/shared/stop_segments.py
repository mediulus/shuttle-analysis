"""Stop IDs and segment indices for the saved 384-point Boston Daytime loop.

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
