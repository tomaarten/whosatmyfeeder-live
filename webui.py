import os
import yaml
import requests
from flask import Flask, render_template, send_file, send_from_directory, abort, current_app, g
from flask import jsonify, request, redirect, url_for
from datetime import datetime
from io import BytesIO
from queries import (
    recent_detections, get_daily_summary,
    get_common_name, get_records_for_date_hour,
    get_records_for_scientific_name_and_date,
    get_earliest_detection_date
)
from PIL import Image, UnidentifiedImageError
import sqlite3

app = Flask(__name__)
session = requests.Session()

# Load config and set up HTTP session/auth
cfg = yaml.safe_load(open('config/config.yml'))['frigate']
base_url = f"http://{cfg['frigate_url']}"
print("base url from web ui " + base_url)
if cfg.get('api_key'):
    session.headers.update({'X-API-Key': cfg['api_key']})
elif cfg.get('bearer_token'):
    session.headers.update({'Authorization': f"Bearer {cfg['bearer_token']}"})
elif cfg.get('username') and cfg.get('password'):
    r = session.post(f"{base_url}/api/login", json={
        'user': cfg['username'], 'password': cfg['password']
    })
    if r.ok and 'access_token' in r.json():
        session.headers.update({'Authorization': f"Bearer {r.json()['access_token']}"})
    else:
        session.auth = (cfg['username'], cfg['password'])

FRIGATE_API = cfg['frigate_url']
print("frigate api variable = " + FRIGATE_API)

# Helper to call Frigate API
# camera and event for recordings endpoints

def frigate_get(path, **kwargs):
    return session.get(f"{base_url}{path}", **kwargs)

# Path to your SQLite file (adjust as needed)
DATABASE = os.path.join(os.path.dirname(__file__), 'data', 'speciesid.db')
def get_db():
    """
    Get a SQLite database connection for the current Flask request.
    The connection is stored in 'g._database' so it’s reused on repeated calls.
    """
    db = getattr(g, '_database', None)
    if db is None:
        # detect_types if you want timestamp parsing etc.
        db = g._database = sqlite3.connect(
            DATABASE,
            detect_types=sqlite3.PARSE_DECLTYPES
        )
        # Return rows as dict-like objects: row['column_name']
        db.row_factory = sqlite3.Row
    return db

# Format filter
@app.template_filter('datetime')
def format_datetime(value, fmt='%B %d, %Y %H:%M:%S'):
    return datetime.fromisoformat(value).strftime(fmt)

def _fetch_and_stream(path, is_video=False):
    url = f"http://{FRIGATE_API}/api/{path}"
    print(url)

    r = session.get(url, stream=not is_video)
    # 1. Check HTTP status
    if r.status_code != 200:
        return send_from_directory('static', 'placeholder.png',
                                   mimetype='image/png')
    # 2. Validate MIME
    ctype = r.headers.get('Content-Type', '')
    if is_video:
        if not ctype.startswith('video/'):
            app.logger.error(f"Bad video Content-Type: {ctype}")
            abort(500)
        return send_file(BytesIO(r.content), mimetype=ctype,
                         as_attachment=False)
    if not ctype.startswith('image/'):
        app.logger.error(f"Bad image Content-Type: {ctype}")
        return send_from_directory('static', 'placeholder.png',
                                   mimetype='image/png')
    # 3. Verify image integrity
    buf = BytesIO(r.content)
    try:
        img = Image.open(buf)
        img.verify()
    except UnidentifiedImageError:
        app.logger.error("Invalid image data received")
        return send_from_directory('static', 'placeholder.png',
                                   mimetype='image/png')
    buf.seek(0)
    # 4. Stream to client
    return send_file(buf, mimetype=ctype, as_attachment=False)


@app.route('/')
def index():
    now = datetime.now()
    db = get_db()
    dets = recent_detections(5)

    for d in dets:
        event_id = d['frigate_event']
        rows = db.execute(
                "SELECT display_name, score FROM detection_choices WHERE event_id=? ORDER BY rank",
                (event_id,)
        ).fetchall()
    
        d['top5'] = [(row['display_name'], row['score']) for row in rows]
        
        ul = db.execute(
                "SELECT user_label FROM detections WHERE frigate_event = ?",
                (event_id,)
        ).fetchone()
        d['user_label'] = ul['user_label'] if ul and ul['user_label'] else None

    return render_template(
        'index.html',
        recent_detections=dets,
        daily_summary=get_daily_summary(now),
        current_hour=now.hour,
        date=now.strftime('%Y-%m-%d'),
        earliest_date=get_earliest_detection_date()
    )

@app.route('/frigate/<camera>/<full_id>/snapshot.jpg')
def frigate_snapshot(camera, full_id):
    # split to get event ID before dash
    #event_id = full_id.split('.')[0]
    #path = f"/api/{camera}/recordings/{full_id}/snapshot.jpg"
    #r = frigate_get(path, stream=True)
    #if r.ok:
    print(FRIGATE_API)
    return _fetch_and_stream(
    f"events/{full_id}/snapshot.jpg?crop=1&quality=95"
    )

    #return send_file(r.raw, mimetype=r.headers['Content-Type'])
    return send_from_directory('static/images', '1x1.png', mimetype='image/png')

@app.route('/frigate/<camera>/<full_id>/thumbnail.jpg')
def frigate_thumbnail(camera, full_id):
    #event_id = full_id.split('.')[0]
    #path = f"/api/{camera}/recordings/{full_id}/thumbnail.jpg"
    #r = frigate_get(path, stream=True)
    #if r.ok:
    
    print(FRIGATE_API)
    return _fetch_and_stream(f"events/{full_id}/thumbnail.jpg")
    
    #return send_file(r.raw, mimetype=r.headers['Content-Type'])
    return send_from_directory('static/images', '1x1.png', mimetype='image/png')

@app.route('/frigate/<camera>/<full_id>/clip.mp4')
def frigate_clip(camera, full_id):
    #event_id = full_id.split('.')[0]
    #path = f"/api/{camera}/recordings/{full_id}/clip.mp4"
    #r = frigate_get(path, stream=True)
    #if r.ok:
    return _fetch_and_stream(f"events/{full_id}/clip.mp4", is_video=True)
    #return send_file(r.raw, mimetype=r.headers['Content-Type'])
    return send_from_directory('static/images', '1x1.png', mimetype='image/png')


# ... other routes unchanged ...
@app.route('/detections/by_hour/<date>/<int:hour>')
def show_detections_by_hour(date, hour):
    records = get_records_for_date_hour(date, hour)
    return render_template('detections_by_hour.html', date=date, hour=hour, records=records)


@app.route('/detections/by_scientific_name/<scientific_name>/<date>', defaults={'end_date': None})
@app.route('/detections/by_scientific_name/<scientific_name>/<date>/<end_date>')
def show_detections_by_scientific_name(scientific_name, date, end_date):
    if end_date is None:
        records = get_records_for_scientific_name_and_date(scientific_name, date)
        return render_template('detections_by_scientific_name.html', scientific_name=scientific_name, date=date,
                               end_date=end_date, common_name=get_common_name(scientific_name), records=records)


@app.route('/daily_summary/<date>')
def show_daily_summary(date):
    date_datetime = datetime.strptime(date, "%Y-%m-%d")
    daily_summary = get_daily_summary(date_datetime)
    today = datetime.now().strftime('%Y-%m-%d')
    earliest_date = get_earliest_detection_date()
    return render_template('daily_summary.html', daily_summary=daily_summary, date=date, today=today,
                           earliest_date=earliest_date)

@app.route('/events/<event_id>/choices')
def get_choices(event_id):
    db = get_db()
    rows = db.execute(
            "SELECT rank, display_name, score FROM detection_choices "
            "WHERE event_id = ? ORDER BY rank", (event_id,)
    ).fetchall()

    return jsonify([{"rank":r,"label":n,"score":s} for r,n,s in rows])

@app.route('/set_label', methods=['POST'])
def set_label():
    event_id = request.form['event_id']
    sub_label = request.form['selected_label']
    db = get_db()

    # 1) Update your own database record if desired
    db.execute("UPDATE detections SET user_label = ? WHERE frigate_event = ?",
               (sub_label, event_id))
    db.commit()
    # 2) Optionally, push sub_label back to Frigate
    r = requests.post(
      f"{FRIGATE_API}/api/events/{event_id}/sub_label",
      json={"subLabel": sub_label}
    )
    if not r.ok:
        app.logger.error("Failed to set sub_label on Frigate API")
    return redirect(request.referrer or url_for('index'))

@app.route('/detections/<event_id>/review', methods=['POST'])
def review_detection(event_id):
    """Mark a detection as reviewed."""
    reviewed = request.json.get('reviewed', True)
    db = get_db()
    db.execute(
        "UPDATE detections SET reviewed = ? WHERE frigate_event = ?",
        (1 if reviewed else 0, event_id)
    )
    db.commit()
    return jsonify(success=True, reviewed=bool(reviewed))

@app.route('/detections/<event_id>/review', methods=['DELETE'])
def unreview_detection(event_id):
    """Clear the reviewed flag."""
    db = get_db()
    db.execute(
        "UPDATE detections SET reviewed = 0 WHERE frigate_event = ?",
        (event_id,)
    )
    db.commit()
    return jsonify(success=True, reviewed=False)


def load_config():
    global config
    file_path = './config/config.yml'
    with open(file_path, 'r') as config_file:
        config = yaml.safe_load(config_file)

@app.teardown_appcontext
def close_db(exc):
    """
    Close the database connection at the end of the request, if it exists.
    This is always called, even on errors.
    """
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()


load_config()


if __name__ == '__main__':
    web_cfg = yaml.safe_load(open('config/config.yml'))['webui']
    app.run(host=web_cfg['host'], port=web_cfg['port'])
