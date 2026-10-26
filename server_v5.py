# YouVin Home Server v5 - Windows
# -*- coding: utf-8 -*-
import os
import re
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


def build_opts(fmt, quality):
    opts = {
        'quiet': True,
        'no_warnings': True,
        'outtmpl': os.path.join(DOWNLOAD_DIR, '%(title)s.%(ext)s'),
        'socket_timeout': 30,
        'retries': 3,
    }

    if os.path.exists(COOKIES_FILE):
        opts['cookiefile'] = COOKIES_FILE

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

    return opts


def find_downloaded_file(info_data):
    """Try to find the file that was downloaded."""
    # Method 1: requested_downloads
    if 'requested_downloads' in info_data:
        for d in info_data['requested_downloads']:
            fp = d.get('filepath') or d.get('filename')
            if fp and os.path.exists(fp):
                return os.path.basename(fp)

    # Method 2: search by title
    title = info_data.get('title', '')
    if title:
        safe = title
        for ch in r'/\?%*:|"<>':
            safe = safe.replace(ch, '_')
        prefix = safe[:20].lower()
        for f in sorted(os.listdir(DOWNLOAD_DIR), key=lambda x: -os.path.getmtime(os.path.join(DOWNLOAD_DIR, x))):
            if f.lower().endswith(('.mp3', '.m4a', '.flac', '.opus', '.webm', '.mp4')):
                if prefix[:10] in f.lower():
                    return f

    # Method 3: newest file
    files = [
        f for f in os.listdir(DOWNLOAD_DIR)
        if f.lower().endswith(('.mp3', '.m4a', '.flac', '.opus', '.webm', '.mp4'))
    ]
    if files:
        newest = max(files, key=lambda x: os.path.getmtime(os.path.join(DOWNLOAD_DIR, x)))
        return newest

    return None


@app.route('/ping', methods=['GET', 'OPTIONS'])
def ping():
    return jsonify({'status': 'YouVin Home Server v5', 'ffmpeg': HAS_FFMPEG})


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
        opts = {
            'quiet': True,
            'no_warnings': True,
            'socket_timeout': 15,
        }
        if os.path.exists(COOKIES_FILE):
            opts['cookiefile'] = COOKIES_FILE
        with yt_dlp.YoutubeDL(opts) as ydl:
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
    url = data.get('url', '').strip()
    fmt = data.get('format', 'mp3')
    quality = data.get('quality', '320')

    if not url:
        return jsonify({'error': 'No URL'}), 400

    # Check if YouTube (inform user but still try)
    is_youtube = 'youtube.com' in url or 'youtu.be' in url

    try:
        opts = build_opts(fmt, quality)

        with yt_dlp.YoutubeDL(opts) as ydl:
            info_data = ydl.extract_info(url, download=True)

        filename = find_downloaded_file(info_data)
        if filename:
            return jsonify({
                'success': True,
                'filename': filename,
                'title': info_data.get('title', ''),
            })

        return jsonify({'error': 'تم التحميل لكن لم يُعثر على الملف'}), 500

    except Exception as e:
        err = str(e)

        # YouTube-specific helpful message
        if is_youtube and ('Sign in' in err or 'bot' in err.lower() or 'reload' in err.lower()
                           or 'PO Token' in err or 'nsig' in err or 'n challenge' in err.lower()):
            return jsonify({
                'error': 'YouTube يحظر التحميل التلقائي. جرّب رابط SoundCloud أو Bandcamp بدلاً من YouTube.',
                'youtube_blocked': True,
            }), 500

        return jsonify({'error': err}), 500


if __name__ == '__main__':
    print('=' * 52)
    print('  YouVin Home Server v5')
    print('  http://localhost:5000')
    print('  Downloads:', DOWNLOAD_DIR)
    print('  ffmpeg:', 'OK' if HAS_FFMPEG else 'غير موجود (M4A فقط)')
    print('  cookies:', 'OK' if os.path.exists(COOKIES_FILE) else 'غير موجود')
    print('  SoundCloud / Bandcamp / Vimeo: مدعوم')
    print('  YouTube: قد لا يعمل (PO Token)')
    print('=' * 52)
    app.run(host='0.0.0.0', port=5000, debug=False)
