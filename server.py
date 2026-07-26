# YouVin Home Server - Windows Mapped
# -*- coding: utf-8 -*-
import os
import shutil
import yt_dlp
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# مجلد التحميلات على سطح المكتب
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

@app.route('/ping', methods=['GET'])
def ping():
    return jsonify({'status': 'YouVin Home Server', 'ffmpeg': HAS_FFMPEG})

@app.route('/download', methods=['POST'])
def download():
    data = request.get_json()
    url = data.get('url')
    fmt_raw = data.get('format', 'mp3-320') # استقبال الصيغة الكاملة من الواجهة
    
    if not url:
        return jsonify({'error': 'Bitte einen Link eingeben'}), 400

    # تحليل الصيغة والجودة بشكل ذكي
    if 'mp4' in fmt_raw:
        fmt = 'mp4'
    elif 'mp3' in fmt_raw:
        fmt = 'mp3'
    else:
        fmt = fmt_raw # m4a أو flac

    quality = '320' if '320' in fmt_raw else '128' if '128' in fmt_raw else 'best'

    # فحص القيود الفنية لجهاز المستخدم قبل التحميل لمنع الانهيار
    if 'mp4' in fmt_raw and not HAS_FFMPEG:
        return jsonify({'error': 'تحميل الفيديو بجودة عالية يتطلب تثبيت ffmpeg على الكمبيوتر. يمكنك حالياً تحميل الصوت بصيغة M4A فقط.'}), 400
    if (fmt == 'mp3' or fmt == 'flac') and not HAS_FFMPEG:
        return jsonify({'error': 'تحويل الصوت إلى MP3 أو FLAC يتطلب ffmpeg. اختر صيغة M4A لتعمل معك فوراً بدون إضافات.'}), 400

    try:
        opts = dict(BASE_OPTS)
        opts['outtmpl'] = os.path.join(DOWNLOAD_DIR, '%(title)s.%(ext)s')

        if fmt == 'mp4':
            opts['format'] = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
        else:
            if HAS_FFMPEG:
                codec = 'flac' if fmt == 'flac' else 'aac' if fmt == 'm4a' else 'mp3'
                opts['format'] = 'bestaudio/best'
                opts['postprocessors'] = [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': codec,
                    'preferredquality': quality,
                }]
            else:
                # العمل بدقة وبدون مشاكل في حال غياب ffmpeg
                opts['format'] = 'bestaudio[ext=m4a]/bestaudio/best'

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            
            # جلب مسار الملف الفعلي المباشر لضمان إرساله بنجاح
            requested_downloads = info.get('_reports', [{}])[0].get('filepath') or info.get('requested_downloads', [{}])[0].get('filepath')
            
            if requested_downloads and os.path.exists(requested_downloads):
                filename = os.path.basename(requested_downloads)
                return send_file(requested_downloads, as_attachment=True, download_name=filename)

        # حل احتياطي في حال لم ينجح جلب المسار المباشر
        title = info.get('title', 'download')
        for f in os.listdir(DOWNLOAD_DIR):
            if title[:10] in f:
                filepath = os.path.join(DOWNLOAD_DIR, f)
                return send_file(filepath, as_attachment=True, download_name=f)

        return jsonify({'error': 'File not found after download'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    print('=' * 44)
    print('  YouVin Home Server - Ready')
    print('  http://localhost:5000')
    print('  ffmpeg:', 'OK' if HAS_FFMPEG else 'NICHT GEFUNDEN (نوصي باختيار صيغة M4A فقط)')
    print('=' * 44)
    app.run(host='0.0.0.0', port=5000, debug=False)

