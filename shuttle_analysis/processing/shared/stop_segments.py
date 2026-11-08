"""Stop IDs and segment indices for the saved 384-point Boston Daytime loop.

Listed in route order. These placements still need field validation. Silber
Way (3042) is unresolved and the detector skips it when using this default list.
"""

BOSTON_DAYTIME_STOPS = [
    ("979", 0), ("991", 45), ("969", 62), ("3042", 114),
    ("968", 175), ("992", 222), ("976", 276), ("1002", 326),
    ("3039", 333), ("177583", 343), ("979", 382),
]
