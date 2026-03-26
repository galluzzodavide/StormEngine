import asyncio
import websockets
import json

ship_type_dict = {
   0: "Not available",
    20: "Wing in ground (WIG), all",
    21: "WIG - Hazardous category A",
    22: "WIG - Hazardous category B",
    23: "WIG - Hazardous category C",
    24: "WIG - Hazardous category D",
    25: "WIG - Reserved",
    26: "WIG - Reserved",
    27: "WIG - Reserved",
    28: "WIG - Reserved",
    29: "WIG - No additional information",
    30: "Fishing",
    31: "Towing",
    32: "Towing (length > 200m or breadth > 25m)",
    33: "Dredging or underwater ops",
    34: "Diving ops",
    35: "Military ops",
    36: "Sailing",
    37: "Pleasure craft",
    40: "High speed craft (HSC), all",
    41: "HSC - Hazardous category A",
    42: "HSC - Hazardous category B",
    43: "HSC - Hazardous category C",
    44: "HSC - Hazardous category D",
    45: "HSC - Reserved",
    46: "HSC - Reserved",
    47: "HSC - Reserved",
    48: "HSC - Reserved",
    49: "HSC - No additional information",
    50: "Pilot vessel",
    51: "Search and rescue vessel",
    52: "Tug",
    53: "Port tender",
    54: "Anti-pollution equipment",
    55: "Law enforcement",
    56: "Spare (for assignments to local vessels)",
    57: "Spare (for assignments to local vessels)",
    58: "Medical transport",
    59: "Noncombatant ship according to RR Resolution No. 18",
    60: "Passenger, all",
    61: "Passenger - Hazardous category A",
    62: "Passenger - Hazardous category B",
    63: "Passenger - Hazardous category C",
    64: "Passenger - Hazardous category D",
    65: "Passenger - Reserved",
    66: "Passenger - Reserved",
    67: "Passenger - Reserved",
    68: "Passenger - Reserved",
    69: "Passenger - No additional information",
    70: "Cargo, all",
    71: "Cargo - Hazardous category A",
    72: "Cargo - Hazardous category B",
    73: "Cargo - Hazardous category C",
    74: "Cargo - Hazardous category D",
    75: "Cargo - Reserved",
    76: "Cargo - Reserved",
    77: "Cargo - Reserved",
    78: "Cargo - Reserved",
    79: "Cargo - No additional information",
    80: "Tanker, all",
    81: "Tanker - Hazardous category A",
    82: "Tanker - Hazardous category B",
    83: "Tanker - Hazardous category C",
    84: "Tanker - Hazardous category D",
    85: "Tanker - Reserved",
    86: "Tanker - Reserved",
    87: "Tanker - Reserved",
    88: "Tanker - Reserved",
    89: "Tanker - No additional information",
    90: "Other type, all",
    91: "Other - Hazardous category A",
    92: "Other - Hazardous category B",
    93: "Other - Hazardous category C",
    94: "Other - Hazardous category D",
    95: "Other - Reserved",
    96: "Other - Reserved",
    97: "Other - Reserved",
    98: "Other - Reserved",
    99: "Other - No additional information"
}

async def listen(navi_dict):
    print("✅ AIS listener avviato")

    async with websockets.connect("wss://stream.aisstream.io/v0/stream") as ws:
        await ws.send(json.dumps({
            "APIKey": "7d33927681ad1d125df5a6f75e0a90b7572aeb89",
            "BoundingBoxes": [[[45.2, 12.0], [46.0, 14.0]]],
            "FilterMessageTypes": ["PositionReport", "StaticDataReport"]
        }))

        async for message in ws:
            data = json.loads(message)

            if data["MessageType"] == "PositionReport":
                msg = data["Message"]["PositionReport"]
                mmsi = msg["UserID"]
                lat = msg["Latitude"]
                lon = msg["Longitude"]

                if mmsi in navi_dict:
                    navi_dict[mmsi]["lat"] = lat
                    navi_dict[mmsi]["lon"] = lon
                else:
                    navi_dict[mmsi] = {
                        "mmsi": mmsi,
                        "lat": lat,
                        "lon": lon,
                        "name": "N/A",
                        "type": "Unknown"
                    }

            elif data["MessageType"] == "StaticDataReport":
                msg = data["Message"]["StaticDataReport"]
                mmsi = msg.get("UserID")
                print("📦 StaticDataReport ricevuto:", msg)

                name = msg.get("ReportA", {}).get("Name", "").strip()
                ship_type_code = msg.get("ReportB", {}).get("ShipType")
                ship_type = ship_type_dict.get(ship_type_code, f"Type {ship_type_code}") if ship_type_code is not None else "Unknown"

                if not name:
                    name = "N/A"
                if not ship_type:
                    ship_type = "Unknown"

                if mmsi in navi_dict:
                    navi_dict[mmsi]["name"] = name
                    navi_dict[mmsi]["type"] = ship_type
                else:
                    navi_dict[mmsi] = {
                        "mmsi": mmsi,
                        "lat": None,
                        "lon": None,
                        "name": name,
                        "type": ship_type
                    }

def start_ais_listener(navi_dict):
    asyncio.run(listen(navi_dict))
