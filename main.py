import os
import time  
import random
import math
import json
from datetime import datetime, timedelta, timezone
from supabase import create_client, Client
from dotenv import load_dotenv
import threading
from flask import Flask
app = Flask(__name__)
@app.route('/')
def home():
    return "Squirrel Server is Online!", 200
def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SERVICE_ROLE_KEY = os.getenv("SERVICE_ROLE_KEY")
if not SUPABASE_URL or not SERVICE_ROLE_KEY:
    print("[CRITICAL] Missing SUPABASE_URL or SERVICE_ROLE_KEY")
    exit(1)
supabase: Client = create_client(SUPABASE_URL, SERVICE_ROLE_KEY)
SEARCH_RADIUS_KM = 0.3
MAX_SQUIRRELS = 10
MIN_SPAWN_MINUTES = 5
MAX_SPAWN_MINUTES = 30
STAGGER_WINDOW_SECONDS = 60  
LOOP_INTERVAL_SECONDS = 30  
UTC_PLUS_8 = timezone(timedelta(hours=8))
RARITY_WEIGHTS = {
    'Legendary': 1,
    'Mythic': 2,
    'Epic': 3,
    'Rare': 4,
    'Uncommon': 6,
    'Common': 8
}
SPECIES_METADATA = {
    'aberts-squirrel': {'rarity': 'Epic'},
    'arctic-ground-squirrel': {'rarity': 'Rare'},
    'black-giant-squirrel': {'rarity': 'Rare'},
    'bobak-marmot': {'rarity': 'Mythic'},
    'douglas-squirrel': {'rarity': 'Rare'},
    'fox-squirrel': {'rarity': 'Uncommon'},
    'golden-mantled-ground-squirrel': {'rarity': 'Rare'},
    'gray-squirrel': {'rarity': 'Common'},
    'harriss-antelope-squirrel': {'rarity': 'Uncommon'},
    'humboldts-flying-squirrel': {'rarity': 'Common'},
    'least-chipmunk': {'rarity': 'Common'},
    'least-pygmy-squirrel': {'rarity': 'Epic'},
    'long-clawed-ground-squirrel': {'rarity': 'Mythic'},
    'northern-flying-squirrel': {'rarity': 'Uncommon'},
    'pallass-squirrel': {'rarity': 'Legendary'},
    'plantain-squirrel': {'rarity': 'Common'},
    'prevosts-squirrel': {'rarity': 'Uncommon'},
    'red-tailed-squirrel': {'rarity': 'Common'},
    'richardsons-ground-squirrel': {'rarity': 'Uncommon'},
    'rock-squirrel': {'rarity': 'Common'},
    'spotted-ground-squirrel': {'rarity': 'Common'},
    'thirteen-lined-ground-squirrel': {'rarity': 'Uncommon'},
    'tufted-ground-squirrel': {'rarity': 'Epic'},
    'variegated-squirrel': {'rarity': 'Common'}
}
BIOME_SPECIES_MAP = {
    'Rainforest': [
        'black-giant-squirrel', 'prevosts-squirrel', 'red-tailed-squirrel',
        'least-pygmy-squirrel', 'tufted-ground-squirrel', 'plantain-squirrel'
    ],
    'Taiga': [
        'arctic-ground-squirrel', 'douglas-squirrel', 'northern-flying-squirrel'
    ],
    'Forest': [
        'black-giant-squirrel', 'douglas-squirrel', 'aberts-squirrel',
        'humboldts-flying-squirrel', 'variegated-squirrel', 'least-chipmunk',
        'gray-squirrel', 'fox-squirrel', 'pallass-squirrel'
    ],
    'Desert': [
        'harriss-antelope-squirrel', 'rock-squirrel', 'long-clawed-ground-squirrel'
    ],
    'Grassland': [
        'harriss-antelope-squirrel', 'spotted-ground-squirrel',
        'richardsons-ground-squirrel', 'golden-mantled-ground-squirrel',
        'thirteen-lined-ground-squirrel', 'bobak-marmot'
    ],
    'Urban': [
        'thirteen-lined-ground-squirrel', 'least-chipmunk', 'gray-squirrel',
        'fox-squirrel', 'pallass-squirrel', 'plantain-squirrel'
    ]
}
def get_random_coordinate_nearby(lat, lon, radius_km):
    radius_deg = radius_km / 111.0  
    u = random.random()
    v = random.random()
    w = radius_deg * math.sqrt(u)
    t = 2 * math.pi * v
    x = w * math.cos(t)
    y = w * math.sin(t)
    new_lon = x / math.cos(math.radians(lat)) + lon
    new_lat = y + lat
    return new_lat, new_lon
def parse_location(geom_data):
    if not geom_data: return None
    try:
        if isinstance(geom_data, dict) and 'coordinates' in geom_data:
            return geom_data['coordinates'][1], geom_data['coordinates'][0] 
        if isinstance(geom_data, str) and geom_data.startswith("POINT"):
            raw_nums = geom_data.replace("POINT(", "").replace(")", "").split()
            return float(raw_nums[1]), float(raw_nums[0])
        return None
    except Exception as e:
        print(f"[ERROR] Parsing location: {e}")
        return None
def cleanup_expired_spawns():
    now_utc = datetime.now(timezone.utc).isoformat()
    try:
        response = supabase.table('spawns').delete().lt('despawned_at', now_utc).execute()
        if response.data:
            print(f"[CLEANUP] Removed {len(response.data)} expired squirrels.")
    except Exception as e:
        print(f"[ERROR] Cleanup failed: {e}")
def spawn_cycle():
    cleanup_expired_spawns()
    now_local = datetime.now(UTC_PLUS_8)
    print(f"\n--- 🚀 Running Staggered Spawner at {now_local.isoformat()} (UTC+8) ---")
    five_mins_ago = (now_local - timedelta(minutes=5)).isoformat()
    try:
        response = supabase.table('players').select("*").gt('updated_at', five_mins_ago).execute()
        online_players = response.data
    except Exception as e:
        print(f"[ERROR] Fetching players: {e}")
        return
    if not online_players:
        print("[INFO] No active players found nearby.")
        return
    print(f"[INFO] Found {len(online_players)} online players.")
    for player in online_players:
        player_id = player['id']
        coords = parse_location(player['location'])
        if not coords:
            continue
        p_lat, p_lon = coords
        try:
            count_res = supabase.rpc(
                'count_active_spawns_nearby', 
                {'lat': p_lat, 'lon': p_lon, 'radius_meters': SEARCH_RADIUS_KM * 1000}
            ).execute()
            current_count = count_res.data
        except Exception as e:
            print(f"[ERROR] RPC count_active_spawns_nearby failed: {e}")
            continue
        if current_count >= MAX_SQUIRRELS:
            print(f"[INFO] Player {player_id} area full ({current_count}/{MAX_SQUIRRELS}). Skipping.")
            continue
        space_left = MAX_SQUIRRELS - current_count
        num_to_spawn = random.randint(1, min(5, space_left)) 
        detected_biome = 'Urban' 
        try:
            biome_res = supabase.rpc('get_biome_at_point', {'lat': p_lat, 'lon': p_lon}).execute()
            if biome_res.data: 
                if biome_res.data in BIOME_SPECIES_MAP:
                    detected_biome = biome_res.data
                else:
                    print(f"[WARN] Biome '{biome_res.data}' found in DB but not in Config. Falling back to Urban.")
        except Exception as e: 
            print(f"[ERROR] Biome lookup failed, defaulting to Urban: {e}")
        species_pool = BIOME_SPECIES_MAP[detected_biome]
        weights = []
        for species in species_pool:
            rarity_label = SPECIES_METADATA.get(species, {}).get('rarity', 'Common')
            weight = RARITY_WEIGHTS.get(rarity_label, 8)
            weights.append(weight)
        print(f"[INFO] Player {player_id} is in '{detected_biome}'. Spawning {num_to_spawn}...")
        spawns_payload = []
        batch_reference_time = datetime.now(UTC_PLUS_8)
        for k in range(num_to_spawn):
            cand_lat, cand_lon = get_random_coordinate_nearby(p_lat, p_lon, SEARCH_RADIUS_KM)
            selected_species = random.choices(species_pool, weights=weights, k=1)[0]
            rarity = SPECIES_METADATA.get(selected_species, {}).get('rarity', 'Common')
            duration_mins = random.randint(MIN_SPAWN_MINUTES, MAX_SPAWN_MINUTES)
            random_offset_seconds = random.randint(-STAGGER_WINDOW_SECONDS, STAGGER_WINDOW_SECONDS)
            individual_spawn_time = batch_reference_time + timedelta(seconds=random_offset_seconds)
            individual_despawn_time = individual_spawn_time + timedelta(minutes=duration_mins)
            wkt_point = f"POINT({cand_lon} {cand_lat})"
            spawns_payload.append({
                "species": selected_species,
                "location": wkt_point,
                "spawned_at": individual_spawn_time.isoformat(),
                "despawned_at": individual_despawn_time.isoformat(),
                "biome_type": detected_biome,
                "rarity": rarity
            })
        if spawns_payload:
            try:
                data = supabase.table('spawns').insert(spawns_payload).execute()
                print(f"[SUCCESS] Inserted {len(data.data)} squirrels for {detected_biome}.")
            except Exception as e:
                print(f"[ERROR] Insert failed: {e}")
if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    print(f"[START] Starting Squirrel Spawner Service...")
    try:
        while True:
            spawn_cycle()
            time.sleep(30) 
    except KeyboardInterrupt:
        print("\n[STOP] Stopped.")
