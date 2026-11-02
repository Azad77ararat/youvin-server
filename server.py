from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import yt_dlp
import os
import glob
import urllib.parse
import uuid
import threading

app = Flask(__name__)
CORS(app)

DOWNLOADS_DIR = r"C:\Users\ISSA\Desktop\YouVin-Downloads"
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

# Job store: job_id -> {'status': 'pending'|'done'|'error', 'filename': ..., 'title': ..., 'error': ...}
jobs = {}

def do_download(job_id, url, fmt, quality, user_id):
    try:
        # Get info
        ydl_opts_info = {'quiet': True, 'no_warnings': True, 'skip_download': True}
        with yt_dlp.YoutubeDL(ydl_opts_info) as ydl:
            info = ydl.extract_info(url, download=False)
            title = info.get('title', 'audio')

        safe_title = "".join(c for c in title if c.isalnum() or c in ' -_()').strip()

        # Build ydl options per format
        user_dir = os.path.join(DOWNLOADS_DIR, str(user_id)) if user_id else DOWNLOADS_DIR
        os.makedirs(user_dir, exist_ok=True)

        outtmpl = os.path.join(user_dir, f'{safe_title}.%(ext)s')

        if fmt in ('mp3',):
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': outtmpl,
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': str(quality),
                }],
                'quiet': True,
            }
        elif fmt == 'flac':
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': outtmpl,
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'flac',
                }],
                'quiet': True,
            }
        elif fmt == 'm4a':
            ydl_opts = {
                'format': 'bestaudio[ext=m4a]/bestaudio/best',
                'outtmpl': outtmpl,
                'quiet': True,
            }
        elif fmt == 'mp4':
            ydl_opts = {
                'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                'outtmpl': outtmpl,
                'quiet': True,
            }
        else:
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': outtmpl,
                'quiet': True,
            }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        # Find downloaded file
        matches = glob.glob(os.path.join(user_dir, f'{safe_title}.*'))
        if not matches:
            jobs[job_id] = {'status': 'error', 'error': 'File not found after download'}
            return

        actual_file = matches[0]
        actual_filename = os.path.basename(actual_file)
        rel_path = f'{user_id}/{urllib.parse.quote(actual_filename)}' if user_id else urllib.parse.quote(actual_filename)

        jobs[job_id] = {
            'status': 'done',
            'filename': actual_filename,
            'title': title,
            'url': f'/play/{rel_path}',
        }

    except Exception as e:
        jobs[job_id] = {'status': 'error', 'error': str(e)}


@app.route('/ping')
def ping():
    return jsonify({'ok': True, 'server': 'YouVin Local 2.0'})


@app.route('/info')
def info():
    url = request.args.get('url')
    if not url:
        return jsonify({'error': 'No URL'}), 400
    try:
        ydl_opts = {'quiet': True, 'no_warnings': True, 'skip_download': True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return jsonify({
                'title': info.get('title', 'Unknown'),
                'duration': info.get('duration', 0),
                'thumbnail': info.get('thumbnail', ''),
                'uploader': info.get('uploader', ''),
            })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/download', methods=['POST'])
def download():
    data = request.json or {}
    url = data.get('url')
    quality = data.get('quality', '320')
    fmt = data.get('format', 'mp3')
    user_id = data.get('user')

    if not url:
        return jsonify({'error': 'No URL'}), 400

    job_id = str(uuid.uuid4())
    jobs[job_id] = {'status': 'pending'}

    t = threading.Thread(target=do_download, args=(job_id, url, fmt, quality, user_id), daemon=True)
    t.start()

    return jsonify({'ok': True, 'job_id': job_id})


@app.route('/job/<job_id>')
def job_status(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify({'status': 'error', 'error': 'Job not found'}), 404
    return jsonify(job)


@app.route('/library')
def library():
    user_id = request.args.get('user')
    try:
        search_dir = os.path.join(DOWNLOADS_DIR, str(user_id)) if user_id else DOWNLOADS_DIR
        os.makedirs(search_dir, exist_ok=True)
        files = []
        for f in os.listdir(search_dir):
            if f.lower().endswith(('.mp3', '.m4a', '.flac', '.ogg', '.wav')):
                path = os.path.join(search_dir, f)
                rel = f'{user_id}/{urllib.parse.quote(f)}' if user_id else urllib.parse.quote(f)
                files.append({
                    'filename': f,
                    'title': os.path.splitext(f)[0],
                    'size': os.path.getsize(path),
                    'url': f'/play/{rel}',
                })
        files.sort(key=lambda x: x['filename'].lower())
        return jsonify({'songs': files})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/play/<path:rel_path>')
def play(rel_path):
    file_path = os.path.join(DOWNLOADS_DIR, urllib.parse.unquote(rel_path))
    if not os.path.exists(file_path):
        return jsonify({'error': 'File not found'}), 404
    return send_file(file_path, as_attachment=False)


@app.route('/delete/<path:rel_path>', methods=['DELETE'])
def delete(rel_path):
    file_path = os.path.join(DOWNLOADS_DIR, urllib.parse.unquote(rel_path))
    if not os.path.exists(file_path):
        return jsonify({'error': 'File not found'}), 404
    os.remove(file_path)
    return jsonify({'ok': True})


@app.route('/reorder', methods=['POST'])
def reorder():
    return jsonify({'ok': True})


@app.route('/rename', methods=['POST'])
def rename():
    data = request.json or {}
    user_id = data.get('user')
    old = data.get('filename')
    new_title = data.get('newTitle')
    if not old or not new_title:
        return jsonify({'error': 'Missing params'}), 400
    search_dir = os.path.join(DOWNLOADS_DIR, str(user_id)) if user_id else DOWNLOADS_DIR
    old_path = os.path.join(search_dir, old)
    if not os.path.exists(old_path):
        return jsonify({'error': 'File not found'}), 404
    ext = os.path.splitext(old)[1]
    safe = "".join(c for c in new_title if c.isalnum() or c in ' -_()').strip()
    new_path = os.path.join(search_dir, safe + ext)
    os.rename(old_path, new_path)
    return jsonify({'ok': True, 'filename': safe + ext})


@app.route('/upload', methods=['POST'])
def upload():
    user_id = request.headers.get('X-User-Id') or request.form.get('user')
    f = request.files.get('file')
    if not f:
        return jsonify({'error': 'No file'}), 400
    user_dir = os.path.join(DOWNLOADS_DIR, str(user_id)) if user_id else DOWNLOADS_DIR
    os.makedirs(user_dir, exist_ok=True)
    safe = "".join(c for c in f.filename if c.isalnum() or c in ' -_.()').strip()
    save_path = os.path.join(user_dir, safe)
    f.save(save_path)
    rel = f'{user_id}/{urllib.parse.quote(safe)}' if user_id else urllib.parse.quote(safe)
    return jsonify({'ok': True, 'filename': safe, 'url': f'/play/{rel}'})


if __name__ == '__main__':
    print("YouVin Local Server running on http://localhost:5000")
    app.run(host='0.0.0.0', port=5000, debug=False)
