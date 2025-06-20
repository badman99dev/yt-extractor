import os
import logging
import re
from urllib.parse import urlparse, parse_qs
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from youtube_transcript_api import YouTubeTranscriptApi

# Configure logging
logging.basicConfig(level=logging.DEBUG)

# Create Flask app
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "default-secret-key-for-development")

# Enable CORS for all routes
CORS(app)

def extract_video_id(url):
    """
    Extract YouTube video ID from various YouTube URL formats
    """
    # Handle different YouTube URL formats
    patterns = [
        r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)([^&\n?#]+)',
        r'youtube\.com/v/([^&\n?#]+)',
        r'youtube\.com/watch\?.*v=([^&\n?#]+)'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    
    # Try parsing as URL
    try:
        parsed_url = urlparse(url)
        if 'youtube.com' in parsed_url.netloc:
            if 'v' in parse_qs(parsed_url.query):
                return parse_qs(parsed_url.query)['v'][0]
        elif 'youtu.be' in parsed_url.netloc:
            return parsed_url.path.lstrip('/')
    except Exception as e:
        logging.error(f"Error parsing URL: {e}")
    
    return None

def format_transcript(transcript):
    """
    Format transcript data for better readability
    """
    formatted_text = ""
    for entry in transcript:
        # Clean up the text
        text = entry['text'].strip()
        if text:
            formatted_text += text + " "
    
    # Clean up extra spaces and return
    return ' '.join(formatted_text.split())

@app.route('/')
def index():
    """
    Serve the testing interface
    """
    return render_template('index.html')

@app.route('/api/extract-subtitles', methods=['POST'])
def extract_subtitles():
    """
    Extract subtitles from YouTube video URL
    Supports language preferences and multiple output formats
    """
    try:
        # Get JSON data from request
        data = request.get_json()
        
        if not data or 'url' not in data:
            return jsonify({
                'success': False,
                'error': 'URL is required in request body'
            }), 400
        
        url = data['url'].strip()
        preferred_languages = data.get('languages', ['hi', 'en'])  # Default: Hindi first, English second
        
        if not url:
            return jsonify({
                'success': False,
                'error': 'URL cannot be empty'
            }), 400
        
        # Extract video ID
        video_id = extract_video_id(url)
        
        if not video_id:
            return jsonify({
                'success': False,
                'error': 'Invalid YouTube URL format'
            }), 400
        
        logging.info(f"Extracting subtitles for video ID: {video_id}, preferred languages: {preferred_languages}")
        
        # Get list of available transcripts
        available_transcripts = {}
        priority_transcripts = {}  # For requested languages
        
        try:
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
            all_transcripts = list(transcript_list)
            logging.info(f"Found {len(all_transcripts)} available transcript(s)")
            
            # First, try to get transcripts in preferred languages
            for lang_code in preferred_languages:
                try:
                    transcript = transcript_list.find_transcript([lang_code])
                    transcript_data = transcript.fetch()
                    
                    # Convert transcript data to proper format if needed
                    if hasattr(transcript_data, '__iter__') and not isinstance(transcript_data, str):
                        formatted_data = []
                        for item in transcript_data:
                            if hasattr(item, 'text'):
                                formatted_data.append({'text': item.text, 'start': getattr(item, 'start', 0), 'duration': getattr(item, 'duration', 0)})
                            elif isinstance(item, dict) and 'text' in item:
                                formatted_data.append(item)
                            else:
                                formatted_data.append({'text': str(item), 'start': 0, 'duration': 0})
                        transcript_data = formatted_data
                    
                    lang_name = getattr(transcript, 'language', lang_code)
                    key = f'priority_{lang_code}'
                    
                    priority_transcripts[key] = {
                        'language': f'{lang_name} {"(Auto-generated)" if transcript.is_generated else "(Manual)"}',
                        'language_code': lang_code,
                        'is_generated': transcript.is_generated,
                        'text': format_transcript(transcript_data),
                        'raw_data': transcript_data,
                        'is_priority': True
                    }
                    logging.info(f"Found priority transcript in {lang_name} (generated: {transcript.is_generated})")
                    
                except Exception as e:
                    logging.warning(f"Priority language {lang_code} transcript not found: {e}")
            
            # Get all other available transcripts for comprehensive response
            for i, transcript in enumerate(all_transcripts):
                try:
                    lang_code = transcript.language_code
                    
                    # Skip if already in priority transcripts
                    if f'priority_{lang_code}' in priority_transcripts:
                        continue
                    
                    transcript_data = transcript.fetch()
                    
                    # Convert transcript data to proper format if needed
                    if hasattr(transcript_data, '__iter__') and not isinstance(transcript_data, str):
                        formatted_data = []
                        for item in transcript_data:
                            if hasattr(item, 'text'):
                                formatted_data.append({'text': item.text, 'start': getattr(item, 'start', 0), 'duration': getattr(item, 'duration', 0)})
                            elif isinstance(item, dict) and 'text' in item:
                                formatted_data.append(item)
                            else:
                                formatted_data.append({'text': str(item), 'start': 0, 'duration': 0})
                        transcript_data = formatted_data
                    
                    lang_name = getattr(transcript, 'language', lang_code)
                    
                    available_transcripts[f'transcript_{lang_code}'] = {
                        'language': f'{lang_name} {"(Auto-generated)" if transcript.is_generated else "(Manual)"}',
                        'language_code': lang_code,
                        'is_generated': transcript.is_generated,
                        'text': format_transcript(transcript_data),
                        'raw_data': transcript_data,
                        'is_priority': False
                    }
                    logging.info(f"Found additional transcript in {lang_name}")
                    
                except Exception as fetch_error:
                    logging.warning(f"Failed to fetch transcript {i+1} ({transcript.language_code}): {fetch_error}")
                    continue
                    
        except Exception as e:
            logging.error(f"Error accessing transcripts: {e}")
            return jsonify({
                'success': False,
                'error': f'Failed to access video transcripts: {str(e)}'
            }), 400
        
        # Combine priority and additional transcripts
        all_found_transcripts = {**priority_transcripts, **available_transcripts}
        
        if not all_found_transcripts:
            return jsonify({
                'success': False,
                'error': 'No subtitles/captions found for this video'
            }), 404
        
        # Return successful response with priority transcripts first
        response_data = {
            'success': True,
            'video_id': video_id,
            'video_url': url,
            'requested_languages': preferred_languages,
            'priority_transcripts': priority_transcripts,
            'priority_transcripts_found': len(priority_transcripts),
            'all_transcripts': all_found_transcripts,
            'total_transcripts_found': len(all_found_transcripts)
        }
        
        logging.info(f"Successfully extracted {len(all_found_transcripts)} transcript(s), {len(priority_transcripts)} priority")
        return jsonify(response_data)
        
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        return jsonify({
            'success': False,
            'error': f'Internal server error: {str(e)}'
        }), 500

@app.route('/api/health', methods=['GET'])
def health_check():
    """
    Health check endpoint
    """
    return jsonify({
        'status': 'healthy',
        'service': 'YouTube Subtitle Extractor API',
        'version': '1.0.0'
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
