# v2 android fix
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import yt_dlp
import os

app = Flask(__name__)
CORS(app)

DOWNLOAD_DIR = os.path.join(os.path.expanduser("~"), "YouVin_Downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

FORMAT_MAP = {
    'mp3-320': {'format': 'bestaudio/best', 'ext': 'mp3', 'quality': '320'},
    'mp3-128': {'format': 'bestaudio/best', 'ext': 'mp3', 'quality': '128'},
    'm4a':     {'format': 'bestaudio[ext=m4a]/best', 'ext': 'm4a', 'quality': '192'},
    'flac':    {'format': 'bestaudio/best', 'ext': 'flac', 'quality': 'lossless'},
    'mp4-hd':  {'format': 'bestvideo[height<=1080]+bestaudio/best', 'ext': 'mp4', 'quality': '1080'},
    'mp4-4k':  {'format': 'bestvideo[height<=2160]+bestaudio/best', 'ext': 'mp4', 'quality': '2160'},
}

BASE_OPTS = {
    'quiet': True,
    'extractor_args': {
        'youtube': {
            'player_client': ['android', 'web'],
            'player_skip': ['webpage', 'config'],
        }
    },
    'http_headers': {
        'User-Agent': 'Mozilla/5.0 (Linux; Android 11; Pixel 5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.91 Mobile Safari/537.36',
    },
}

@app.route('/info', methods=['GET'])
def info():
    url = request.args.get('url')
    if not url:
        return jsonify({'error': 'No URL provided'}), 400
    try:
        opts = dict(BASE_OPTS)
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return jsonify({
                'title': info.get('title', 'Unknown'),
                'artist': info.get('uploader', 'Unknown'),
                'duration': info.get('duration', 0),
                'thumbnail': info.get('thumbnail', ''),
            })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/download', methods=['POST'])
def download():
    data = request.json
    url = data.get('url')
    fmt = data.get('format', 'mp3-320')

    if not url:
        return jsonify({'error': 'No URL provided'}), 400

    fmt_info = FORMAT_MAP.get(fmt, FORMAT_MAP['mp3-320'])
    ext = fmt_info['ext']

    try:
        ydl_opts = dict(BASE_OPTS)
        ydl_opts['outtmpl'] = os.path.join(DOWNLOAD_DIR, '%(title)s.%(ext)s')

        if ext in ['mp3', 'flac', 'm4a']:
            ydl_opts['format'] = 'bestaudio/best'
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': ext,
                'preferredquality': fmt_info['quality'] if fmt_info['quality'] != 'lossless' else '0',
            }]
        else:
            ydl_opts['format'] = fmt_info['format']

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get('title', 'download')
            filename = f"{title}.{ext}"
            filepath = os.path.join(DOWNLOAD_DIR, filename)

            for f in os.listdir(DOWNLOAD_DIR):
                if title[:20] in f and f.endswith(f'.{ext}'):
                    filepath = os.path.join(DOWNLOAD_DIR, f)
                    break

            if os.path.exists(filepath):
                return send_file(filepath, as_attachment=True, download_name=filename)
            else:
                return jsonify({'error': 'File not found after download'}), 500

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/ping', methods=['GET'])
def ping():
    return jsonify({'status': 'YouVin Server running v2 ✅'})

if __name__ == '__main__':
    print("=" * 40)
    print("  YouVin Download Server v2")
    print("  http://localhost:5000")
    print("=" * 40)
    app.run(host='0.0.0.0', port=5000, debug=False)
