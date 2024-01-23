from flask import Flask, request, render_template, jsonify, session, current_app
import os, requests, json, traceback, secrets
from flask_wtf.csrf import CSRFProtect, generate_csrf
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_cors import CORS
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from helper import *
from io import BytesIO
import dropbox
from itsdangerous import URLSafeTimedSerializer

active_files = {}
app = Flask(__name__)
secret_key = os.urandom(24)
app.config['SECRET_KEY'] = secret_key
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'None'
app.config['REQUEST_METHODS'] = ['GET', 'POST', 'HEAD', 'OPTIONS']
client_id=os.environ.get('CLIENT_ID')
client_secret=os.environ.get('CLIENT_SECRET')
csrf = CSRFProtect(app)
limiter = Limiter(
    app,
    storage_uri='memory://'
)

CORS(app, resources={r"/*": {"origins": ["https://spotifydownloader-killua.onrender.com", "https://dl.dropboxusercontent.com"]}})
sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(client_id=client_id, client_secret=client_secret, cache_handler=CustomCacheHandler()))

def _get_config(
    value, config_name, default=None, required=True, message="CSRF is not configured."
):
    if value is None:
        value = current_app.config.get(config_name, default)

    if required and value is None:
        raise RuntimeError(message)

    return value

def validate_csrf(app, data, secret_key=None, time_limit=None, token_key=None):
    secret_key = _get_config(
        secret_key,
        "WTF_CSRF_SECRET_KEY",
        current_app.secret_key,
        message="A secret key is required to use CSRF.",
    )
    field_name = _get_config(
        token_key,
        "WTF_CSRF_FIELD_NAME",
        "csrf_token",
        message="A field name is required to use CSRF.",
    )
    time_limit = _get_config(time_limit, "WTF_CSRF_TIME_LIMIT", 3600, required=False)
    s = URLSafeTimedSerializer(secret_key, salt="wtf-csrf-token")
    token = s.loads(data, max_age=time_limit)
    sessiontoken = session[field_name]
    if sessiontoken==token:
        return True
    else:
        return False

@app.route('/deletefile', methods=['POST'])
def deletingfile():
    if request.method == 'POST':
        csrf_token = request.headers.get('X-CSRFToken')
        referer = request.headers.get('Referer')
        if not referer or 'https://spotifydownloader-killua.onrender.com' not in referer:
            return jsonify({'success': False, 'error': 'Invalid Referer'}), 403
        if csrf_token and validate_csrf(app, csrf_token):
            if request.is_json:
                data = request.get_json()
                if 'dkey' in data and data['dkey'] in active_files:
                    try:
                        dropbox_path = active_files[data['dkey']]
                        delete_file(dropbox_path)
                    except:
                        app.logger.exception(traceback.format_exc())
                        return jsonify({'success': False}), 400
                    return jsonify({'success': True}), 200
                else:
                    return jsonify({'success': False, 'error': 'Key Mismatch or File does not exist'}), 400
            else:
                return jsonify({'success': False, 'error': 'Data must be in json format'}), 400
        else:
            return jsonify({'success': False, 'error': 'CSRF token validation failed'}), 403
    else:
        message = f'This is a {request.method} request on /download'
        return jsonify({'message': message})

@app.route('/')
def home():
    csrf_token = generate_csrf()
    return render_template('home.html', csrf_token = csrf_token)

@app.route('/download', methods=['HEAD','GET','POST'])
@limiter.limit("5 per minute")
def downloading():
    app.logger.debug('Received request to /download with method: %s', request.method)
    if request.method == 'GET':
        return jsonify({'message': 'This is a GET request on /download'})
    elif request.method == 'POST': # Assuming you have a function to generate CSRF tokens
        csrf_token = request.headers.get('X-CSRFToken')
        referer = request.headers.get('Referer')
        app.logger.error(csrf_token)
        if not referer or 'https://spotifydownloader-killua.onrender.com/' not in referer:
            return jsonify({'success': False, 'error': 'Invalid Referer'}), 403
        if csrf_token and validate_csrf(app, csrf_token):
            if request.is_json:
                data = request.get_json()
                baseurl = 'https://api.fabdl.com/spotify/get?url='
                if 'track_id' in data:
                    track_id = data.get('track_id')
                    baseurl = 'https://api.fabdl.com/spotify/get?url=https://open.spotify.com/track/'
                    try:
                        results = sp.track(track_id)
                        url = baseurl + track_id
                        audiobytes, filename = get_mp3(url)
                    except:
                        app.logger.exception(traceback.format_exc())
                        return jsonify({'success': False, 'error': 'Song not found or invalid URL'}), 400
                else:
                    track_name = data.get('name')
                    try:
                        results = sp.search(q=track_name, type='track', limit=1)['tracks']['items'][0]
                    except:
                        app.logger.exception(traceback.format_exc())
                        return jsonify({'success': False, 'error': 'Song not found'}), 400
                    url = baseurl + results['id']
                    audiobytes, filename = get_mp3(url)
                if not audiobytes:
                    return jsonify({'success': False, 'error': 'Song not found'}), 400
                track_name = results['name']
                album_name = results['album']['name']
                release_date = results['album']['release_date']
                artists = [artist['name'] for artist in results['artists']]
                album_artists = [artist['name'] for artist in results['album']['artists']]
                genres = sp.artist(results['artists'][0]['id'])['genres']
                cover_art_url = results['album']['images'][0]['url']
                mdata = { 
                    'track_name': track_name,
                    'album_name': album_name,
                    'release_date': release_date,
                    'artists': artists,
                    'album_artists': album_artists,
                    'genres': genres,
                    'cover_art_url': cover_art_url
                }
                filelike = BytesIO(audiobytes)
                merged_file = add_mdata(filelike, mdata)
                token = secrets.token_hex(12)
                try:
                    dropbox_path = f"/songs/{filename}"
                    file_url, direct_url = upload_file(merged_file, dropbox_path)
                    active_files[token] = dropbox_path
                    return jsonify({'success': True, 'url': direct_url, 'filename' : filename, 'dkey' : token}), 200
                except Exception as e:
                    return jsonify({'success': False, 'error': traceback.format_exc()}), 400
            else:
                return render_template('home.html')
        else:
            return jsonify({'success': False, 'error': 'CSRF token validation failed'}), 403
    else:
        return render_template('home.html')

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=443, debug=True)
