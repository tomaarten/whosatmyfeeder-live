import sys
import os
import yaml
import json
import sqlite3
import numpy as np
from PIL import Image, ImageOps
from io import BytesIO
from datetime import datetime
import requests
#import paho.mqtt.client as mqtt
from paho.mqtt import client as mqtt_client
from paho.mqtt.client import CallbackAPIVersion
from tflite_support.task import core, processor, vision
from queries import get_common_name
import multiprocessing
import time
#import cv2
import hashlib
from webui import app
import logging
import tflite_runtime.interpreter as tflite

# Globals
session = requests.Session()
DBPATH = './data/speciesid.db'

# Load config + auth + TFLite model
cfg_full = yaml.safe_load(open('config/config.yml'))
frig_cfg = cfg_full['frigate']
base_url = f"http://{frig_cfg['frigate_url']}"
if frig_cfg.get('api_key'):
    session.headers.update({'X-API-Key': frig_cfg['api_key']})
elif frig_cfg.get('bearer_token'):
    session.headers.update({'Authorization': f"Bearer {frig_cfg['bearer_token']}"})
elif frig_cfg.get('username') and frig_cfg.get('password'):
    r = session.post(f"{base_url}/api/login", json={
        'user': frig_cfg['username'], 'password': frig_cfg['password']
    })
    if r.ok and 'access_token' in r.json():
        session.headers.update({'Authorization': f"Bearer {r.json()['access_token']}"})
    else:
        session.auth = (frig_cfg['username'], frig_cfg['password'])
MODEL_PATH = cfg_full['classification']['model']
LABEL_PATH = cfg_full['classification']['labels']


# Load TFLite model & labels
model_path = cfg_full['classification']['model']
label_path = cfg_full['classification']['labels']
#base_opts = core.BaseOptions(file_name=model_path, num_threads=4)
#cls_opts = processor.ClassificationOptions(
#    max_results=5,
#    score_threshold=cfg_full['classification']['threshold']
#)
#vision_opts = vision.ImageClassifierOptions(
#    base_options=base_opts,
#    classification_options=cls_opts
#)
#classifier = vision.ImageClassifier.create_from_options(vision_opts)
#print(f"Loaded TFLite model: {model_path}, top‑k = {cls_opts.max_results}", flush=True)


# New filter import code
BASE_DIR = os.path.dirname(__file__)                           # directory of speciesid.py :contentReference[oaicite:0]{index=0}
whitelist_path = os.path.join(BASE_DIR, 'config', 'northeast_birds.txt')
try:
    with open(whitelist_path, 'r') as f:
        allowed = {line.strip().lower() for line in f if line.strip() and not line.strip().startswith('#')}
    print(f"Loaded {len(allowed)} allowed species: {sorted(allowed)}")
except FileNotFoundError:
    print(f"Whitelist file not found: {whitelist_path}")
    allowed = set()


# Logging setup
logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        stream=sys.stdout
)
logger = logging.getLogger(__name__)

# mapping scientific to common
#BASE_DIR = os.path.dirname(__file__)
BIRDNAMES_PATH = os.path.join(BASE_DIR, 'birdnames.db')

def get_common_name(scientific_name: str) -> str:
    """
    Look up the common name for a given scientific_name in birdnames.db.
    Assumes birdnames.db has a table named 'birdnames' with columns:
      - scientific_name TEXT PRIMARY KEY
      - common_name     TEXT
    Returns the common name if found, otherwise returns the original scientific_name.
    """
    try:
        conn = sqlite3.connect(BIRDNAMES_PATH)
        cursor = conn.cursor()
        # Parameterized query to avoid SQL injection (PEP 249) :contentReference[oaicite:0]{index=0}
        cursor.execute(
            "SELECT common_name FROM birdnames WHERE scientific_name = ?",
            (scientific_name,)
        )
        row = cursor.fetchone()  # fetchone() returns one tuple or None :contentReference[oaicite:1]{index=1}
        conn.close()
        if row:
            return row[0]
    except sqlite3.Error as e:
        # Log or print the error in real code; here we silently fall back
        print(f"Warning: failed to lookup common name for {scientific_name}: {e}")
    return scientific_name

def classify_top5_via_interpreter(pil_img: Image.Image):
    # 1. Crop / resize / pad exactly as in speciesid.py
    #img = pil_img.copy()
    #img.thumbnail((224, 224))
    #pad = ImageOps.expand(
    #    img,
    #    border=((224 - img.width)  // 2, (224 - img.height) // 2),
    #    fill='black'
    #)
    #arr = np.array(pad)
    
    arr = np.array(pil_img)

    with open(LABEL_PATH) as f:
        labels = [line.strip() for line in f]

    # Ensure interpreter is ready
    interpreter.allocate_tensors()

    # Fetch details here, in the function’s scope
    input_details  = interpreter.get_input_details()
    output_details = interpreter.get_output_details()

    # 2. Prepare input tensor
    tensor = np.expand_dims(arr, axis=0).astype(input_details[0]['dtype'])
    interpreter.set_tensor(input_details[0]['index'], tensor)

    # 3. Run inference
    interpreter.invoke()

    # 4. Retrieve and dequantize output
    raw_output = interpreter.get_tensor(output_details[0]['index'])  # shape: [1, 965]
    scale, zero_point = output_details[0]['quantization']
    probs = scale * (raw_output.astype(np.float32) - zero_point)    # dequantize :contentReference[oaicite:6]{index=6}
    probs = np.squeeze(probs)  # shape: (965,)

    # 5. Get top-5 indices
    #    Argsort returns indices that would sort the array ascending.
    idx_sorted = np.argsort(probs)                              # :contentReference[oaicite:7]{index=7}
    top5_idx   = idx_sorted[-5:][::-1]                          # last 5 reversed for descending :contentReference[oaicite:8]{index=8}

    # 6. Map to (label, score)
    top5 = [(labels[i], float(probs[i])) for i in top5_idx]     # label file from step 2 :contentReference[oaicite:9]{index=9}
    return top5

# MQTT callbacks & DB setup
def on_connect(client, userdata, flags, rc):
    print("MQTT Connected", flush=True)

    # we are going subscribe to frigate/events and look for bird detections there
    client.subscribe(f"{cfg_full['frigate']['main_topic']}/events/#")


def on_disconnect(client, userdata, rc):
    if rc != 0:
        print("Unexpected disconnection, trying to reconnect", flush=True)
        while True:
            try:
                client.reconnect()
                break
            except Exception as e:
                print(f"Reconnection failed due to {e}, retrying in 60 seconds", flush=True)
                time.sleep(60)
    else:
        print("Expected disconnection", flush=True)

def setupdb():
    conn = sqlite3.connect(DBPATH)
    cursor = conn.cursor()
    cursor.execute("""    
        CREATE TABLE IF NOT EXISTS detections (    
            id INTEGER PRIMARY KEY AUTOINCREMENT,  
            detection_time TIMESTAMP NOT NULL,  
            detection_index INTEGER NOT NULL,  
            score REAL NOT NULL,  
            display_name TEXT NOT NULL,  
            category_name TEXT NOT NULL,  
            frigate_event TEXT NOT NULL UNIQUE,
            camera_name TEXT NOT NULL,
            user_label TEXT NOT NULL DEFAULT '',
            reviewed INTEGER NOT NULL DEFAULT 0
        )    
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS detection_choices (
            event_id TEXT,
            rank INTEGER,
            display_name TEXT,
            score REAL,
            PRIMARY KEY(event_id, rank)
        )
    """)

    conn.commit()

    conn.close()

def on_message(client, userdata, message):
    #print("on message triggered")
    logger.debug("on_message ENTER topic=%s qos=%s", message.topic, message.qos)
    
    payload = json.loads(message.payload)
    #logger.debug("Decoded payload: %s", payload)
    
    if payload.get("type") != "update":
        logger.info("Skipping because type=%r", payload.get("type"))
        return # ignore 'new' and 'end' because they don't actually have snapshots
    after = payload.get('after', {})
    if after.get('label') != 'bird':
        logger.info("Skipping beceuase not bird")
        return
    has_snapshot = after.get("has_snapshot", False)
    if not has_snapshot:
        logger.info("Skipping because has_snapshot=%s", has_snapshot)

    full_id = after['id']
    event_id = full_id.split('-')[0]
    camera = after.get('camera')

    # Build snapshot URL per camera
    
    snapshot_path = f"/api/{camera}/recordings/{event_id}/snapshot.jpg"
    r = session.get(f"{base_url}{snapshot_path}", stream=True)
    logger.debug("Fetched snapshot URL=%s -> status=%d", snapshot_path, r.status_code)

    if not r.ok:
        #print(f"Snapshot error {r.status_code}", flush=True)
        logger.warning("Snapshot fetch failed: %s %s", r.status_code, r.text[:200]) 
        return
    
    img = Image.open(BytesIO(r.content))
    x1, y1, x2, y2 = after['snapshot']['box']
    ROI = img.crop((x1,y1,x2,y2))
    ROI.thumbnail((224,224))
#    pad = ImageOps.expand(
#        ROI,
#        border=((224-ROI.width)//2, (224-ROI.height)//2),
#        fill='black'
#    )
    
    w, h = ROI.size
    pad_left   = (224 - w) // 2
    pad_right  = 224 - w - pad_left
    pad_top    = (224 - h) // 2
    pad_bottom = 224 - h - pad_top

    pad = ImageOps.expand(
        ROI,
        border=(pad_left, pad_top, pad_right, pad_bottom),
        fill='black'
    )

    arr = np.array(pad)
    tensor_img = vision.TensorImage.create_from_array(arr)

    start = datetime.fromtimestamp(after['start_time'])
    ts = start.strftime('%Y-%m-%d %H:%M:%S')

    # Classification & DB logic as before...
    result = classifier.classify(tensor_img)
    logger.debug("Classifier result: %s", result)

    categories = result.classifications[0].categories
    if not categories:
        #print("no categories")
        logger.info("No categories returned by classifier")
        return
    
    print("Length of classifications   ")
    print(len(result.classifications))
    print("Length of classifications[0].categories:   ")
    print(len(result.classifications[0].categories))

    # prints out candidates to terminal
    for cat in result.classifications[0].categories:
        name = cat.display_name or "<None>"
        low = name.lower()
        is_allowed = (low in allowed)
        print(f"  » '{name}' → lowercase '{low}' → in allowed? {is_allowed}")
    
    for cat in result.classifications[0].categories:
        sci = cat.display_name
        common = get_common_name(sci)
        logger.debug("Category %r maps to common name %r", sci, common)


    filtered = [
            cat for cat in result.classifications[0].categories
            if cat.display_name not in (None, "__background__") and get_common_name(cat.display_name).lower() in allowed
    ]

    if not filtered:
        logger.info("All candidates were filtered out")
        return

    best_cat = filtered[0]
    display_name = best_cat.display_name
    score = best_cat.score
    index = best_cat.index
    display_name = best_cat.display_name
    category_name = best_cat.category_name
    common_name = get_common_name(best_cat.display_name)
    logger.debug("Best candidate: %s", best_cat.display_name)

    #top5 = sorted(filtered, key=lambda c: c.score, reverse=True)[:5]
    top5 = classify_top5_via_interpreter(pad)

    if score < cfg_full['classification']['threshold']:
        #print("Insufficient score")
        logger.info("Top category has insufficient score")
        return

    if display_name != "__background__":
        conn = sqlite3.connect(DBPATH, timeout=30)
        cursor = conn.cursor()

        #Check if a record with the given event exists
        cursor.execute("SELECT * FROM detections WHERE frigate_event = ?", (full_id,))
        result = cursor.fetchone()

        if result is None:
	     # Insert a new record if it doesn't exist
             print("No record yet for this event. Storing.", flush=True)
             cursor.execute("""  
             INSERT OR REPLACE INTO detections (detection_time, detection_index, score,  
             display_name, category_name, frigate_event, camera_name) VALUES (?, ?, ?, ?, ?, ?, ?)  
             """, (ts, index, score, common_name, category_name, full_id, camera))
            
             for rank, (display_name, score) in enumerate(top5, start=1):
                 common = get_common_name(display_name)
                 cursor.execute("""
                 INSERT INTO detection_choices(event_id, rank, display_name, score)
                 VALUES (?, ?, ?, ?)
                 ON CONFLICT(event_id, rank) DO UPDATE
                     SET display_name=excluded.display_name,
                         score=excluded.score
                 """, (full_id, rank, common, score))
            
        else:
            print("There is already a record for this event. Checking score", flush=True)
            # Update the existing record if the new score is higher
            existing_score = result[3]
            if score > existing_score:
                print("New score is higher. Updating record with higher score.", flush=True)
                cursor.execute("""  
                  UPDATE detections  
                  SET detection_time = ?, detection_index = ?, score = ?, display_name = ?, category_name = ?  
                  WHERE frigate_event = ?  
                  """, (ts, index, score, common_name, category_name, full_id))
            else:
                print("New score is lower.", flush=True)

        # Commit the changes
        conn.commit()


    # Example sub_label push using recordings endpoint
    sub_json = {"subLabel": display_name[:20]}
    session.post(
        f"{base_url}/api/{camera}/recordings/{event_id}/sub_label",
        json=sub_json
    )

    conn.close()
    
    logger.debug("on_message fully processed event %s", full_id)

def run_mqtt_client():
    load_config()
    print("Starting MQTT client. Connecting to: " + config['frigate']['mqtt_server'], flush=True)
    now = datetime.now()
    current_time = now.strftime("%Y%m%d%H%M%S")
    #client = mqtt.Client("birdspeciesid" + current_time)
    client = mqtt_client.Client(
      CallbackAPIVersion.VERSION1,          # use the legacy callback API
      client_id="birdspeciesid" + current_time)
    client.reconnect_delay_set(min_delay=1,max_delay=60)
    
    print("client created")

    client.subscribe("frigate/events/#")
    print("explicit subscription")
    
    client.on_message = on_message
    client.on_disconnect = on_disconnect
    client.on_connect = on_connect
    # check if we are using authentication and set username/password if so
    if config['frigate']['mqtt_auth']:
        username = config['frigate']['mqtt_username']
        password = config['frigate']['mqtt_password']
        #print(username + "   " + password)
        client.username_pw_set(username, password)

    #client.enable_logger()

    client.connect(config['frigate']['mqtt_server'])
    client.loop_forever()

def load_config():
    global config
    file_path = './config/config.yml'
    with open(file_path, 'r') as config_file:
        config = yaml.safe_load(config_file)

def run_webui():
    print("Starting flask app", flush=True)
    app.run(debug=False, host=config['webui']['host'], port=config['webui']['port'])

def main():

    now = datetime.now()
    current_time = now.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]

    print("Time: " + current_time, flush=True)
    print("Python version", flush=True)
    print(sys.version, flush=True)
    print("Version info.", flush=True)
    print(sys.version_info, flush=True)

    load_config()

    # Initialize the image classification model
    base_options = core.BaseOptions(
        file_name=config['classification']['model'], use_coral=False, num_threads=4)

    # Enable Coral by this setting
    classification_options = processor.ClassificationOptions(
        max_results=5, score_threshold=config['classification']['threshold'])
    options = vision.ImageClassifierOptions(
        base_options=base_options, classification_options=classification_options)

    # create classifier
    global classifier
    classifier = vision.ImageClassifier.create_from_options(options)

    # Instantiate and allocate
    global interpreter
    interpreter = tflite.Interpreter(model_path=MODEL_PATH)  
    interpreter.allocate_tensors()  
    input_details  = interpreter.get_input_details()  
    output_details = interpreter.get_output_details()  

    # setup database
    setupdb()

    print("Starting threads for Flask and MQTT", flush=True)
    flask_process = multiprocessing.Process(target=run_webui)
    mqtt_process = multiprocessing.Process(target=run_mqtt_client)

    flask_process.start()
    mqtt_process.start()

    flask_process.join()
    mqtt_process.join()

    print("main completed")

if __name__ == '__main__':
    print("Calling Main", flush=True)
    main()





