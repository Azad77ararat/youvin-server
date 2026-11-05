"""
YouVin Cloud Server v4.0 — Render.com
- /library, /delete, /rename, /reorder  — يقرأ/يعدّل R2
- /download  — يحمّل من YouTube على Render ويرفع إلى R2
- /job/<id>  — حالة التحميل
- الأغاني تُشغَّل مباشرة من R2
"""

import os, re, json, threading, uuid, time, tempfile, shutil
import boto3
from flask import Flask, request, jsonify
from flask_cors import CORS

# ── R2 Config ─────────────────────────────────────────────────────────────────
R2_ACCOUNT_ID = os.environ.get('R2_ACCOUNT_ID', '8143bcf45fca20e95fb4d43f3e46c474')
R2_ACCESS_KEY = os.environ.get('R2_ACCESS_KEY', '8f12f945a7283401f0718fe5108cca79')
R2_SECRET_KEY = os.environ.get('R2_SECRET_KEY', '385247751cb11de26bede82f3617143df89439d34df94b6a12553fa05794629a')
R2_BUCKET     = os.environ.get('R2_BUCKET', 'youvin-music')
R2_ENDPOINT   = f'https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com'
R2_PUBLIC_URL = f'https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com/{R2_BUCKET}'

API_KEY       = os.environ.get('API_KEY', 'youvin-secret-2024')

# ── S3 Client ─────────────────────────────────────────────────────────────────
s3 = boto3.client(
    's3',
    endpoint_url=R2_ENDPOINT,
    aws_access_key_id=R2_ACCESS_KEY,
    aws_secret_access_key=R2_SECRET_KEY,
    region_name='auto'
)

app = Flask(__name__)
CORS(app)

jobs = {}  # job_id → {status, title, url, error}

# ── Auth ──────────────────────────────────────────────────────────────────────
def auth_ok():
    return (request.headers.get('X-API-Key') == API_KEY or
            request.args.get('key') == API_KEY)

# ── Content type helper ───────────────────────────────────────────────────────
def get_content_type(filename):
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'mp3'
    types = {
        'mp3': 'audio/mpeg', 'm4a': 'audio/mp4', 'flac': 'audio/flac',
        'wav': 'audio/wav', 'ogg': 'audio/ogg', 'mp4': 'video/mp4',
        'mov': 'video/quicktime', 'mkv': 'video/x-matroska',
        'webm': 'video/webm', 'avi': 'video/avi'
    }
    return types.get(ext, 'audio/mpeg')

# ── Storage size for user ─────────────────────────────────────────────────────
def get_user_storage(user):
    try:
        resp = s3.list_objects_v2(Bucket=R2_BUCKET, Prefix=f'songs/{user}/')
        return sum(o['Size'] for o in resp.get('Contents', []))
    except:
        return 0

# ── Ping ──────────────────────────────────────────────────────────────────────
@app.route('/ping')
def ping():
    return jsonify({'ok': True, 'server': 'YouVin Cloud v4.0 (Render)'})

# ── Download from YouTube ─────────────────────────────────────────────────────
@app.route('/download', methods=['POST'])
def download():
    if not auth_ok():
        return jsonify({'error': 'unauthorized'}), 401

    data    = request.get_json(force=True)
    url     = data.get('url', '').strip()
    user    = data.get('user', 'unknown')
    fmt     = data.get('format', 'mp3')
    quality = data.get('quality', '320')
    sub     = data.get('subType', 'free')

    if not url:
        return jsonify({'error': 'no url'}), 400

    # Storage limit check (100 MB free)
    used = get_user_storage(user)
    if sub == 'free' and used >= 100 * 1024 * 1024:
        return jsonify({'error': 'storage_full'}), 400

    job_id = str(uuid.uuid4())
    jobs[job_id] = {'status': 'pending', 'title': None, 'url': None, 'error': None}

    def do_download():
        try:
            import yt_dlp

            tmp_dir = tempfile.mkdtemp(prefix=f'youvin_{job_id}_')

            # cookies file — same directory as this script
            base_dir = os.path.dirname(os.path.abspath(__file__))
            cookies_path = os.environ.get('COOKIES_FILE', os.path.join(base_dir, 'youtube_cookies.txt'))
            if not os.path.exists(cookies_path):
                cookies_path = ''

            if fmt == 'mp4':
                ydl_opts = {
                    'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                    'outtmpl': os.path.join(tmp_dir, '%(title)s.%(ext)s'),
                    'merge_output_format': 'mp4',
                    'noplaylist': True,
                    'quiet': True,
                }
            else:
                bitrate  = quality if sub != 'free' else quality
                audio_fmt = {'mp3': 'mp3', 'm4a': 'm4a', 'flac': 'flac'}.get(fmt, 'mp3')
                ydl_opts = {
                    'format': 'bestaudio/best',
                    'outtmpl': os.path.join(tmp_dir, '%(title)s.%(ext)s'),
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': audio_fmt,
                        'preferredquality': bitrate,
                    }],
                    'noplaylist': True,
                    'quiet': True,
                }

            if cookies_path:
                ydl_opts['cookiefile'] = cookies_path

            jobs[job_id]['status'] = 'downloading'

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get('title', 'Unknown')

            files = os.listdir(tmp_dir)
            if not files:
                raise Exception('Download failed — no file')

            local_file = os.path.join(tmp_dir, files[0])
            filename   = files[0]
            safe       = re.sub(r'[^\w\-. ]', '_', filename)
            r2_key     = f'songs/{user}/{safe}'
            ct         = get_content_type(safe)

            jobs[job_id]['status'] = 'uploading'

            s3.upload_file(
                local_file, R2_BUCKET, r2_key,
                ExtraArgs={'ContentType': ct}
            )

            r2_url = f'{R2_PUBLIC_URL}/{r2_key}'

            # Cleanup
            try:
                os.remove(local_file)
                os.rmdir(tmp_dir)
            except:
                pass

            jobs[job_id].update({'status': 'done', 'title': title, 'url': r2_url, 'filename': safe})

        except Exception as e:
            jobs[job_id].update({'status': 'error', 'error': str(e)})

    threading.Thread(target=do_download, daemon=True).start()
    return jsonify({'job_id': job_id})

# ── Upload file directly (from device) ───────────────────────────────────────
@app.route('/upload', methods=['POST'])
def upload():
    if not auth_ok():
        return jsonify({'error': 'unauthorized'}), 401
    user = request.form.get('user', 'unknown')
    sub  = request.form.get('subType', 'free')
    f    = request.files.get('file')
    if not f:
        return jsonify({'error': 'no file'}), 400

    used = get_user_storage(user)
    if sub == 'free' and used >= 100 * 1024 * 1024:
        return jsonify({'error': 'storage_full'}), 400

    filename = re.sub(r'[^\w\-. ]', '_', f.filename or f'upload_{int(time.time())}.mp3')
    r2_key   = f'songs/{user}/{filename}'
    ct       = get_content_type(filename)

    try:
        s3.upload_fileobj(f, R2_BUCKET, r2_key, ExtraArgs={'ContentType': ct})
        url = f'{R2_PUBLIC_URL}/{r2_key}'
        title = filename.rsplit('.', 1)[0].replace('_', ' ')
        return jsonify({'ok': True, 'url': url, 'filename': filename, 'title': title})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ── Job status ────────────────────────────────────────────────────────────────
@app.route('/job/<job_id>')
def job_status(job_id):
    if not auth_ok():
        return jsonify({'error': 'unauthorized'}), 401
    j = jobs.get(job_id)
    if not j:
        return jsonify({'error': 'not found'}), 404
    return jsonify(j)

# ── Library: list user's songs from R2 ───────────────────────────────────────
@app.route('/library')
def library():
    if not auth_ok():
        return jsonify({'error': 'unauthorized'}), 401

    user = request.args.get('user', '')
    if not user:
        return jsonify({'error': 'no user'}), 400

    try:
        resp    = s3.list_objects_v2(Bucket=R2_BUCKET, Prefix=f'songs/{user}/')
        objects = resp.get('Contents', [])

        songs       = []
        total_bytes = 0
        for obj in objects:
            key      = obj['Key']
            filename = key.split('/')[-1]
            if not filename:
                continue
            size = obj['Size']
            total_bytes += size
            ext   = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'mp3'
            title = filename.rsplit('.', 1)[0].replace('_', ' ')
            url   = f'{R2_PUBLIC_URL}/{key}'
            songs.append({'filename': filename, 'title': title, 'url': url, 'size': size, 'ext': ext})

        songs.sort(key=lambda s: s['filename'])

        # Apply saved order
        try:
            obj   = s3.get_object(Bucket=R2_BUCKET, Key=f'meta/{user}/order.json')
            order = json.loads(obj['Body'].read())
            order_map = {fn: i for i, fn in enumerate(order)}
            songs.sort(key=lambda s: order_map.get(s['filename'], 9999))
        except:
            pass

        limit_bytes = 100 * 1024 * 1024
        storage = {
            'used':    total_bytes,
            'limit':   limit_bytes,
            'percent': round(total_bytes / limit_bytes * 100, 1) if limit_bytes > 0 else 0
        }

        return jsonify({'songs': songs, 'storage': storage})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ── Delete song from R2 ───────────────────────────────────────────────────────
@app.route('/delete/<user>/<filename>', methods=['DELETE'])
def delete_song(user, filename):
    if not auth_ok():
        return jsonify({'error': 'unauthorized'}), 401
    try:
        s3.delete_object(Bucket=R2_BUCKET, Key=f'songs/{user}/{filename}')
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ── Rename ────────────────────────────────────────────────────────────────────
@app.route('/rename', methods=['POST'])
def rename():
    if not auth_ok():
        return jsonify({'error': 'unauthorized'}), 401
    data      = request.get_json(force=True)
    user      = data.get('user', '')
    old_name  = data.get('old', '')
    new_title = data.get('new', '').strip()
    if not user or not old_name or not new_title:
        return jsonify({'error': 'missing fields'}), 400
    ext      = old_name.rsplit('.', 1)[-1] if '.' in old_name else 'mp3'
    new_safe = re.sub(r'[^\w\-. ]', '_', new_title) + '.' + ext
    old_key  = f'songs/{user}/{old_name}'
    new_key  = f'songs/{user}/{new_safe}'
    try:
        s3.copy_object(Bucket=R2_BUCKET, CopySource={'Bucket': R2_BUCKET, 'Key': old_key}, Key=new_key)
        s3.delete_object(Bucket=R2_BUCKET, Key=old_key)
        return jsonify({'ok': True, 'filename': new_safe, 'url': f'{R2_PUBLIC_URL}/{new_key}'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ── Reorder ───────────────────────────────────────────────────────────────────
@app.route('/reorder', methods=['POST'])
def reorder():
    if not auth_ok():
        return jsonify({'error': 'unauthorized'}), 401
    data  = request.get_json(force=True)
    user  = data.get('user', '')
    order = data.get('order', [])
    if not user:
        return jsonify({'error': 'no user'}), 400
    try:
        s3.put_object(
            Bucket=R2_BUCKET, Key=f'meta/{user}/order.json',
            Body=json.dumps(order).encode(), ContentType='application/json'
        )
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f'YouVin Cloud v4.0 (Render) — port {port}')
    app.run(host='0.0.0.0', port=port, debug=False)
