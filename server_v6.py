# YouVin Home Server v6 - Windows
# -*- coding: utf-8 -*-
import os
import re
import shutil
import subprocess
import yt_dlp
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

DOWNLOAD_DIR = os.path.join(os.path.expanduser('~'), 'Desktop', 'YouVin-Downloads')
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

HAS_FFMPEG = shutil.which('ffmpeg') is not None
HAS_SPOTDL = shutil.which('spotdl') is not None


def is_spotify_url(url):
    return 'spotify.com' in url or 'open.spotify' in url

def is_youtube_url(url):
    return 'youtube.com' in url or 'youtu.be' in url


def download_with_spotdl(url, fmt='mp3', quality='320'):
    """Download using spotDL - works for Spotify links and song searches."""
    before = set(os.listdir(DOWNLOAD_DIR))

    out_fmt = fmt if fmt in ('mp3', 'flac', 'm4a', 'opus') else 'mp3'
    cmd = [
        'spotdl',
        '--output', '{title} - {artists}.{output-ext}',
        '--format', out_fmt,
        '--bitrate', f'{quality}k',
        url
    ]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        timeout=300,
        cwd=DOWNLOAD_DIR  # spotDL saves relative to cwd
    )

    # Find new files
    after = set(os.listdir(DOWNLOAD_DIR))
    new_files = [
        f for f in (after - before)
        if f.lower().endswith(('.mp3', '.m4a', '.flac', '.opus', '.webm', '.mp4'))
    ]

    if new_files:
        return new_files[0], None

    # Check for errors
    err = result.stderr or result.stdout or 'spotDL فشل في التحميل'
    return None, err


def download_with_ytdlp(url, fmt='mp3', quality='320'):
    """Fallback: download using yt-dlp."""
    opts = {
        'quiet': True,
        'no_warnings': True,
        'outtmpl': os.path.join(DOWNLOAD_DIR, '%(title)s.%(ext)s'),
        'socket_timeout': 30,
        'retries': 3,
    }

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

    before = set(os.listdir(DOWNLOAD_DIR))

    with yt_dlp.YoutubeDL(opts) as ydl:
        info_data = ydl.extract_info(url, download=True)

    # Find new file
    after = set(os.listdir(DOWNLOAD_DIR))
    new_files = [
        f for f in (after - before)
        if f.lower().endswith(('.mp3', '.m4a', '.flac', '.opus', '.webm', '.mp4'))
    ]
    if new_files:
        return new_files[0], info_data.get('title', '')

    # Fallback: newest file
    all_files = [
        f for f in os.listdir(DOWNLOAD_DIR)
        if f.lower().endswith(('.mp3', '.m4a', '.flac', '.opus', '.webm', '.mp4'))
    ]
    if all_files:
        newest = max(all_files, key=lambda x: os.path.getmtime(os.path.join(DOWNLOAD_DIR, x)))
        return newest, info_data.get('title', '')

    return None, info_data.get('title', '')


@app.route('/ping', methods=['GET', 'OPTIONS'])
def ping():
    return jsonify({
        'status': 'YouVin Home Server v6',
        'ffmpeg': HAS_FFMPEG,
        'spotdl': HAS_SPOTDL,
    })


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
        opts = {'quiet': True, 'no_warnings': True, 'socket_timeout': 15}
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

    # --- Spotify: use spotDL ---
    if is_spotify_url(url):
        if not HAS_SPOTDL:
            return jsonify({
                'error': 'spotDL غير مثبت. شغّل: pip install spotdl'
            }), 500
        try:
            filename, err = download_with_spotdl(url, fmt, quality)
            if filename:
                return jsonify({'success': True, 'filename': filename, 'title': filename})
            return jsonify({'error': err or 'spotDL فشل'}), 500
        except subprocess.TimeoutExpired:
            return jsonify({'error': 'انتهت مهلة التحميل (5 دقائق)'}), 500
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    # --- YouTube / others: use yt-dlp ---
    try:
        filename, title = download_with_ytdlp(url, fmt, quality)
        if filename:
            return jsonify({'success': True, 'filename': filename, 'title': title or filename})
        return jsonify({'error': 'تم التحميل لكن لم يُعثر على الملف'}), 500
    except Exception as e:
        err = str(e)
        if is_youtube_url(url) and any(k in err.lower() for k in ['sign in', 'bot', 'reload', 'po token', 'nsig', 'n challenge', 'cookies']):
            return jsonify({
                'error': 'YouTube محظور. الصق رابط Spotify بدلاً منه.',
                'youtube_blocked': True,
            }), 500
        return jsonify({'error': err}), 500


if __name__ == '__main__':
    print('=' * 52)
    print('  YouVin Home Server v6')
    print('  http://localhost:5000')
    print('  Downloads:', DOWNLOAD_DIR)
    print('  ffmpeg :', 'OK' if HAS_FFMPEG else 'غير موجود')
    print('  spotDL :', 'OK' if HAS_SPOTDL else 'غير مثبت - شغّل: pip install spotdl')
    print('  Spotify : مدعوم عبر spotDL')
    print('  YouTube : yt-dlp (قد لا يعمل)')
    print('=' * 52)
    app.run(host='0.0.0.0', port=5000, debug=False)
