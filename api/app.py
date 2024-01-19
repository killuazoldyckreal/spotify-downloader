from flask import Flask, request, render_template, send_file, jsonify, after_this_request, redirect
import tempfile
import logging, os
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from spotipy.cache_handler import CacheHandler
from api.helper import is_valid_spotify_url, get_song_metadata
import traceback
from flask_cors import CORS
import requests
from io import BytesIO
from api.vercel_storage import blob
import time
from datetime import datetime, timedelta
from mutagen.id3 import ID3, APIC
from PIL import Image

logger = logging.getLogger("werkzeug")
logger.setLevel(logging.ERROR)
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "https://spotify-downloader-killua.vercel.app"}})

client_id=os.environ.get('CLIENT_ID')
client_secret=os.environ.get('CLIENT_SECRET')
        
class CustomCacheHandler(CacheHandler):
    def __init__(self):
        self.cache_path = None

    def get_cached_token(self):
        cached_token = os.environ.get('MY_API_TOKEN')
        return eval(cached_token) if cached_token else None

    def save_token_to_cache(self, token_info):
        os.environ['MY_API_TOKEN'] = str(token_info)

sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(client_id=client_id, client_secret=client_secret, cache_handler=CustomCacheHandler()))

@app.route('/.well-known/pki-validation/<filename>')
def verification_file(filename):
    return send_from_directory('verification', filename)

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/download', methods=['HEAD','GET','POST'])
def downloading():
    app.logger.debug('Received request to /download with method: %s', request.method)
    if request.method == 'GET':
        # Handle GET request
        return jsonify({'message': 'This is a GET request on /download'})
    elif request.method == 'POST':
        if request.is_json:
            data = request.get_json()
            if 'track_id' in data:
                track_id = data.get('track_id')
                url = 'https://api.spotifydown.com/download/' + track_id
                try:
                    results = sp.track(track_id)
                    audiobytes, filename = get_mp3(url)
                except:
                    traceback.print_exc()
                    return jsonify({'success': False, 'error': 'Song not found or invalid URL', 'errorinfo' : traceback.format_exc()}), 400
            else:
                track_name = data.get('name')
                try:
                    results = sp.search(q=track_name, type='track', limit=1)['tracks']['items'][0]
                except:
                    return jsonify({'success': False, 'error': 'Song not found'}), 400
                url = 'https://api.spotifydown.com/download/' + results['id']
                audiobytes, filename = get_mp3(data, url)
            cover_art_url = results['album']['images'][0]['url']
            filelike = BytesIO(audiobytes)
            merged_file = add_cover_art(filelike, cover_art_url)
            try:
                resp = blob.put(
                    pathname=filename,
                    body=merged_file.read()
                )
                current_time = datetime.utcnow()
                @after_this_request
                def remove_file(response):
                    try:
                        while True:
                            if current_time - datetime.utcnow() > timedelta(minutes=5):
                                blob.delete(file_info[filename]['url'])
                                del file_info[filename]
                                break
                            else:
                                time.sleep(300)
                    except Exception as error:
                        return jsonify({'success': False, 'error': traceback.format_exc()}), 400
                return jsonify({'success': True, 'url': resp['url'], 'filename' : filename}), 200
            except Exception as e:
                return jsonify({'success': False, 'error': traceback.format_exc()}), 400
        else:
            return render_template('home.html')
    else:
        return render_template('home.html')

def get_mp3(url):
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
        audiobytes = response.content
        return audiobytes, filename
    else:
        return None, None
    
def add_cover_art(audio_file, cover_art_url):
    audio_file.seek(0)
    tags = ID3()
    cover_image_data = BytesIO(requests.get(cover_art_url).content)
    tags['APIC'] = APIC(
        encoding=0,  # 0 is for utf-8
        mime='image/jpeg',
        type=3,  # 3 is for the front cover
        desc=u'Cover',
        data=cover_image_data.getvalue()
    )
    tags.save(audio_file)
    audio_file.seek(0)
    return audio_file

def delete_old_files():
    global file_info
    while True:
        try:
            current_time = datetime.utcnow()
            files_to_delete = [filename for filename, info in file_info.items() if current_time - info["timestamp"] > timedelta(minutes=5)]
            for filename in files_to_delete:
                blob.delete(file_info[filename]['url'])
                del file_info[filename]
            time.sleep(300)
        except Exception as e:
            print(f"Error deleting old files: {e}")

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=443)
