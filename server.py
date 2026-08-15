# YouVin Home Server v3 - Windows
# -*- coding: utf-8 -*-
import os
import re
import shutil
import yt_dlp
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

DOWNLOAD_DIR = os.path.join(os.path.expanduser('~'), 'Desktop', 'YouVin-Downloads')
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

COOKIES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cookies.txt')
HAS_FFMPEG = shutil.which('ffmpeg') is not None

AUDIO_EXTS = ('.mp3', '.m4a', '.flac', '.opus', '.webm', '.wav', '.aac')
VIDEO_EXTS = ('.mp4', '.mkv')

BASE_OPTS = {'quiet': True, 'no_warnings': True}
if os.path.exists(COOKIES_FILE):
    BASE_OPTS['cookiefile'] = COOKIES_FILE

def clean_filename(name):
    return re.sub(r'[\\/*?:"<>|]', '_', name)

# ═══════════════════════════════════
# عزل كل جهاز/مستخدم بمجلده الخاص
# ═══════════════════════════════════
DEVICE_ID_RE = re.compile(r'^[a-zA-Z0-9_-]{8,64}$')

def get_device_dir():
    """كل طلب لازم يجيب X-Device-Id بالـ header. كل جهاز إله مجلد منفصل تماماً."""
    device_id = request.headers.get('X-Device-Id', '').strip()
    if not device_id or not DEVICE_ID_RE.match(device_id):
        return None
    user_dir = os.path.join(DOWNLOAD_DIR, device_id)
    os.makedirs(user_dir, exist_ok=True)
    return user_dir

def device_error():
    return jsonify({'error': 'Missing or invalid X-Device-Id header'}), 400

@app.route('/ping', methods=['GET'])
def ping():
    return jsonify({'status': 'YouVin Home Server v3', 'ffmpeg': HAS_FFMPEG})

@app.route('/library', methods=['GET'])
def library():
    user_dir = get_device_dir()
    if user_dir is None:
        return device_error()
    songs = []
    try:
        for f in sorted(os.listdir(user_dir)):
            ext = os.path.splitext(f)[1].lower()
            if ext in AUDIO_EXTS or ext in VIDEO_EXTS:
                path = os.path.join(user_dir, f)
                size = os.path.getsize(path)
                name = os.path.splitext(f)[0]
                songs.append({
                    'filename': f,
                    'title': name,
                    'ext': ext.lstrip('.'),
                    'size': size,
                    'is_video': ext in VIDEO_EXTS,
                })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    return jsonify({'songs': songs})

@app.route('/play/<path:filename>', methods=['GET'])
def play(filename):
    user_dir = get_device_dir()
    if user_dir is None:
        return device_error()
    try:
        # منع الخروج من مجلد المستخدم بمسارات مثل ../
        safe_name = os.path.basename(filename)
        filepath = os.path.join(user_dir, safe_name)
        if not os.path.exists(filepath):
            return jsonify({'error': 'File not found'}), 404
        return send_file(filepath, conditional=True)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/delete/<path:filename>', methods=['DELETE'])
def delete_song(filename):
    user_dir = get_device_dir()
    if user_dir is None:
        return device_error()
    try:
        safe_name = os.path.basename(filename)
        filepath = os.path.join(user_dir, safe_name)
        if not os.path.exists(filepath):
            return jsonify({'error': 'File not found'}), 404
        os.remove(filepath)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/info', methods=['GET'])
def info():
    url = request.args.get('url')
    if not url:
        return jsonify({'error': 'No URL'}), 400
    try:
        info_opts = dict(BASE_OPTS)
        info_opts['noplaylist'] = True
        with yt_dlp.YoutubeDL(info_opts) as ydl:
            data = ydl.extract_info(url, download=False)
            return jsonify({
                'title': data.get('title', 'Unknown'),
                'artist': data.get('uploader', 'Unknown'),
                'duration': data.get('duration', 0),
                'thumbnail': data.get('thumbnail', ''),
            })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/download', methods=['POST'])
def download():
    user_dir = get_device_dir()
    if user_dir is None:
        return device_error()
    data = request.get_json()
    url = data.get('url')
    fmt = data.get('format', 'mp3')
    quality = data.get('quality', '320')
    if not url:
        return jsonify({'error': 'No URL'}), 400
    try:
        opts = dict(BASE_OPTS)
        opts['noplaylist'] = True  # يحمّل الأغنية المطلوبة بس، حتى لو الرابط من قائمة تشغيل أو Mix
        opts['outtmpl'] = os.path.join(user_dir, '%(title)s.%(ext)s')
        if fmt == 'mp4':
            opts['format'] = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
        elif HAS_FFMPEG:
            codec = 'flac' if fmt == 'flac' else 'aac' if fmt == 'm4a' else 'mp3'
            opts['format'] = 'bestaudio/best'
            opts['postprocessors'] = [{'key': 'FFmpegExtractAudio', 'preferredcodec': codec, 'preferredquality': quality}]
        else:
            opts['format'] = 'bestaudio[ext=m4a]/bestaudio/best'

        with yt_dlp.YoutubeDL(opts) as ydl:
            info_data = ydl.extract_info(url, download=True)

        if 'requested_downloads' in info_data and info_data['requested_downloads']:
            filepath = info_data['requested_downloads'][0].get('filepath')
            if filepath and os.path.exists(filepath):
                return jsonify({'success': True, 'filename': os.path.basename(filepath), 'title': info_data.get('title', '')})

        title = info_data.get('title', 'download')
        title_clean = clean_filename(title)
        for f in os.listdir(user_dir):
            ext = os.path.splitext(f)[1].lower()
            if ext in AUDIO_EXTS or ext in VIDEO_EXTS:
                f_clean = clean_filename(os.path.splitext(f)[0])
                if title_clean[:15].lower() in f_clean.lower():
                    return jsonify({'success': True, 'filename': f, 'title': title})

        return jsonify({'error': 'File not found after download'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    print('=' * 44)
    print('  YouVin Home Server v3 (multi-device)')
    print('  http://localhost:5000')
    print('  Downloads:', DOWNLOAD_DIR)
    print('  ffmpeg:', 'OK' if HAS_FFMPEG else 'NICHT GEFUNDEN (nur M4A)')
    print('=' * 44)
    app.run(host='0.0.0.0', port=5000, debug=False)
