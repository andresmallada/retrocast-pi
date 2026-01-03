#!/usr/bin/env python3
"""
RetroCast RPI - Headless Multimedia Server
Backend for Raspberry Pi Zero 2W with composite video output (PAL)
Optimized for 512MB RAM
"""

# Eventlet monkey patching MUST be first
import eventlet
eventlet.monkey_patch()

import os
import sys
import json
import signal
import socket
import mimetypes
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional, Dict, Any, List

from flask import Flask, render_template, request, jsonify, send_from_directory
from flask_socketio import SocketIO, emit
from werkzeug.utils import secure_filename

# ==============================================================================
# CONFIGURATION
# ==============================================================================

MEDIA_DIR = Path("/home/pi/media")
UPLOAD_FOLDER = MEDIA_DIR
ALLOWED_EXTENSIONS = {
    'video': {'mp4', 'mkv', 'avi', 'mov', 'wmv', 'flv', 'webm', 'm4v', 'mpeg', 'mpg', '3gp'},
    'audio': {'mp3', 'wav', 'flac', 'aac', 'ogg', 'm4a', 'wma', 'opus'},
    'image': {'jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'tiff', 'tif'}
}
MPV_SOCKET = "/tmp/mpvsocket"
SPLASH_IMAGE = "/home/pi/retrocast/splash.png"

# YouTube quality limit for 480p (critical for Pi Zero 2W)
# Format priority: separate video+audio (better quality) > combined
YT_FORMAT = "bestvideo[height<=480]+bestaudio/best[height<=480]/best"

# ==============================================================================
# FLASK APP INITIALIZATION
# ==============================================================================

app = Flask(__name__, static_folder='static', template_folder='templates')
app.config['SECRET_KEY'] = 'retrocast-secret-key-change-in-production'
app.config['UPLOAD_FOLDER'] = str(UPLOAD_FOLDER)
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024 * 1024  # 2GB max upload

socketio = SocketIO(app, async_mode='eventlet', cors_allowed_origins="*")

# ==============================================================================
# MEDIA CONTROLLER CLASS
# ==============================================================================

class MediaController:
    """
    Manages media playback with 'Last Action Priority' logic.
    Ensures only one media process runs at a time.
    """
    
    def __init__(self):
        self.current_process: Optional[subprocess.Popen] = None
        self.current_media: Optional[str] = None
        self.current_type: Optional[str] = None  # 'video', 'audio', 'image', 'stream', 'monitor'
        self.is_playing: bool = False
        self.is_paused: bool = False
        self.is_looping: bool = False
        self.monitor_mode: bool = False
        self.splash_process: Optional[subprocess.Popen] = None
        self.lock = threading.Lock()
        self._status_thread: Optional[threading.Thread] = None
        self._stop_status_thread = threading.Event()
        
    def _kill_all_media_processes(self):
        """Kill any existing media processes blocking framebuffer."""
        # Kill splash process first (tracked)
        self._kill_splash()
        
        # Kill any other media processes
        processes_to_kill = ['mpv', 'vlc', 'fbi', 'fim']
        for proc_name in processes_to_kill:
            try:
                subprocess.run(['pkill', '-9', proc_name], 
                             stderr=subprocess.DEVNULL, 
                             stdout=subprocess.DEVNULL)
            except Exception:
                pass
        time.sleep(0.3)  # Allow processes to terminate
        
    def _get_mpv_base_args(self) -> List[str]:
        """Get base MPV arguments optimized for composite PAL output."""
        # openvt runs mpv on tty1 for proper VT/DRM access
        return [
            'openvt', '-f', '-s', '-c', '1', '--',
            'mpv',
            '--vo=drm',                    # Direct DRM output
            '--drm-connector=Composite-1', # Use composite output
            '--fs',                        # Fullscreen
            '--af=scaletempo',             # Maintain audio pitch during speed changes
            '--input-ipc-server=' + MPV_SOCKET,
            '--no-terminal',               # No terminal output
            '--no-osc',                    # No on-screen controller (save RAM)
            '--no-config',                 # Skip config file (faster startup)
            '--cache=yes',                 # Enable cache
            '--cache-secs=10',             # Cache 10 seconds
            '--demuxer-max-bytes=50M',     # Limit demuxer memory
            '--hwdec=auto',                # Hardware decoding if available
            '--video-sync=audio',          # Sync video to audio
            '--audio-device=auto',         # Auto audio device
        ]
    
    def _send_mpv_command(self, command: Dict[str, Any]) -> Optional[Dict]:
        """Send command to MPV via IPC socket."""
        try:
            if not os.path.exists(MPV_SOCKET):
                return None
            
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(2)
            sock.connect(MPV_SOCKET)
            
            cmd_str = json.dumps(command) + '\n'
            sock.sendall(cmd_str.encode('utf-8'))
            
            response = sock.recv(4096).decode('utf-8')
            sock.close()
            
            for line in response.strip().split('\n'):
                try:
                    data = json.loads(line)
                    if 'data' in data or 'error' in data:
                        return data
                except json.JSONDecodeError:
                    continue
            return None
        except Exception as e:
            print(f"MPV IPC error: {e}")
            return None
    
    def _get_mpv_property(self, prop: str) -> Any:
        """Get a property from MPV."""
        result = self._send_mpv_command({
            "command": ["get_property", prop]
        })
        if result and 'data' in result:
            return result['data']
        return None
    
    def _set_mpv_property(self, prop: str, value: Any) -> bool:
        """Set a property in MPV."""
        result = self._send_mpv_command({
            "command": ["set_property", prop, value]
        })
        return result is not None and result.get('error') == 'success'
    
    def _start_status_thread(self):
        """Start thread to monitor playback status and emit updates."""
        self._stop_status_thread.clear()
        
        def status_loop():
            consecutive_failures = 0
            while not self._stop_status_thread.is_set():
                try:
                    # Watchdog: check if process is alive
                    if self.current_process:
                        poll_result = self.current_process.poll()
                        if poll_result is not None:
                            print(f"Process ended with code: {poll_result}")
                            self._handle_playback_ended()
                            break
                    
                    # Check MPV responsiveness via IPC
                    if self.current_type in ('video', 'audio', 'stream', 'monitor'):
                        response = self._get_mpv_property('time-pos')
                        if response is None and self.is_playing:
                            consecutive_failures += 1
                            if consecutive_failures >= 5:
                                print("MPV unresponsive, handling as ended")
                                self._handle_playback_ended()
                                break
                        else:
                            consecutive_failures = 0
                    
                    status = self.get_status()
                    socketio.emit('status_update', status)
                        
                except Exception as e:
                    print(f"Status thread error: {e}")
                    consecutive_failures += 1
                    if consecutive_failures >= 10:
                        print("Too many consecutive failures, stopping monitoring")
                        self._handle_playback_ended()
                        break
                
                time.sleep(1)
        
        self._status_thread = threading.Thread(target=status_loop, daemon=True)
        self._status_thread.start()
    
    def _stop_status_monitoring(self):
        """Stop the status monitoring thread."""
        self._stop_status_thread.set()
        if self._status_thread:
            self._status_thread.join(timeout=2)
    
    def _handle_playback_ended(self):
        """Handle when playback ends or stream is lost."""
        with self.lock:
            self.is_playing = False
            self.current_media = None
            self.current_type = None
            
            # Always show splash in idle state
            self._show_splash()
            
            if self.monitor_mode:
                socketio.emit('status_update', {
                    'state': 'waiting',
                    'mode': 'monitor',
                    'message': 'Esperando stream...'
                })
            else:
                socketio.emit('status_update', {
                    'state': 'idle',
                    'mode': 'library'
                })
    
    def _kill_splash(self):
        """Kill splash screen process if running."""
        if self.splash_process:
            try:
                self.splash_process.terminate()
                self.splash_process.wait(timeout=1)
            except Exception:
                try:
                    self.splash_process.kill()
                except Exception:
                    pass
            self.splash_process = None
    
    def _show_splash(self):
        """Show splash screen on framebuffer using mpv via openvt."""
        try:
            # Kill existing splash first
            self._kill_splash()
            
            if os.path.exists(SPLASH_IMAGE):
                self.splash_process = subprocess.Popen(
                    [
                        'openvt', '-f', '-s', '-c', '1', '--',
                        'mpv', '--vo=drm', '--drm-connector=Composite-1',
                        '--fs', '--image-display-duration=inf',
                        '--no-terminal', '--no-osc', '--no-config',
                        '--video-aspect-override=4:3',
                        '--really-quiet',
                        SPLASH_IMAGE
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                print("Splash screen displayed")
        except Exception as e:
            print(f"Splash error: {e}")
    
    def play_local(self, filepath: str) -> Dict[str, Any]:
        """Play a local media file."""
        with self.lock:
            if not os.path.exists(filepath):
                return {'success': False, 'error': 'Archivo no encontrado'}
            
            # Security check: ensure path is within MEDIA_DIR
            try:
                resolved_path = Path(filepath).resolve()
                if not str(resolved_path).startswith(str(MEDIA_DIR.resolve())):
                    return {'success': False, 'error': 'Ruta no permitida'}
            except Exception:
                return {'success': False, 'error': 'Ruta inválida'}
            
            # Determine media type
            mime_type, _ = mimetypes.guess_type(filepath)
            if not mime_type:
                return {'success': False, 'error': 'Tipo de archivo no reconocido'}
            
            self._kill_all_media_processes()
            self._stop_status_monitoring()
            self.monitor_mode = False
            
            if mime_type.startswith('image/'):
                return self._play_image(filepath)
            elif mime_type.startswith('video/') or mime_type.startswith('audio/'):
                return self._play_av(filepath)
            else:
                return {'success': False, 'error': 'Tipo de archivo no soportado'}
    
    def _play_image(self, filepath: str) -> Dict[str, Any]:
        """Display image using mpv on DRM framebuffer via openvt."""
        try:
            args = [
                'openvt', '-f', '-s', '-c', '1', '--',
                'mpv',
                '--vo=drm',
                '--drm-connector=Composite-1',
                '--fs',
                '--image-display-duration=inf',
                '--input-ipc-server=' + MPV_SOCKET,
                '--no-terminal',
                '--no-osc',
                '--no-config',
                '--loop-file=inf',
                '--video-aspect-override=4:3',
                filepath
            ]
            self.current_process = subprocess.Popen(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            self.current_media = os.path.basename(filepath)
            self.current_type = 'image'
            self.is_playing = True
            self.is_paused = False
            
            return {'success': True, 'type': 'image', 'file': self.current_media}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def _play_av(self, filepath: str) -> Dict[str, Any]:
        """Play audio/video using MPV."""
        try:
            args = self._get_mpv_base_args()
            if self.is_looping:
                args.append('--loop-file=inf')
            args.append(filepath)
            
            self.current_process = subprocess.Popen(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            
            time.sleep(0.5)  # Wait for MPV to initialize
            
            self.current_media = os.path.basename(filepath)
            self.current_type = 'video' if 'video' in (mimetypes.guess_type(filepath)[0] or '') else 'audio'
            self.is_playing = True
            self.is_paused = False
            
            self._start_status_thread()
            
            return {'success': True, 'type': self.current_type, 'file': self.current_media}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def play_youtube(self, url: str) -> Dict[str, Any]:
        """Play YouTube video using yt-dlp + MPV."""
        with self.lock:
            self._kill_all_media_processes()
            self._stop_status_monitoring()
            self.monitor_mode = False
            
            try:
                # Extract stream URL with yt-dlp (480p max)
                # Format priority: separate video+audio (better quality) > combined
                result = subprocess.run(
                    [
                        'yt-dlp',
                        '-f', 'bestvideo[height<=480]+bestaudio/best[height<=480]/best',
                        '-g',
                        '--get-title',
                        '--no-playlist',
                        '--no-warnings',
                        '--no-check-certificates',
                        '--socket-timeout', '15',
                        '--cache-dir', '/tmp/yt-dlp-cache',
                        url
                    ],
                    capture_output=True,
                    text=True,
                    timeout=60
                )
                
                if result.returncode != 0:
                    error_msg = result.stderr.strip() if result.stderr else 'Error al extraer URL de YouTube'
                    return {'success': False, 'error': error_msg[:200]}
                
                # Parse output: first line is title, rest are URLs
                lines = result.stdout.strip().split('\n')
                title = lines[0] if lines else 'YouTube Video'
                stream_urls = [l for l in lines[1:] if l.startswith('http')]
                
                if not stream_urls:
                    # Fallback: all lines might be URLs
                    stream_urls = [l for l in lines if l.startswith('http')]
                    title = 'YouTube Video'
                
                if not stream_urls:
                    return {'success': False, 'error': 'No se pudo extraer URL'}
                
                # Build MPV command
                args = self._get_mpv_base_args()
                if self.is_looping:
                    args.append('--loop-file=inf')
                
                # Add stream URLs (video and audio if separate)
                if len(stream_urls) >= 2:
                    args.extend([stream_urls[0], '--audio-file=' + stream_urls[1]])
                else:
                    args.append(stream_urls[0])
                
                self.current_process = subprocess.Popen(
                    args,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                
                time.sleep(1)
                
                self.current_media = title
                self.current_type = 'stream'
                self.is_playing = True
                self.is_paused = False
                
                self._start_status_thread()
                
                return {'success': True, 'type': 'youtube', 'title': title}
                
            except subprocess.TimeoutExpired:
                return {'success': False, 'error': 'Timeout extrayendo URL'}
            except Exception as e:
                return {'success': False, 'error': str(e)}
    
    def start_monitor_mode(self, port: int = 1234) -> Dict[str, Any]:
        """Start monitor mode listening for UDP/RTP streams."""
        with self.lock:
            self._kill_all_media_processes()
            self._stop_status_monitoring()
            
            try:
                args = [
                    'openvt', '-f', '-s', '-c', '1', '--',
                    'mpv',
                    '--vo=drm',
                    '--drm-connector=Composite-1',   # Use composite output
                    '--fs',
                    '--af=scaletempo',
                    '--input-ipc-server=' + MPV_SOCKET,
                    '--no-terminal',
                    '--no-osc',
                    '--no-config',
                    '--idle=yes',                    # Stay open when idle
                    '--force-window=yes',            # Force window
                    '--keep-open=always',            # Keep open after playback
                    '--network-timeout=30',          # Network timeout
                    f'udp://@:{port}',               # Listen on UDP port
                ]
                
                self.current_process = subprocess.Popen(
                    args,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                
                time.sleep(0.5)
                
                self.monitor_mode = True
                self.current_media = f"Monitor UDP:{port}"
                self.current_type = 'monitor'
                self.is_playing = True
                self.is_paused = False
                
                self._start_status_thread()
                
                return {'success': True, 'mode': 'monitor', 'port': port}
                
            except Exception as e:
                return {'success': False, 'error': str(e)}
    
    def stop_monitor_mode(self) -> Dict[str, Any]:
        """Stop monitor mode and return to idle (show splash)."""
        with self.lock:
            self.monitor_mode = False
            self._kill_all_media_processes()
            self._stop_status_monitoring()
            self.is_playing = False
            self.current_media = None
            self.current_type = None
            
            # Show splash screen in idle state
            self._show_splash()
            
            return {'success': True}
    
    def play_pause(self) -> Dict[str, Any]:
        """Toggle play/pause."""
        if self.current_type == 'image':
            return {'success': True, 'paused': False}
        
        result = self._send_mpv_command({"command": ["cycle", "pause"]})
        if result:
            self.is_paused = not self.is_paused
            return {'success': True, 'paused': self.is_paused}
        return {'success': False, 'error': 'No hay reproducción activa'}
    
    def stop(self) -> Dict[str, Any]:
        """Stop playback and return to idle (show splash)."""
        with self.lock:
            self._kill_all_media_processes()
            self._stop_status_monitoring()
            self.monitor_mode = False
            self.is_playing = False
            self.is_paused = False
            self.current_media = None
            self.current_type = None
            
            # Show splash screen in idle state
            self._show_splash()
            
            return {'success': True}
    
    def volume_up(self, step: int = 5) -> Dict[str, Any]:
        """Increase volume."""
        result = self._send_mpv_command({"command": ["add", "volume", step]})
        vol = self._get_mpv_property("volume")
        return {'success': result is not None, 'volume': vol}
    
    def volume_down(self, step: int = 5) -> Dict[str, Any]:
        """Decrease volume."""
        result = self._send_mpv_command({"command": ["add", "volume", -step]})
        vol = self._get_mpv_property("volume")
        return {'success': result is not None, 'volume': vol}
    
    def set_loop(self, enabled: bool) -> Dict[str, Any]:
        """Enable/disable loop."""
        self.is_looping = enabled
        if self.current_type in ('video', 'audio', 'stream'):
            value = 'inf' if enabled else 'no'
            self._set_mpv_property('loop-file', value)
        return {'success': True, 'loop': enabled}
    
    def seek(self, seconds: int) -> Dict[str, Any]:
        """Seek relative position."""
        result = self._send_mpv_command({"command": ["seek", seconds, "relative"]})
        return {'success': result is not None}
    
    def get_status(self) -> Dict[str, Any]:
        """Get current playback status."""
        status = {
            'is_playing': self.is_playing,
            'is_paused': self.is_paused,
            'is_looping': self.is_looping,
            'monitor_mode': self.monitor_mode,
            'current_media': self.current_media,
            'current_type': self.current_type,
            'position': 0,
            'duration': 0,
            'volume': 100
        }
        
        if self.current_type in ('video', 'audio', 'stream', 'monitor'):
            pos = self._get_mpv_property('time-pos')
            dur = self._get_mpv_property('duration')
            vol = self._get_mpv_property('volume')
            paused = self._get_mpv_property('pause')
            
            status['position'] = pos if pos else 0
            status['duration'] = dur if dur else 0
            status['volume'] = vol if vol else 100
            status['is_paused'] = paused if paused is not None else self.is_paused
        
        return status


# ==============================================================================
# LIBRARY MANAGER
# ==============================================================================

class LibraryManager:
    """Manages local media library."""
    
    def __init__(self, media_dir: Path):
        self.media_dir = media_dir
        self._ensure_media_dir()
    
    def _ensure_media_dir(self):
        """Ensure media directory exists."""
        self.media_dir.mkdir(parents=True, exist_ok=True)
        # Create subdirectories
        (self.media_dir / 'videos').mkdir(exist_ok=True)
        (self.media_dir / 'music').mkdir(exist_ok=True)
        (self.media_dir / 'photos').mkdir(exist_ok=True)
    
    def _get_file_type(self, filepath: Path) -> Optional[str]:
        """Determine file type from extension."""
        ext = filepath.suffix.lower().lstrip('.')
        for file_type, extensions in ALLOWED_EXTENSIONS.items():
            if ext in extensions:
                return file_type
        return None
    
    def scan_library(self) -> Dict[str, List[Dict]]:
        """Scan media directory recursively."""
        library = {
            'video': [],
            'audio': [],
            'image': []
        }
        
        for filepath in self.media_dir.rglob('*'):
            if filepath.is_file():
                file_type = self._get_file_type(filepath)
                if file_type:
                    stat = filepath.stat()
                    library[file_type].append({
                        'name': filepath.name,
                        'path': str(filepath),
                        'relative_path': str(filepath.relative_to(self.media_dir)),
                        'size': stat.st_size,
                        'modified': stat.st_mtime
                    })
        
        # Sort by name
        for category in library:
            library[category].sort(key=lambda x: x['name'].lower())
        
        return library
    
    def delete_file(self, relative_path: str) -> Dict[str, Any]:
        """Delete a file from the library."""
        try:
            filepath = self.media_dir / relative_path
            if not filepath.exists():
                return {'success': False, 'error': 'Archivo no encontrado'}
            
            # Security check: ensure path is within media dir
            if not str(filepath.resolve()).startswith(str(self.media_dir.resolve())):
                return {'success': False, 'error': 'Ruta no permitida'}
            
            filepath.unlink()
            return {'success': True}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def save_upload(self, file, category: str = 'videos') -> Dict[str, Any]:
        """Save uploaded file."""
        try:
            if not file:
                return {'success': False, 'error': 'No hay archivo'}
            
            filename = secure_filename(file.filename)
            if not filename:
                return {'success': False, 'error': 'Nombre de archivo inválido'}
            
            # Determine category from extension
            ext = Path(filename).suffix.lower().lstrip('.')
            if ext in ALLOWED_EXTENSIONS['video']:
                category = 'videos'
            elif ext in ALLOWED_EXTENSIONS['audio']:
                category = 'music'
            elif ext in ALLOWED_EXTENSIONS['image']:
                category = 'photos'
            else:
                return {'success': False, 'error': 'Tipo de archivo no permitido'}
            
            save_path = self.media_dir / category / filename
            
            # Handle duplicate names
            counter = 1
            while save_path.exists():
                stem = Path(filename).stem
                suffix = Path(filename).suffix
                save_path = self.media_dir / category / f"{stem}_{counter}{suffix}"
                counter += 1
            
            file.save(str(save_path))
            return {'success': True, 'path': str(save_path), 'filename': save_path.name}
            
        except Exception as e:
            return {'success': False, 'error': str(e)}


# ==============================================================================
# GLOBAL INSTANCES
# ==============================================================================

media_controller = MediaController()
library_manager = LibraryManager(MEDIA_DIR)


# ==============================================================================
# ROUTES - WEB INTERFACE
# ==============================================================================

@app.route('/')
def index():
    """Serve main SPA."""
    return send_from_directory('templates', 'index.html')


@app.route('/static/<path:filename>')
def serve_static(filename):
    """Serve static files."""
    return send_from_directory('static', filename)


# ==============================================================================
# ROUTES - API
# ==============================================================================

@app.route('/api/status')
def api_status():
    """Get current status."""
    return jsonify(media_controller.get_status())


@app.route('/api/library')
def api_library():
    """Get media library."""
    return jsonify(library_manager.scan_library())


@app.route('/api/play', methods=['POST'])
def api_play():
    """Play a local file."""
    data = request.get_json()
    filepath = data.get('path')
    if not filepath:
        return jsonify({'success': False, 'error': 'Ruta no especificada'})
    return jsonify(media_controller.play_local(filepath))


@app.route('/api/youtube', methods=['POST'])
def api_youtube():
    """Play YouTube video."""
    data = request.get_json()
    url = data.get('url')
    if not url:
        return jsonify({'success': False, 'error': 'URL no especificada'})
    return jsonify(media_controller.play_youtube(url))


@app.route('/api/monitor', methods=['POST'])
def api_monitor():
    """Start/stop monitor mode."""
    data = request.get_json()
    enabled = data.get('enabled', True)
    port = data.get('port', 1234)
    
    if enabled:
        return jsonify(media_controller.start_monitor_mode(port))
    else:
        return jsonify(media_controller.stop_monitor_mode())


@app.route('/api/control/<action>', methods=['POST'])
def api_control(action):
    """Playback controls."""
    if action == 'play_pause':
        return jsonify(media_controller.play_pause())
    elif action == 'stop':
        return jsonify(media_controller.stop())
    elif action == 'volume_up':
        return jsonify(media_controller.volume_up())
    elif action == 'volume_down':
        return jsonify(media_controller.volume_down())
    elif action == 'seek_forward':
        return jsonify(media_controller.seek(10))
    elif action == 'seek_backward':
        return jsonify(media_controller.seek(-10))
    else:
        return jsonify({'success': False, 'error': 'Acción no reconocida'})


@app.route('/api/loop', methods=['POST'])
def api_loop():
    """Set loop mode."""
    data = request.get_json()
    enabled = data.get('enabled', False)
    return jsonify(media_controller.set_loop(enabled))


@app.route('/api/upload', methods=['POST'])
def api_upload():
    """Upload file."""
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'No hay archivo en la petición'})
    
    file = request.files['file']
    result = library_manager.save_upload(file)
    
    if result['success']:
        socketio.emit('library_updated')
    
    return jsonify(result)


@app.route('/api/delete', methods=['POST'])
def api_delete():
    """Delete file."""
    data = request.get_json()
    relative_path = data.get('path')
    if not relative_path:
        return jsonify({'success': False, 'error': 'Ruta no especificada'})
    
    result = library_manager.delete_file(relative_path)
    
    if result['success']:
        socketio.emit('library_updated')
    
    return jsonify(result)


# ==============================================================================
# WEBSOCKET EVENTS
# ==============================================================================

@socketio.on('connect')
def handle_connect():
    """Handle client connection."""
    emit('status_update', media_controller.get_status())


@socketio.on('get_status')
def handle_get_status():
    """Handle status request."""
    emit('status_update', media_controller.get_status())


@socketio.on('get_library')
def handle_get_library():
    """Handle library request."""
    emit('library_data', library_manager.scan_library())


# ==============================================================================
# SIGNAL HANDLERS
# ==============================================================================

def cleanup(signum=None, frame=None):
    """Cleanup on exit."""
    print("\nLimpiando procesos...")
    media_controller.stop()
    sys.exit(0)

signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)


# ==============================================================================
# MAIN
# ==============================================================================

if __name__ == '__main__':
    print("=" * 60)
    print("  RetroCast RPI - Headless Multimedia Server")
    print("  Optimizado para Raspberry Pi Zero 2W")
    print("=" * 60)
    print(f"  Media Directory: {MEDIA_DIR}")
    print(f"  MPV Socket: {MPV_SOCKET}")
    print("=" * 60)
    
    # Ensure directories exist
    library_manager._ensure_media_dir()
    
    # Create templates directory if needed
    Path('templates').mkdir(exist_ok=True)
    Path('static').mkdir(exist_ok=True)
    
    # Show splash screen on startup (idle state)
    print("Mostrando splash screen inicial...")
    media_controller._show_splash()
    
    # Run server
    socketio.run(
        app,
        host='0.0.0.0',
        port=5000,
        debug=False,
        use_reloader=False,
        log_output=True,
        allow_unsafe_werkzeug=True
    )
