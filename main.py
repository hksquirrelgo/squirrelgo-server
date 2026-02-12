import os
import time
import random
import math
import threading
from datetime import datetime, timedelta, timezone
from flask import Flask
from supabase import create_client, Client
from dotenv import load_dotenv

# --- INITIALIZATION ---
load_dotenv()
app = Flask(__name__)

# Credentials (Set these in Azure Environment Variables)
SUPABASE_URL = os.getenv("SUPABASE_URL")
SERVICE_ROLE_KEY = os.getenv("SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SERVICE_ROLE_KEY:
    print("[CRITICAL] Missing SUPABASE_URL or SERVICE_ROLE_KEY")
    # Don't exit here so the web server can at least show an error page
else:
    supabase: Client = create_client(SUPABASE_URL, SERVICE_ROLE_KEY)

# --- CONFIGURATION ---
SEARCH_RADIUS_KM = 0.3
MAX_SQUIRRELS = 10
MIN_SPAWN_MINUTES = 5
MAX_SPAWN_MINUTES = 30
STAGGER_WINDOW_SECONDS = 60  
LOOP_INTERVAL_SECONDS = 30  
UTC_PLUS_8 = timezone(timedelta(hours=8))

RARITY_WEIGHTS = {
    'Legendary': 1, 'Mythic': 2, 'Epic': 3, 
    'Rare': 4, 'Uncommon': 6, 'Common': 8
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
    'Rainforest': ['black-giant-squirrel', 'prevosts-squirrel', 'red-tailed-squirrel', 'least-pygmy-squirrel', 'tufted-ground-squirrel', 'plantain-squirrel'],
    'Taiga': ['arctic-ground-squirrel', 'douglas-squirrel', 'northern-flying-squirrel'],
    'Forest': ['black-giant-squirrel', 'douglas-squirrel', 'aberts-squirrel', 'humboldts-flying-squirrel', 'variegated-squirrel', 'least-chipmunk', 'gray-squirrel', 'fox-squirrel', 'pallass-squirrel'],
    'Desert': ['harriss-antelope-squirrel', 'rock-squirrel', 'long-clawed-ground-squirrel'],
    'Grassland': ['harriss-antelope-squirrel', 'spotted-ground-squirrel', 'richardsons-ground-squirrel', 'golden-mantled-ground-squirrel', 'thirteen-lined-ground-squirrel', 'bobak-marmot'],
    'Urban': ['thirteen-lined-ground-squirrel', 'least-chipmunk', 'gray-squirrel', 'fox-squirrel', 'pallass-squirrel', 'plantain-squirrel']
}

# --- LOGIC FUNCTIONS ---

def get_random_coordinate_nearby(lat, lon, radius_km):
    radius_deg = radius_km / 111.0  
    u, v = random.random(), random.random()
    w = radius_deg * math.sqrt(u)
    t = 2 * math.pi * v
    new_lon = (w * math.cos(t)) / math.cos(math.radians(lat)) + lon
    new_lat = (w * math.sin(t)) + lat
    return new_lat, new_lon

def parse_location(geom_data):
    if not geom_data: return None
    try:
        if isinstance(geom_data, dict) and 'coordinates' in geom_data:
            return geom_data['coordinates'][1], geom_data['coordinates'][0] 
        if isinstance(geom_data, str) and geom_data.startswith("POINT"):
            raw = geom_data.replace("POINT(", "").replace(")", "").split()
            return float(raw[1]), float(raw[0])
        return None
    except: return None

def cleanup_expired_spawns():
    now_utc = datetime.now(timezone.utc).isoformat()
    try:
        supabase.table('spawns').delete().lt('despawned_at', now_utc).execute()
    except Exception as e:
        print(f"[ERROR] Cleanup: {e}")

def spawn_cycle():
    cleanup_expired_spawns()
    now_local = datetime.now(UTC_PLUS_8)
    five_mins_ago = (now_local - timedelta(minutes=5)).isoformat()
    
    try:
        players = supabase.table('players').select("*").gt('updated_at', five_mins_ago).execute().data
        if not players: return
        
        for player in players:
            coords = parse_location(player['location'])
            if not coords: continue
            p_lat, p_lon = coords
            
            # Check population
            count = supabase.rpc('count_active_spawns_nearby', {'lat': p_lat, 'lon': p_lon, 'radius_meters': SEARCH_RADIUS_KM * 1000}).execute().data
            if count >= MAX_SQUIRRELS: continue
            
            # Determine Biome
            detected_biome = 'Urban'
            try:
                biome_res = supabase.rpc('get_biome_at_point', {'lat': p_lat, 'lon': p_lon}).execute()
                if biome_res.data in BIOME_SPECIES_MAP: detected_biome = biome_res.data
            except: pass
            
            # Spawn Logic
            species_pool = BIOME_SPECIES_MAP[detected_biome]
            weights = [RARITY_WEIGHTS.get(SPECIES_METADATA.get(s, {}).get('rarity', 'Common'), 8) for s in species_pool]
            
            num_to_spawn = random.randint(1, min(5, MAX_SQUIRRELS - count))
            payload = []
            for _ in range(num_to_spawn):
                lat, lon = get_random_coordinate_nearby(p_lat, p_lon, SEARCH_RADIUS_KM)
                species = random.choices(species_pool, weights=weights, k=1)[0]
                duration = random.randint(MIN_SPAWN_MINUTES, MAX_SPAWN_MINUTES)
                start = datetime.now(UTC_PLUS_8) + timedelta(seconds=random.randint(-60, 60))
                payload.append({
                    "species": species,
                    "location": f"POINT({lon} {lat})",
                    "spawned_at": start.isoformat(),
                    "despawned_at": (start + timedelta(minutes=duration)).isoformat(),
                    "biome_type": detected_biome,
                    "rarity": SPECIES_METADATA.get(species, {}).get('rarity', 'Common')
                })
            supabase.table('spawns').insert(payload).execute()
    except Exception as e:
        print(f"[ERROR] Cycle Failed: {e}")

# --- WEB & THREAD MANAGEMENT ---

def background_loop():
    print("Background loop started.")
    while True:
        try:
            spawn_cycle()
        except Exception as e:
            print(f"Loop Error: {e}")
        time.sleep(LOOP_INTERVAL_SECONDS)

# Flask route for Azure Health Checks
@app.route('/')
def health():
    return f"Squirrel Spawner is Online. Last Check: {datetime.now(UTC_PLUS_8)}", 200

# This ensures the thread only starts once when Azure runs the app
if not app.debug or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
    thread = threading.Thread(target=background_loop, daemon=True)
    thread.start()

if __name__ == "__main__":
    # Local development run
    port = int(os.environ.get("PORT", 8000))
    app.run(host='0.0.0.0', port=port)
