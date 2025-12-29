from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import yt_dlp
import instaloader
import os
import requests
import uuid
from io import BytesIO
import tempfile
import re
from datetime import datetime

app = Flask(__name__)
CORS(app)

# Configuration
DOWNLOAD_FOLDER = 'downloads'
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

# Initialize Instaloader (Instagram)
L = instaloader.Instaloader()

@app.route('/')
def home():
    return jsonify({
        "message": "YouTube/Instagram Downloader API",
        "endpoints": {
            "/download/youtube": "Download YouTube videos",
            "/download/instagram": "Download Instagram content",
            "/download/instagram/stories": "Download Instagram stories",
            "/info/youtube": "Get YouTube video info",
            "/info/instagram": "Get Instagram post info"
        }
    })

@app.route('/download/youtube', methods=['POST'])
def download_youtube():
    """
    Download YouTube video/audio
    Expected JSON: {"url": "youtube_url", "quality": "best/720p/480p/audio"}
    """
    try:
        data = request.json
        url = data.get('url')
        quality = data.get('quality', 'best')
        
        if not url:
            return jsonify({"error": "URL is required"}), 400
        
        # Generate unique filename
        file_id = str(uuid.uuid4())
        temp_dir = tempfile.mkdtemp()
        
        # Configure yt-dlp options
        ydl_opts = {
            'outtmpl': os.path.join(temp_dir, '%(title)s.%(ext)s'),
            'quiet': True,
        }
        
        if quality == 'audio':
            ydl_opts['format'] = 'bestaudio/best'
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
        else:
            if quality != 'best':
                ydl_opts['format'] = f'bestvideo[height<={quality[:-1]}]+bestaudio/best[height<={quality[:-1]}]'
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            downloaded_file = ydl.prepare_filename(info)
            
            if quality == 'audio':
                downloaded_file = downloaded_file.rsplit('.', 1)[0] + '.mp3'
        
        # Get the actual downloaded file
        files = os.listdir(temp_dir)
        if not files:
            return jsonify({"error": "Failed to download file"}), 500
            
        actual_file = os.path.join(temp_dir, files[0])
        
        # Return file
        return send_file(
            actual_file,
            as_attachment=True,
            download_name=os.path.basename(actual_file),
            mimetype='application/octet-stream'
        )
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/download/instagram', methods=['POST'])
def download_instagram():
    """
    Download Instagram post (photo/video/carousel)
    Expected JSON: {"url": "instagram_post_url"}
    """
    try:
        data = request.json
        url = data.get('url')
        
        if not url:
            return jsonify({"error": "URL is required"}), 400
        
        # Extract shortcode from URL
        shortcode = re.search(r'/(?:p|reel)/([^/?]+)', url)
        if not shortcode:
            return jsonify({"error": "Invalid Instagram URL"}), 400
        
        shortcode = shortcode.group(1)
        
        # Get post
        post = instaloader.Post.from_shortcode(L.context, shortcode)
        
        # Download post
        temp_dir = tempfile.mkdtemp()
        
        if post.typename == 'GraphImage':
            # Single image
            response = requests.get(post.url)
            filename = f"instagram_{shortcode}.jpg"
            filepath = os.path.join(temp_dir, filename)
            
            with open(filepath, 'wb') as f:
                f.write(response.content)
                
            return send_file(filepath, as_attachment=True, download_name=filename)
            
        elif post.typename == 'GraphVideo':
            # Video
            response = requests.get(post.video_url)
            filename = f"instagram_{shortcode}.mp4"
            filepath = os.path.join(temp_dir, filename)
            
            with open(filepath, 'wb') as f:
                f.write(response.content)
                
            return send_file(filepath, as_attachment=True, download_name=filename)
            
        elif post.typename == 'GraphSidecar':
            # Carousel (multiple media)
            # Create zip file for multiple items
            import zipfile
            
            zip_filename = f"instagram_{shortcode}.zip"
            zip_path = os.path.join(temp_dir, zip_filename)
            
            with zipfile.ZipFile(zip_path, 'w') as zipf:
                for index, node in enumerate(post.get_sidecar_nodes()):
                    if node.is_video:
                        url = node.video_url
                        ext = '.mp4'
                    else:
                        url = node.display_url
                        ext = '.jpg'
                    
                    response = requests.get(url)
                    media_filename = f"media_{index+1}{ext}"
                    media_path = os.path.join(temp_dir, media_filename)
                    
                    with open(media_path, 'wb') as f:
                        f.write(response.content)
                    
                    zipf.write(media_path, media_filename)
            
            return send_file(zip_path, as_attachment=True, download_name=zip_filename)
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/download/instagram/stories', methods=['POST'])
def download_instagram_stories():
    """
    Download Instagram stories
    Expected JSON: {"username": "instagram_username"}
    """
    try:
        data = request.json
        username = data.get('username')
        
        if not username:
            return jsonify({"error": "Username is required"}), 400
        
        # Get profile
        profile = instaloader.Profile.from_username(L.context, username)
        
        # Get stories
        temp_dir = tempfile.mkdtemp()
        stories = []
        
        for story in L.get_stories([profile.userid]):
            for item in story.get_items():
                if item.is_video:
                    url = item.video_url
                    ext = '.mp4'
                else:
                    url = item.url
                    ext = '.jpg'
                
                response = requests.get(url)
                filename = f"story_{int(item.date_utc.timestamp())}{ext}"
                filepath = os.path.join(temp_dir, filename)
                
                with open(filepath, 'wb') as f:
                    f.write(response.content)
                
                stories.append(filepath)
        
        if not stories:
            return jsonify({"message": "No stories available"}), 404
        
        # Create zip if multiple stories
        if len(stories) > 1:
            import zipfile
            zip_filename = f"stories_{username}.zip"
            zip_path = os.path.join(temp_dir, zip_filename)
            
            with zipfile.ZipFile(zip_path, 'w') as zipf:
                for story_path in stories:
                    zipf.write(story_path, os.path.basename(story_path))
            
            return send_file(zip_path, as_attachment=True, download_name=zip_filename)
        else:
            # Single story
            return send_file(
                stories[0],
                as_attachment=True,
                download_name=os.path.basename(stories[0])
            )
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/info/youtube', methods=['GET'])
def youtube_info():
    """Get YouTube video information"""
    url = request.args.get('url')
    
    if not url:
        return jsonify({"error": "URL is required"}), 400
    
    try:
        ydl_opts = {'quiet': True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            formats = []
            for fmt in info.get('formats', []):
                if fmt.get('ext') and fmt.get('format_note'):
                    formats.append({
                        'format_id': fmt.get('format_id'),
                        'ext': fmt.get('ext'),
                        'resolution': fmt.get('format_note'),
                        'filesize': fmt.get('filesize'),
                        'video_codec': fmt.get('vcodec'),
                        'audio_codec': fmt.get('acodec')
                    })
            
            return jsonify({
                'title': info.get('title'),
                'duration': info.get('duration'),
                'uploader': info.get('uploader'),
                'thumbnail': info.get('thumbnail'),
                'formats': formats,
                'description': info.get('description')[:200] + '...' if info.get('description') else None
            })
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/info/instagram', methods=['GET'])
def instagram_info():
    """Get Instagram post information"""
    url = request.args.get('url')
    
    if not url:
        return jsonify({"error": "URL is required"}), 400
    
    try:
        shortcode = re.search(r'/(?:p|reel)/([^/?]+)', url)
        if not shortcode:
            return jsonify({"error": "Invalid Instagram URL"}), 400
        
        shortcode = shortcode.group(1)
        post = instaloader.Post.from_shortcode(L.context, shortcode)
        
        return jsonify({
            'username': post.owner_username,
            'caption': post.caption,
            'likes': post.likes,
            'comments': post.comments,
            'type': post.typename,
            'is_video': post.is_video,
            'video_duration': post.video_duration if post.is_video else None,
            'timestamp': post.date_utc.isoformat(),
            'media_count': post.mediacount if hasattr(post, 'mediacount') else 1
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)
