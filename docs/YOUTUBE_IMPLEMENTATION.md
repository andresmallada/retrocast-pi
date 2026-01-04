# Implementación de YouTube en RetroCast RPI

Guía técnica completa para reproducir vídeos de YouTube en una Raspberry Pi Zero 2W con salida de vídeo compuesto (PAL) a una TV CRT.

---

## Índice

1. [Arquitectura General](#arquitectura-general)
2. [Dependencias del Sistema](#dependencias-del-sistema)
3. [Configuración del Sistema](#configuración-del-sistema)
4. [Extracción de URLs con yt-dlp](#extracción-de-urls-con-yt-dlp)
5. [Reproducción con MPV](#reproducción-con-mpv)
6. [Configuración del Servicio Systemd](#configuración-del-servicio-systemd)
7. [Código Python Completo](#código-python-completo)
8. [Optimizaciones para Pi Zero 2W](#optimizaciones-para-pi-zero-2w)
9. [Solución de Problemas](#solución-de-problemas)

---

## Arquitectura General

```
┌─────────────────────────────────────────────────────────────────┐
│                        FLUJO DE DATOS                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  [Usuario]  →  [Flask API]  →  [yt-dlp]  →  [MPV]  →  [CRT TV] │
│     │              │              │           │          │      │
│   URL YouTube    /api/youtube   Extrae     Reproduce   Salida  │
│                                  URLs       stream    compuesta │
│                                 directas   de video    PAL     │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Componentes:

| Componente | Función |
|------------|---------|
| **Flask** | API REST que recibe peticiones del frontend |
| **yt-dlp** | Extrae URLs directas de streaming de YouTube |
| **MPV** | Reproductor multimedia con salida DRM/framebuffer |
| **DRM** | Direct Rendering Manager para acceso al framebuffer |

---

## Dependencias del Sistema

### Instalación de paquetes:

```bash
# Actualizar repositorios
sudo apt update

# Instalar MPV y dependencias de vídeo
sudo apt install -y mpv ffmpeg

# Instalar yt-dlp (versión más reciente desde pip)
sudo apt install -y python3-pip
pip3 install --break-system-packages yt-dlp

# Alternativa: instalar yt-dlp desde repositorios
sudo apt install -y yt-dlp
```

### Verificar instalación:

```bash
# Verificar yt-dlp
yt-dlp --version

# Verificar mpv
mpv --version

# Test básico de extracción
yt-dlp -f "best[height<=480]" -g --no-playlist "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
```

---

## Configuración del Sistema

### 1. Configuración de Boot (`/boot/firmware/config.txt`)

```ini
# Habilitar salida de vídeo compuesto
dtoverlay=vc4-kms-v3d,composite=1
enable_tvout=1

# Ignorar HDMI (forzar composite)
hdmi_ignore_hotplug=1

# Modo PAL (Europa)
sdtv_mode=2
sdtv_aspect=1

# Memoria GPU (necesaria para decodificación)
gpu_mem=128

# Desactivar overscan (ajustar según TV)
disable_overscan=1
```

### 2. Línea de comandos del kernel (`/boot/firmware/cmdline.txt`)

Añadir al final de la línea existente:
```
video=Composite-1:720x576@50p vc4.tv_norm=PAL
```

### 3. Permisos de usuario

```bash
# Añadir usuario al grupo video
sudo usermod -aG video pi

# Permisos para framebuffer
sudo chmod 666 /dev/fb0
sudo chmod 666 /dev/dri/card0
```

### 4. Deshabilitar getty en tty1 (opcional, si hay conflictos)

```bash
# Si mpv tiene problemas de acceso VT
sudo systemctl disable getty@tty1
```

---

## Extracción de URLs con yt-dlp

### Comando básico:

```bash
yt-dlp \
  -f 'bestvideo[height<=480]+bestaudio/best[height<=480]/best' \
  -g \
  --get-title \
  --no-playlist \
  --no-warnings \
  --no-check-certificates \
  --socket-timeout 15 \
  "URL_DE_YOUTUBE"
```

### Explicación de parámetros:

| Parámetro | Descripción |
|-----------|-------------|
| `-f 'bestvideo[height<=480]+bestaudio/best[height<=480]/best'` | Formato: video 480p + audio separados, o combinado si no hay |
| `-g` | Obtener URL directa del stream (no descargar) |
| `--get-title` | Obtener título del vídeo |
| `--no-playlist` | No procesar playlists, solo el vídeo individual |
| `--no-warnings` | Suprimir advertencias (reduce output) |
| `--no-check-certificates` | Omitir verificación SSL (más rápido) |
| `--socket-timeout 15` | Timeout de red de 15 segundos |

### Salida esperada:

```
Rick Astley - Never Gonna Give You Up
https://rr2---sn-xxx.googlevideo.com/videoplayback?expire=...
https://rr2---sn-xxx.googlevideo.com/videoplayback?expire=...
```

- Línea 1: Título del vídeo
- Línea 2: URL del stream de vídeo
- Línea 3: URL del stream de audio (si hay streams separados)

### Formato de selección explicado:

```
bestvideo[height<=480]+bestaudio/best[height<=480]/best
│                      │         │                  │
│                      │         │                  └─ Fallback final: cualquier formato
│                      │         └─ Fallback: mejor combinado ≤480p
│                      └─ Más (+) mejor audio disponible
└─ Mejor vídeo con altura máxima 480p
```

---

## Reproducción con MPV

### Comando para salida compuesta:

```bash
mpv \
  --vo=drm \
  --drm-connector=Composite-1 \
  --fs \
  --no-terminal \
  --no-osc \
  --no-config \
  --hwdec=auto \
  --cache=yes \
  --cache-secs=10 \
  --demuxer-max-bytes=50M \
  --video-sync=audio \
  --audio-device=auto \
  "URL_VIDEO" \
  --audio-file="URL_AUDIO"
```

### Explicación de parámetros MPV:

| Parámetro | Descripción |
|-----------|-------------|
| `--vo=drm` | Video output usando DRM (Direct Rendering Manager) |
| `--drm-connector=Composite-1` | Usar salida de vídeo compuesto |
| `--fs` | Pantalla completa |
| `--no-terminal` | Sin output en terminal |
| `--no-osc` | Sin On-Screen Controller (ahorra RAM) |
| `--no-config` | Ignorar archivos de configuración (inicio más rápido) |
| `--hwdec=auto` | Decodificación por hardware si está disponible |
| `--cache=yes` | Habilitar caché de stream |
| `--cache-secs=10` | Cachear 10 segundos |
| `--demuxer-max-bytes=50M` | Limitar memoria del demuxer |
| `--video-sync=audio` | Sincronizar vídeo con audio |
| `--audio-file=URL` | Archivo de audio separado (para streams separados) |

### Alternativa con openvt (si hay problemas de VT):

```bash
sudo openvt -f -s -c 1 -- mpv --vo=drm --drm-connector=Composite-1 --fs "URL"
```

---

## Configuración del Servicio Systemd

### Archivo `/etc/systemd/system/retrocast.service`:

```ini
[Unit]
Description=RetroCast RPI Multimedia Server
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/home/pi/retrocast
Environment=PATH=/home/pi/retrocast/venv/bin:/usr/local/bin:/usr/bin:/bin
Environment=HOME=/home/pi
ExecStart=/home/pi/retrocast/venv/bin/python /home/pi/retrocast/app.py
Restart=always
RestartSec=5

# CRÍTICO: Acceso TTY/Framebuffer para mpv
StandardInput=tty
StandardOutput=journal
StandardError=journal
TTYPath=/dev/tty1
TTYReset=yes
TTYVHangup=yes

# Límite de memoria para Pi Zero 2W
MemoryMax=256M

[Install]
WantedBy=multi-user.target
```

### Parámetros críticos explicados:

| Parámetro | Por qué es necesario |
|-----------|---------------------|
| `User=root` | Acceso completo a framebuffer y DRM |
| `StandardInput=tty` | MPV necesita stdin de TTY |
| `TTYPath=/dev/tty1` | Especifica qué TTY usar |
| `TTYReset=yes` | Resetear TTY al parar servicio |
| `TTYVHangup=yes` | Liberar TTY correctamente |

### Comandos de gestión:

```bash
# Recargar configuración
sudo systemctl daemon-reload

# Habilitar inicio automático
sudo systemctl enable retrocast

# Iniciar/parar/reiniciar
sudo systemctl start retrocast
sudo systemctl stop retrocast
sudo systemctl restart retrocast

# Ver logs
sudo journalctl -u retrocast -f
```

---

## Código Python Completo

### Función de reproducción de YouTube:

```python
import subprocess
import mimetypes
from typing import Dict, Any, List

MPV_SOCKET = '/tmp/mpvsocket'

class MediaController:
    
    def _get_mpv_base_args(self) -> List[str]:
        """Argumentos base de MPV optimizados para salida compuesta PAL."""
        return [
            'mpv',
            '--vo=drm',                    # Direct Rendering Manager
            '--drm-connector=Composite-1', # Salida compuesta
            '--fs',                        # Pantalla completa
            '--af=scaletempo',             # Mantener pitch en cambios de velocidad
            '--input-ipc-server=' + MPV_SOCKET,
            '--no-terminal',
            '--no-osc',
            '--no-config',
            '--cache=yes',
            '--cache-secs=10',
            '--demuxer-max-bytes=50M',
            '--hwdec=auto',
            '--video-sync=audio',
            '--audio-device=auto',
        ]
    
    def play_youtube(self, url: str) -> Dict[str, Any]:
        """Reproducir vídeo de YouTube usando yt-dlp + MPV."""
        
        # Matar procesos anteriores
        self._kill_all_media_processes()
        
        try:
            # Extraer URL del stream con yt-dlp
            result = subprocess.run(
                [
                    'yt-dlp',
                    '-f', 'bestvideo[height<=480]+bestaudio/best[height<=480]/best',
                    '-g',                        # Obtener URL directa
                    '--get-title',               # Obtener título
                    '--no-playlist',
                    '--no-warnings',
                    '--no-check-certificates',   # Más rápido
                    '--socket-timeout', '15',
                    '--cache-dir', '/tmp/yt-dlp-cache',
                    url
                ],
                capture_output=True,
                text=True,
                timeout=60  # 60 segundos máximo (Pi Zero es lento)
            )
            
            if result.returncode != 0:
                error_msg = result.stderr.strip() if result.stderr else 'Error extrayendo URL'
                return {'success': False, 'error': error_msg[:200]}
            
            # Parsear salida: primera línea es título, resto son URLs
            lines = result.stdout.strip().split('\n')
            title = lines[0] if lines else 'YouTube Video'
            stream_urls = [l for l in lines[1:] if l.startswith('http')]
            
            if not stream_urls:
                # Fallback: todas las líneas pueden ser URLs
                stream_urls = [l for l in lines if l.startswith('http')]
                title = 'YouTube Video'
            
            if not stream_urls:
                return {'success': False, 'error': 'No se pudo extraer URL'}
            
            # Construir comando MPV
            args = self._get_mpv_base_args()
            
            # Añadir URLs de stream (vídeo y audio si están separados)
            if len(stream_urls) >= 2:
                # Vídeo + audio separados
                args.extend([stream_urls[0], '--audio-file=' + stream_urls[1]])
            else:
                # Stream combinado
                args.append(stream_urls[0])
            
            # Iniciar reproducción
            self.current_process = subprocess.Popen(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            
            return {
                'success': True, 
                'type': 'youtube', 
                'title': title,
                'url': url
            }
            
        except subprocess.TimeoutExpired:
            return {'success': False, 'error': 'Timeout extrayendo vídeo (>60s)'}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def _kill_all_media_processes(self):
        """Matar todos los procesos de reproducción anteriores."""
        for proc in ['mpv', 'fbi', 'vlc']:
            try:
                subprocess.run(
                    ['pkill', '-9', proc],
                    stderr=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL
                )
            except Exception:
                pass
```

---

## Optimizaciones para Pi Zero 2W

### Limitaciones del hardware:

| Recurso | Límite |
|---------|--------|
| RAM | 512 MB total |
| CPU | 4 cores ARM Cortex-A53 @ 1GHz |
| GPU | VideoCore IV |

### Optimizaciones aplicadas:

1. **Resolución máxima 480p**: Reduce carga de CPU/GPU
   ```python
   '-f', 'bestvideo[height<=480]+bestaudio/best[height<=480]/best'
   ```

2. **Caché limitado**: Evita llenar RAM
   ```bash
   --cache-secs=10
   --demuxer-max-bytes=50M
   ```

3. **Decodificación hardware**: Usa GPU cuando es posible
   ```bash
   --hwdec=auto
   ```

4. **Sin interfaz gráfica**: MPV sin OSC ahorra RAM
   ```bash
   --no-osc
   --no-terminal
   ```

5. **Timeout generoso**: Pi Zero es lento para yt-dlp
   ```python
   timeout=60  # segundos
   ```

6. **Caché de yt-dlp**: Acelera consultas repetidas
   ```bash
   --cache-dir /tmp/yt-dlp-cache
   ```

---

## Solución de Problemas

### Problema: "No primary DRM device could be picked"

**Causa**: MPV no puede acceder al framebuffer/DRM.

**Soluciones**:
```bash
# 1. Verificar permisos
sudo chmod 666 /dev/dri/card0

# 2. Verificar que el servicio tiene acceso TTY
# En retrocast.service:
StandardInput=tty
TTYPath=/dev/tty1

# 3. Usar openvt para forzar acceso VT
sudo openvt -f -s -c 1 -- mpv --vo=drm ...
```

### Problema: "Timeout extrayendo vídeo"

**Causa**: Pi Zero es lento o conexión de red mala.

**Soluciones**:
```python
# Aumentar timeout
timeout=120  # 2 minutos

# Usar formato más simple (sin streams separados)
'-f', 'best[height<=360]'
```

### Problema: Vídeo sin audio

**Causa**: Streams de vídeo y audio están separados.

**Solución**:
```python
# Verificar que se pasan ambas URLs
if len(stream_urls) >= 2:
    args.extend([stream_urls[0], '--audio-file=' + stream_urls[1]])
```

### Problema: Pantalla negra

**Causa**: DRM connector incorrecto o deshabilitado.

**Soluciones**:
```bash
# Verificar conectores disponibles
ls /sys/class/drm/

# Verificar estado del composite
cat /sys/class/drm/card0-Composite-1/status
cat /sys/class/drm/card0-Composite-1/enabled

# Forzar modo en cmdline.txt
video=Composite-1:720x576@50p
```

### Problema: Franjas negras arriba/abajo

**Causa**: Aspect ratio incorrecto.

**Solución**:
```bash
# Forzar 4:3 en MPV
--video-aspect-override=4:3
```

---

## Verificación Rápida

Script de prueba completo:

```bash
#!/bin/bash
# test_youtube.sh - Verificar que todo funciona

echo "=== Test YouTube RetroCast ==="

# 1. Verificar yt-dlp
echo -n "yt-dlp: "
yt-dlp --version && echo "OK" || echo "FALLO"

# 2. Verificar mpv
echo -n "mpv: "
mpv --version | head -1 && echo "OK" || echo "FALLO"

# 3. Verificar DRM
echo -n "DRM Composite: "
cat /sys/class/drm/card0-Composite-1/status

# 4. Test extracción
echo "Extrayendo URL de prueba..."
URL=$(yt-dlp -f 'best[height<=480]' -g --no-playlist \
  "https://www.youtube.com/watch?v=dQw4w9WgXcQ" 2>/dev/null | head -1)

if [ -n "$URL" ]; then
    echo "URL extraída: ${URL:0:50}..."
    echo "Reproduciendo 5 segundos..."
    timeout 5 mpv --vo=drm --drm-connector=Composite-1 --fs --no-terminal "$URL"
    echo "Test completado"
else
    echo "FALLO: No se pudo extraer URL"
fi
```

---

## Resumen

| Componente | Configuración Clave |
|------------|---------------------|
| **yt-dlp** | `-f 'bestvideo[height<=480]+bestaudio/best[height<=480]'`, timeout 60s |
| **MPV** | `--vo=drm --drm-connector=Composite-1 --fs` |
| **Systemd** | `User=root`, `StandardInput=tty`, `TTYPath=/dev/tty1` |
| **Boot** | `dtoverlay=vc4-kms-v3d,composite=1`, `enable_tvout=1` |
| **Cmdline** | `video=Composite-1:720x576@50p vc4.tv_norm=PAL` |

---

*Documentación generada para RetroCast RPI - Headless Multimedia Server*
