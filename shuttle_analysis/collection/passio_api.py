import requests


class PassioAPI:
    """Communicate with Passio GO for a configured system and route.

    Return complete decoded API responses without polling, writing files,
    or interpreting predictions. Request and JSON decoding errors propagate
    to the caller.
    """

    def __init__(self, system_id=94, route_id=71342, timeout=10):
        """Initialize the client with a system ID, route ID, and timeout.

        The timeout is measured in seconds. Defaults target MIT's Boston
        Daytime route.
        """
        self.system_id = system_id
        self.route_id = route_id
        self.timeout = timeout
        self.url = "https://passiogo.com/mapGetData.php"

    def get_etas(self, stop_id, route_id=None):
        """Retrieve ETA predictions for a stop as a complete decoded response.

        Args:
            stop_id: The Passio GO identifier of the requested stop.
            route_id: Optional route to request. Defaults to this client's
                configured route without changing its configuration.

        Returns:
            A Python dict decoded from JSON, preserving API metadata.
            Abbreviated example of the observed response format:

            {
                "ETAs": {
                    "979": [
                        {
                            "busId": 17693,
                            "tripId": "1072829",
                            "routeId": "71342",
                            "stopId": "979",
                            "eta": "7 min ",
                            "secondsSpent": 396,
                            "arrivalTimestamp": 1793890361,
                            "routeStopPosition": 7,
                            "busLatLng": [42.35941361, -71.09389848],
                            "theStop": {
                                "position": 1,
                                "routeStopId": "1644957"
                            }
                        }
                    ]
                },
                "time": "2026-11-05 09:46:05 AM",
                "debug": {}
            }

            ETAs maps string stop IDs to lists of predictions; a stop can
            have multiple predictions or an empty list. Fields may be
            absent or null (decoded as None). Earlier responses also used
            nested solidEta fields. The example omits additional fields;
            this method returns the response without normalizing it.
        """
        params = {
            "eta": 3,
            "deviceId": 155555126,
            "stopIds": stop_id,
            "routeId": self.route_id if route_id is None else route_id,
            "position": 0,
            "userId": self.system_id,
        }
        response = requests.get(self.url, params=params, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def get_vehicles(self):
        """Retrieve independent live vehicle data for the configured system.

        Returns:
            A Python dict decoded from JSON. Abbreviated observed example:

            {
                "buses": {
                    "417748": [
                        {
                            "busId": 3009,
                            "busName": "910",
                            "deviceId": 417748,
                            "routeId": "71342",
                            "route": "Boston Daytime",
                            "latitude": "42.349208133",
                            "longitude": "-71.094778667",
                            "created": "10:15 AM",
                            "createdTime": "10:15 AM",
                            "outOfService": 0,
                            "outdated": 0
                        }
                    ]
                },
                "debug": {"systemIds": [94]},
                "microtime": 0.027745962142944336,
                "time": {"94": "10:15 AM"}
            }

            The buses mapping uses string device IDs as keys and lists of
            records as values. It includes other routes in the system;
            callers can filter records by routeId. Coordinates were strings
            in the observed response. The observed time fields lack a date,
            seconds, and timezone and do not establish precise GPS fix times.
            Fields can vary; all original fields are returned unchanged.
            Request and JSON decoding errors propagate to the caller.
        """
        response = requests.post(
            self.url,
            params={"getBuses": 2},
            json={"s0": str(self.system_id), "sA": 1},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def get_stops(self):
        """Return complete decoded stop and route metadata for the system.

        Includes system-wide stops and ordered route occurrences. Callers
        can select the configured route from the response's routes mapping.
        Request and JSON decoding errors propagate to the caller.

        Returns:
            A Python dict decoded from JSON. Abbreviated observed example:

            {
                "stops": {
                    "ID979": {
                        "id": "979",
                        "name": "84 Massachusetts Ave",
                        "latitude": 42.358729734,
                        "longitude": -71.093422775,
                        "position": "11",
                        "routeId": "71342"
                    }
                },
                "routes": {
                    "71342": [
                        "Boston Daytime",
                        "#9ecae1",
                        ["1", "979", 0],
                        ["2", "991", 0],
                        ...,
                        ["11", "979", 1]
                    ]
                }
            }

            The ellipsis represents omitted route entries. Stop dictionary
            keys use forms such as "ID979", while route keys are string IDs.
            A route list starts with its name and color, followed by ordered
            entries [position string, stop ID string, flag]. The flag's
            meaning is unverified. Repeated stop IDs represent separate
            route occurrences; a stop record's position alone does not
            capture them all.

            Additional top-level fields include routePoints, groupRoutes,
            routeShortNames, routeSchedules, routesRR, excludedRoutesID,
            and stopsRR. All original fields are returned unchanged.
        """
        response = requests.post(
            self.url,
            params={"getStops": 2},
            json={"s0": str(self.system_id), "sA": 1},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

if __name__ == "__main__":
    pass
    # from pprint import pprint

    # api = PassioAPI()

    # pprint(api.get_vehicles())
