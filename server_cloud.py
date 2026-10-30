"""
YouVin Cloud Server v2
Render.com + Cloudflare R2
كل مستخدم له مكتبة خاصة — يعمل 24/7
"""

import os, uuid, json, re, threading, tempfile, shutil
import boto3
from botocore.config import Config
from flask import Flask, request, jsonify
from flask_cors import CORS
import yt_dlp

app = Flask(__name__)
CORS(app)

# ── R2 Config (من Environment Variables في Render) ────────────────────────────
R2_ACCOUNT_ID = os.environ.get('R2_ACCOUNT_ID', '')
R2_ACCESS_KEY = os.environ.get('R2_ACCESS_KEY', '')
R2_SECRET_KEY = os.environ.get('R2_SECRET_KEY', '')
R2_BUCKET     = os.environ.get('R2_BUCKET', 'youvin-music')
API_KEY       = os.environ.get('YOUVIN_API_KEY', 'youvin-secret-2024')

s3 = boto3.client(
    's3',
    endpoint_url=f'https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com',
    aws_access_key_id=R2_ACCESS_KEY,
    aws_secret_access_key=R2_SECRET_KEY,
    config=Config(signature_version='s3v4'),
    region_name='auto'
)

# ── حالة التحميل ──────────────────────────────────────────────────────────────
active_jobs: dict = {}

# ── مساعدات ───────────────────────────────────────────────────────────────────
def check_key():
    k = request.headers.get('X-API-Key') or request.args.get('key')
    return k == API_KEY

def safe_name(name: str) -> str:
    return re.sub(r'[^\w.\-]', '_', name)

def r2_key(user_id: str, filename: str) -> str:
    return f'users/{safe_name(user_id)}/songs/{safe_name(filename)}'

def meta_key(user_id: str) -> str:
    return f'users/{safe_name(user_id)}/library.json'

def load_library(user_id: str) -> list:
    try:
        obj = s3.get_object(Bucket=R2_BUCKET, Key=meta_key(user_id))
        return json.loads(obj['Body'].read())
    except:
        return []

def save_library(user_id: str, songs: list):
    data = json.dumps(songs, ensure_ascii=False).encode()
    s3.put_object(Bucket=R2_BUCKET, Key=meta_key(user_id),
                  Body=data, ContentType='application/json')

CONTENT_TYPES = {
    'mp3': 'audio/mpeg', 'm4a': 'audio/mp4',
    'flac': 'audio/flac', 'wav': 'audio/wav',
    'ogg': 'audio/ogg',  'mp4': 'video/mp4'
}

# ─────────────────────────────────────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/ping')
def ping():
    return jsonify({'ok': True, 'server': 'YouVin Cloud 2.0'})


@app.route('/library')
def library():
    if not check_key():
        return jsonify({'error': 'Unauthorized'}), 401
    user_id = request.args.get('user', '').strip()
    if not user_id:
        return jsonify({'error': 'user param required'}), 400
    songs = load_library(user_id)
    return jsonify({'files': songs, 'count': len(songs)})


@app.route('/play/<user_id>/<filename>')
def play(user_id, filename):
    if not check_key():
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        url = s3.generate_presigned_url(
            'get_object',
            Params={'Bucket': R2_BUCKET, 'Key': r2_key(user_id, filename)},
            ExpiresIn=3600
        )
        return jsonify({'url': url})
    except Exception as e:
        return jsonify({'error': str(e)}), 404


@app.route('/download', methods=['POST'])
def download():
    if not check_key():
        return jsonify({'error': 'Unauthorized'}), 401
    data    = request.get_json() or {}
    url     = data.get('url', '').strip()
    user_id = data.get('user', '').strip()
    fmt     = data.get('format', 'mp3')
    quality = data.get('quality', '320')

    if not url or not user_id:
        return jsonify({'error': 'url and user required'}), 400

    job_id = str(uuid.uuid4())[:8]
    active_jobs[job_id] = {'status': 'starting', 'progress': 0, 'title': '', 'error': ''}

    def run():
        tmp_dir = tempfile.mkdtemp()
        try:
            active_jobs[job_id]['status'] = 'downloading'

            if fmt == 'mp3':
                opts = {
                    'format': 'bestaudio/best',
                    'outtmpl': f'{tmp_dir}/%(title)s.%(ext)s',
                    'postprocessors': [{'key': 'FFmpegExtractAudio',
                                        'preferredcodec': 'mp3',
                                        'preferredquality': quality}],
                    'noplaylist': True, 'quiet': True,
                }
            elif fmt == 'flac':
                opts = {
                    'format': 'bestaudio/best',
                    'outtmpl': f'{tmp_dir}/%(title)s.%(ext)s',
                    'postprocessors': [{'key': 'FFmpegExtractAudio',
                                        'preferredcodec': 'flac'}],
                    'noplaylist': True, 'quiet': True,
                }
            elif fmt == 'm4a':
                opts = {
                    'format': 'bestaudio[ext=m4a]/bestaudio/best',
                    'outtmpl': f'{tmp_dir}/%(title)s.%(ext)s',
                    'noplaylist': True, 'quiet': True,
                }
            else:  # mp4
                opts = {
                    'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                    'outtmpl': f'{tmp_dir}/%(title)s.%(ext)s',
                    'noplaylist': True, 'quiet': True,
                }

            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get('title', 'Unknown')

            active_jobs[job_id]['title'] = title
            files = os.listdir(tmp_dir)
            if not files:
                raise Exception('لم يُحمَّل أي ملف')

            local_path = os.path.join(tmp_dir, files[0])
            ext = files[0].rsplit('.', 1)[-1].lower()
            filename = f'{title}.{ext}'

            active_jobs[job_id]['status'] = 'uploading'
            key = r2_key(user_id, filename)
            ct  = CONTENT_TYPES.get(ext, 'audio/mpeg')
            with open(local_path, 'rb') as f:
                s3.put_object(Bucket=R2_BUCKET, Key=key, Body=f, ContentType=ct)

            size = os.path.getsize(local_path)
            lib  = load_library(user_id)
            lib  = [s for s in lib if s.get('filename') != filename]
            lib.append({'filename': filename, 'title': title, 'ext': ext, 'size': size})
            save_library(user_id, lib)

            active_jobs[job_id].update({'status': 'done', 'progress': 100})

        except Exception as e:
            active_jobs[job_id].update({'status': 'error', 'error': str(e)})
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    threading.Thread(target=run, daemon=True).start()
    return jsonify({'job_id': job_id, 'success': True})


@app.route('/job/<job_id>')
def job_status(job_id):
    if not check_key():
        return jsonify({'error': 'Unauthorized'}), 401
    j = active_jobs.get(job_id)
    if not j:
        return jsonify({'error': 'not found'}), 404
    return jsonify(j)


@app.route('/upload', methods=['POST'])
def upload():
    if not check_key():
        return jsonify({'error': 'Unauthorized'}), 401
    user_id = request.form.get('user', '').strip()
    if not user_id:
        return jsonify({'error': 'user required'}), 400
    f = request.files.get('file')
    if not f:
        return jsonify({'error': 'no file'}), 400

    filename = safe_name(f.filename)
    ext   = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'mp3'
    title = filename.rsplit('.', 1)[0] if '.' in filename else filename
    data  = f.read()

    s3.put_object(Bucket=R2_BUCKET, Key=r2_key(user_id, filename),
                  Body=data, ContentType=CONTENT_TYPES.get(ext, 'audio/mpeg'))

    lib = load_library(user_id)
    lib = [s for s in lib if s.get('filename') != filename]
    lib.append({'filename': filename, 'title': title, 'ext': ext, 'size': len(data)})
    save_library(user_id, lib)

    return jsonify({'success': True, 'filename': filename, 'title': title})


@app.route('/delete/<user_id>/<filename>', methods=['DELETE'])
def delete_song(user_id, filename):
    if not check_key():
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        s3.delete_object(Bucket=R2_BUCKET, Key=r2_key(user_id, filename))
        lib = load_library(user_id)
        lib = [s for s in lib if s.get('filename') != filename]
        save_library(user_id, lib)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/rename', methods=['POST'])
def rename():
    if not check_key():
        return jsonify({'error': 'Unauthorized'}), 401
    data      = request.get_json() or {}
    user_id   = data.get('user', '').strip()
    old_name  = data.get('filename', '').strip()
    new_title = data.get('newTitle', '').strip()
    if not all([user_id, old_name, new_title]):
        return jsonify({'error': 'missing fields'}), 400
    lib = load_library(user_id)
    for s in lib:
        if s.get('filename') == old_name:
            s['title'] = new_title
    save_library(user_id, lib)
    return jsonify({'success': True})


@app.route('/reorder', methods=['POST'])
def reorder():
    if not check_key():
        return jsonify({'error': 'Unauthorized'}), 401
    data    = request.get_json() or {}
    user_id = data.get('user', '').strip()
    order   = data.get('order', [])
    if not user_id:
        return jsonify({'error': 'user required'}), 400
    lib     = load_library(user_id)
    idx_map = {s['filename']: s for s in lib}
    new_lib = [idx_map[fn] for fn in order if fn in idx_map]
    new_lib += [s for s in lib if s['filename'] not in set(order)]
    save_library(user_id, new_lib)
    return jsonify({'success': True})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
