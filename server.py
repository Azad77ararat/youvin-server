# YouVin Home Server - Windows
# -*- coding: utf-8 -*-
import os
import shutil
import yt_dlp
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

DOWNLOAD_DIR = os.path.join(os.path.expanduser('~'), 'Desktop', 'YouVin-Downloads')
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

COOKIES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cookies.txt')
HAS_FFMPEG = shutil.which('ffmpeg') is not None

BASE_OPTS = {
    'quiet': True,
    'no_warnings': True,
}
if os.path.exists(COOKIES_FILE):
    BASE_OPTS['cookiefile'] = COOKIES_FILE


@app.route('/ping', methods=['GET', 'OPTIONS'])
def ping():
    return jsonify({'status': 'YouVin Home Server v4', 'ffmpeg': HAS_FFMPEG})


@app.route('/library', methods=['GET', 'OPTIONS'])
def library():
    files = []
    for f in os.listdir(DOWNLOAD_DIR):
        if f.lower().endswith(('.mp3', '.m4a', '.flac', '.opus', '.webm', '.mp4')):
            files.append(f)
    return jsonify({'files': sorted(files)})


@app.route('/play/<filename>', methods=['GET', 'OPTIONS'])
def play(filename):
    filepath = os.path.join(DOWNLOAD_DIR, filename)
    if not os.path.exists(filepath):
        return jsonify({'error': 'File not found'}), 404
    return send_file(filepath, as_attachment=False)


@app.route('/delete/<filename>', methods=['DELETE', 'OPTIONS'])
def delete(filename):
    filepath = os.path.join(DOWNLOAD_DIR, filename)
    if os.path.exists(filepath):
        os.remove(filepath)
        return jsonify({'success': True})
    return jsonify({'error': 'File not found'}), 404


@app.route('/info', methods=['GET', 'OPTIONS'])
def info():
    url = request.args.get('url')
    if not url:
        return jsonify({'error': 'No URL'}), 400
    try:
        with yt_dlp.YoutubeDL(dict(BASE_OPTS)) as ydl:
            data = ydl.extract_info(url, download=False)
            return jsonify({
                'title': data.get('title', 'Unknown'),
                'artist': data.get('uploader', 'Unknown'),
                'duration': data.get('duration', 0),
                'thumbnail': data.get('thumbnail', ''),
            })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/download', methods=['POST', 'OPTIONS'])
def download():
    if request.method == 'OPTIONS':
        return '', 200

    data = request.get_json(force=True, silent=True) or {}
    url = data.get('url')
    fmt = data.get('format', 'mp3')
    quality = data.get('quality', '320')

    if not url:
        return jsonify({'error': 'No URL'}), 400

    try:
        opts = dict(BASE_OPTS)
        opts['outtmpl'] = os.path.join(DOWNLOAD_DIR, '%(title)s.%(ext)s')

        if fmt == 'mp4':
            opts['format'] = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
        elif HAS_FFMPEG:
            codec = 'flac' if fmt == 'flac' else 'aac' if fmt == 'm4a' else 'mp3'
            opts['format'] = 'bestaudio/best'
            opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': codec,
                'preferredquality': quality,
            }]
        else:
            opts['format'] = 'bestaudio[ext=m4a]/bestaudio/best'

        with yt_dlp.YoutubeDL(opts) as ydl:
            info_data = ydl.extract_info(url, download=True)

        if 'requested_downloads' in info_data and info_data['requested_downloads']:
            filepath = info_data['requested_downloads'][0].get('filepath')
            if filepath and os.path.exists(filepath):
                return jsonify({'success': True, 'filename': os.path.basename(filepath), 'title': info_data.get('title', '')})

        title = info_data.get('title', 'download')
        for char in ['/', '\\', '?', '%', '*', ':', '|', '"', '<', '>']:
            title = title.replace(char, '_')

        for f in os.listdir(DOWNLOAD_DIR):
            if title[:15].lower() in f.lower() and f.lower().endswith(('.mp3', '.m4a', '.flac', '.mp4', '.opus', '.webm')):
                return jsonify({'success': True, 'filename': f, 'title': info_data.get('title', '')})

        return jsonify({'error': 'File not found after download'}), 500

    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    print('=' * 44)
    print('  YouVin Home Server v4')
    print('  http://localhost:5000')
    print('  Downloads:', DOWNLOAD_DIR)
    print('  ffmpeg:', 'OK' if HAS_FFMPEG else 'NICHT GEFUNDEN (nur M4A)')
    print('=' * 44)
    app.run(host='0.0.0.0', port=5000, debug=False)
