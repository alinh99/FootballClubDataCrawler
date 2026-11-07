#!/usr/bin/env python3
"""
geocode_cities.py - Get latitude/longitude for all cities from england_city.csv

Uses a predefined dictionary of UK city coordinates (no network needed).
Saves results to output/city_coordinates.csv for reuse.
"""

import os
import pandas as pd

INPUT_FILE = "output/england_city.csv"
OUTPUT_FILE = "output/city_coordinates.csv"
CITY_COLUMN = "name"

os.makedirs("output", exist_ok=True)

# Predefined coordinates for UK cities (exact names from england_city.csv)
CITY_COORDS = {
    "Bath": {"lat": 51.3758, "lon": -2.3599},
    "Birmingham": {"lat": 52.4862, "lon": -1.8904},
    "Bradford": {"lat": 53.7959, "lon": -1.7594},
    "Brighton & Hove": {"lat": 50.8225, "lon": -0.1372},
    "Bristol": {"lat": 51.4545, "lon": -2.5879},
    "Cambridge": {"lat": 52.2053, "lon": 0.1218},
    "Canterbury": {"lat": 51.2787, "lon": 1.0779},
    "Carlisle": {"lat": 54.8925, "lon": -2.9335},
    "Chelmsford": {"lat": 51.7356, "lon": 0.4685},
    "Chester": {"lat": 53.1934, "lon": -2.8931},
    "Chichester": {"lat": 50.8376, "lon": -0.7749},
    "Colchester": {"lat": 51.8959, "lon": 0.8919},
    "Coventry": {"lat": 52.4068, "lon": -1.5197},
    "Derby": {"lat": 52.9225, "lon": -1.4746},
    "Doncaster": {"lat": 53.5228, "lon": -1.1285},
    "Durham": {"lat": 54.7753, "lon": -1.5849},
    "Ely": {"lat": 52.3989, "lon": 0.2636},
    "Exeter": {"lat": 50.7184, "lon": -3.5339},
    "Gloucester": {"lat": 51.8642, "lon": -2.2382},
    "Hereford": {"lat": 52.0564, "lon": -2.7160},
    "Kingston-upon-Hull": {"lat": 53.7457, "lon": -0.3367},
    "Lancaster": {"lat": 54.0466, "lon": -2.8007},
    "Leeds": {"lat": 53.8008, "lon": -1.5491},
    "Leicester": {"lat": 52.6369, "lon": -1.1398},
    "Lichfield": {"lat": 52.6850, "lon": -1.8260},
    "Lincoln": {"lat": 53.2307, "lon": -0.5406},
    "Liverpool": {"lat": 53.4084, "lon": -2.9916},
    "London": {"lat": 51.5074, "lon": -0.1278},
    "Manchester": {"lat": 53.4808, "lon": -2.2426},
    "Milton Keynes": {"lat": 52.0406, "lon": -0.7594},
    "Newcastle-upon-Tyne": {"lat": 54.9783, "lon": -1.6178},
    "Norwich": {"lat": 52.6309, "lon": 1.2974},
    "Nottingham": {"lat": 52.9548, "lon": -1.1581},
    "Oxford": {"lat": 51.7520, "lon": -1.2577},
    "Peterborough": {"lat": 52.5695, "lon": -0.2405},
    "Plymouth": {"lat": 50.3755, "lon": -4.1427},
    "Portsmouth": {"lat": 50.8198, "lon": -1.0880},
    "Preston": {"lat": 53.7632, "lon": -2.7031},
    "Ripon": {"lat": 54.1370, "lon": -1.5219},
    "Salford": {"lat": 53.4875, "lon": -2.2901},
    "Salisbury": {"lat": 51.0698, "lon": -1.7951},
    "Sheffield": {"lat": 53.3811, "lon": -1.4701},
    "Southampton": {"lat": 50.9097, "lon": -1.4044},
    "Southend-on-Sea": {"lat": 51.5378, "lon": 0.7143},
    "St Albans": {"lat": 51.7527, "lon": -0.3394},
    "Stoke on Trent": {"lat": 53.0027, "lon": -2.1794},
    "Sunderland": {"lat": 54.9069, "lon": -1.3838},
    "Truro": {"lat": 50.2661, "lon": -5.0520},
    "Wakefield": {"lat": 53.6833, "lon": -1.4977},
    "Wells": {"lat": 51.2101, "lon": -2.6448},
    "Westminster": {"lat": 51.4994, "lon": -0.1348},
    "Winchester": {"lat": 51.0632, "lon": -1.3086},
    "Wolverhampton": {"lat": 52.5862, "lon": -2.1275},
    "Worcester": {"lat": 52.1912, "lon": -2.2219},
    "York": {"lat": 53.9614, "lon": -1.0776},
}

# Default fallback (London center)
DEFAULT_COORDS = {"lat": 51.5074, "lon": -0.1278}


def load_cities(path=INPUT_FILE, column=CITY_COLUMN):
    df = pd.read_csv(path)
    cities = sorted(df[column].dropna().unique().tolist())
    return cities


def load_existing_coords(path=OUTPUT_FILE):
    """Load already geocoded cities"""
    if not os.path.exists(path):
        return {}
    df = pd.read_csv(path)
    coords = {}
    for _, row in df.iterrows():
        coords[row["city"]] = {"lat": row["latitude"], "lon": row["longitude"]}
    return coords


def save_coords(coords, path=OUTPUT_FILE):
    """Save coordinates to CSV"""
    rows = [{"city": city, "latitude": v["lat"], "longitude": v["lon"]} for city, v in coords.items()]
    df = pd.DataFrame(rows)
    df.to_csv(path, index=False)


def main():
    print("=" * 60)
    print("CITY GEOCODER - Get lat/lon for all cities (offline)")
    print("=" * 60)

    # Load cities
    cities = load_cities()
    print(f"Total cities: {len(cities)}")

    # Load existing coordinates
    existing = load_existing_coords()
    print(f"Already geocoded: {len(existing)}")

    # Build coordinates for all cities
    all_coords = {}
    for city in cities:
        if city in CITY_COORDS:
            all_coords[city] = CITY_COORDS[city]
        elif city in existing:
            all_coords[city] = existing[city]
        else:
            # Try partial match
            matched = False
            for known_city, coords in CITY_COORDS.items():
                if known_city.lower() in city.lower() or city.lower() in known_city.lower():
                    all_coords[city] = coords
                    print(f"  Matched '{city}' -> '{known_city}'")
                    matched = True
                    break
            if not matched:
                all_coords[city] = DEFAULT_COORDS
                print(f"  Using default for: {city}")

    # Save
    save_coords(all_coords)
    print(f"\nOK Saved {len(all_coords)} city coordinates to {OUTPUT_FILE}")

    # Print summary
    print("\nCoordinates:")
    for city, coords in sorted(all_coords.items()):
        print(f"  {city}: {coords['lat']:.4f}, {coords['lon']:.4f}")


if __name__ == "__main__":
    main()