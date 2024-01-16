from gevent import monkey
monkey.patch_all()
from flask import Flask, request, render_template, send_file, redirect, jsonify, after_this_request, send_from_directory
from flask_socketio import SocketIO
import logging, os
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from api.chandler import CustomCacheHandler
from api.helper import MDATA, is_valid_spotify_url, get_song_metadata, estimate_conversion_time
import traceback
from flask_cors import CORS
from gevent.pywsgi import WSGIServer
from flask_compress import Compress
from geventwebsocket.handler import WebSocketHandler


logger = logging.getLogger("werkzeug")
logger.setLevel(logging.ERROR)
app = Flask(__name__)
CORS(app, supports_credentials=True)

compress = Compress()
compress.init_app(app)

app.config['SECRET_KEY'] = 'secret!'
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
socketio = SocketIO(app, secure=True, cors_allowed_origins="*")
cache_path = "api/.spotify_cache"

if not os.path.exists(cache_path):
    os.makedirs(cache_path)
client_id=os.environ.get('CLIENT_ID')
client_secret=os.environ.get('CLIENT_SECRET')
sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(client_id=client_id, client_secret=client_secret, cache_handler=CustomCacheHandler(cache_path)))

@app.route('/.well-known/pki-validation/<filename>')
def verification_file(filename):
    return send_from_directory('verification', filename)

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/download', methods=['POST'])
def downloading():
    if request.is_json:
        data = request.get_json()
        if 'track_id' in data:
            track_id = data.get('track_id')
            url = 'https://api.spotifydown.com/download/' + track_id
            try:
                track_info = sp.track(_id)
                song_title = track_info['name']
                data = get_song_metadata(track_info, sp)
                path = get_mp3(data,url)
            except:
                traceback.print_exc()
                return jsonify({'success': False, 'error': 'Song not found or invalid URL'}), 400
        else:
            track_name = data.get('name')
            try:
                results = sp.search(q=song_title, type='track', limit=1)['tracks']['items'][0]
            except:
                return jsonify({'success': False, 'error': 'Song not found'}), 400
            data = get_song_metadata(results, sp)
            url = 'https://api.spotifydown.com/download/' + data['_id']
            song_title = data['track_name']
            path = get_mp3(data,url)

        try:
            file_handle = open(path, 'r')
            @after_this_request
            def remove_file(response):
                try:
                    os.remove(path)
                    file_handle.close()
                except Exception as error:
                    app.logger.error("Error removing or closing downloaded file handle", error)
                return response
            return send_file(path, download_name = path, as_attachment=True, mimetype='audio/mpeg'), 200
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 400
    else:
        return render_template('home.html')

def progress_hook(d):
    if d['status'] == 'downloading':
        socketio.emit('progress', {'downloaded_bytes': d['downloaded_bytes'], 'total_bytes': d['total_bytes']})
    if d['status'] == 'finished':
        socketio.emit('finished', {'status':'finished'})

def get_mp3(data, query):
    headers = {
        'Accept': '*/*',
        'Accept-Encoding': 'gzip, deflate, br',
        'Accept-Language': 'en-GB,en;q=0.8',
        'Cache-Control': 'no-cache',
        'Origin': 'https://spotifydown.com',
        'Pragma': 'no-cache',
        'Referer': 'https://spotifydown.com/',
        'Sec-Ch-Ua': '"Not_A Brand";v="8", "Chromium";v="120", "Brave";v="120"',
        'Sec-Ch-Ua-Mobile': '?0',
        'Sec-Ch-Ua-Platform': '"Windows"',
        'Sec-Fetch-Dest': 'empty',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'same-site',
        'Sec-Gpc': '1',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    }
    response = requests.get(url, headers=headers)
    data = response.json()
    new_url = data['link']
    new_headers = {
        'Accept': '*/*',
        'Accept-Encoding': 'gzip, deflate, br',
        'Accept-Language': 'en-GB,en;q=0.8',
        'Cache-Control': 'no-cache',
        'Origin': 'https://spotifydown.com',
        'Pragma': 'no-cache',
        'Referer': 'https://spotifydown.com/',
        'Sec-Ch-Ua': '"Not_A Brand";v="8", "Chromium";v="120", "Brave";v="120"',
        'Sec-Ch-Ua-Mobile': '?0',
        'Sec-Ch-Ua-Platform': '"Windows"',
        'Sec-Fetch-Dest': 'empty',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'cross-site',
        'Sec-Gpc': '1',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    }

    response = requests.get(new_url, headers=new_headers)

    if response.ok:
        content_disposition = response.headers.get('Content-Disposition')
        filename = content_disposition.split('filename=')[1].replace('"', '') if content_disposition else 'output.mp3'
        with open(filename, 'wb') as f:
            f.write(response.content)
        return filename

if __name__ == "__main__":
    socketio.run(app, host='0.0.0.0')
    http_server = WSGIServer(('0.0.0.0'), app, handler_class=WebSocketHandler)
    http_server.serve_forever()
