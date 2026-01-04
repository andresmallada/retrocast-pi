# 📺 RetroCast RPI - Headless Multimedia Server

Servidor multimedia sin interfaz gráfica para Raspberry Pi Zero 2W conectada por vídeo compuesto (PAL) a una TV CRT. Optimizado para 512MB de RAM.

## 🎯 Características

- **Reproducción Local**: Vídeo, audio e imágenes desde biblioteca local
- **YouTube Casting**: Streaming de YouTube limitado a 360p para optimizar CPU
- **Modo Monitor**: Recepción de streams UDP/RTP desde VLC u otros emisores
- **Splash Screen**: Imagen de espera en estado idle (no pantalla negra)
- **Interfaz Web Retro**: SPA con estética dark mode, touch-friendly
- **Compartición Samba**: Acceso a la biblioteca desde Windows/Mac/Linux
- **Control en Tiempo Real**: WebSocket (eventlet) para actualizaciones instantáneas
- **Watchdog**: Detección automática de procesos huérfanos/caídos

## 📋 Requisitos

- Raspberry Pi Zero 2W (o superior)
- Raspberry Pi OS Lite (sin escritorio)
- Cable de vídeo compuesto
- TV CRT con entrada de vídeo compuesto
- Conexión a red (WiFi o Ethernet via USB)

## 🚀 Instalación Rápida

```bash
# 1. Clonar o copiar archivos al Pi
scp -r ./* pi@raspberrypi.local:/home/pi/retrocast/

# 2. Conectar por SSH
ssh pi@raspberrypi.local

# 3. Ejecutar instalador
cd /home/pi/retrocast
chmod +x setup.sh
sudo ./setup.sh
```

## 📁 Estructura del Proyecto

```
retrocast-rpi/
├── app.py              # Backend Flask + SocketIO
├── setup.sh            # Script de instalación
├── requirements.txt    # Dependencias Python
├── config.txt.example  # Configuración de boot
├── README.md           # Esta documentación
└── templates/
    └── index.html      # Frontend SPA
```

## 🎮 Uso

### Interfaz Web
Accede desde cualquier dispositivo en tu red local:
```
http://[IP_DEL_PI]:5000
```

### Carpeta Compartida Samba
Desde Windows:
```
\\raspberrypi\CRT_Media
```

Desde Mac/Linux:
```
smb://raspberrypi/CRT_Media
```

> ⚠️ **Advertencia de Seguridad**: La carpeta Samba está configurada con acceso de invitado (`guest ok = yes`) para facilitar el uso en redes domésticas. Cualquier dispositivo en la red local puede leer, escribir y eliminar archivos. **No exponer este servicio a redes públicas o no confiables.**

### Modo Monitor (Recibir Stream)
1. Activa "Modo Monitor" en la interfaz web
2. Desde VLC en tu PC, configura el streaming (ver sección detallada abajo)

## 📡 Streaming desde VLC

Para enviar video desde tu PC a la TV CRT via RetroCast:

### Configuración en VLC (GUI)

1. **Menú:** `Media` → `Stream...` (o `Ctrl+S`)
2. **Añadir** el archivo de video → Click **Stream** → **Next**
3. **Destino:** Selecciona `UDP (legacy)` → **Add**
4. **Configuración:**
   - **Dirección:** `[IP_DEL_PI]` (ej: 192.168.0.105)
   - **Puerto:** `1234`
5. **Transcoding** (importante para Pi Zero 2W):
   - Activa **Activate Transcoding**
   - Perfil: `Video - H.264 + MP3 (MP4)`
   - Click en el **icono de llave** para editar:
     - **Video codec:** H.264
     - **Bitrate:** 1000-1500 kb/s
     - **Resolución:** 640x480 o menor
     - **Frame rate:** 25 fps (PAL)
6. Click **Next** → **Stream**

### Alternativa por línea de comandos

```bash
vlc video.mp4 --sout '#transcode{vcodec=h264,vb=1200,scale=0.5,fps=25,acodec=none}:udp{dst=192.168.0.105:1234}'
```

### Configuración recomendada para fluidez

| Parámetro | Valor | Notas |
|-----------|-------|-------|
| Codec | H.264 | Compatible con hardware decoding |
| Bitrate | 1000-1500 kbps | Menor = más fluido |
| Resolución | 480p o menor | 720x576 máximo para PAL |
| FPS | 25 | Estándar PAL |
| Audio | Desactivado | No hay interfaz de audio en Pi Zero 2W |

## ⚙️ Comandos de Servicio

```bash
# Iniciar servidor
sudo systemctl start retrocast

# Detener servidor
sudo systemctl stop retrocast

# Ver estado
sudo systemctl status retrocast

# Ver logs en tiempo real
journalctl -u retrocast -f

# Reiniciar servicio
sudo systemctl restart retrocast
```

## 🔧 Configuración de Vídeo

El script configura automáticamente los archivos de boot para salida PAL.

### config.txt

| Parámetro | Valor | Descripción |
|-----------|-------|-------------|
| `dtoverlay` | `vc4-kms-v3d,composite=1` | Driver KMS con salida compuesta |
| `enable_tvout` | 1 | Habilita salida compuesta |
| `sdtv_aspect` | 1 | Aspect ratio 4:3 |
| `hdmi_ignore_hotplug` | 1 | **CRÍTICO**: Fuerza salida compuesta |
| `disable_overscan` | 1 | Desactiva overscan |
| `gpu_mem` | 128 | Memoria GPU para vídeo |

### cmdline.txt

El script añade estos parámetros **esenciales** al final de la línea:

```
video=Composite-1:720x576@50ie vc4.tv_norm=PAL
```

> ⚠️ **IMPORTANTE**: Sin estos parámetros en cmdline.txt, el driver DRM no detectará el conector compuesto y no habrá salida de video.

### Servicio systemd

El servicio requiere acceso TTY para que MPV pueda usar DRM:

```ini
StandardInput=tty
TTYPath=/dev/tty1
TTYReset=yes
TTYVHangup=yes
```

## 🎬 Formatos Soportados

### Vídeo
MP4, MKV, AVI, MOV, WMV, FLV, WebM, MPEG, 3GP

### Audio
MP3, WAV, FLAC, AAC, OGG, M4A, WMA, Opus

### Imágenes
JPG, PNG, GIF, BMP, WebP, TIFF

## 🔌 API REST

| Endpoint | Método | Descripción |
|----------|--------|-------------|
| `/api/status` | GET | Estado actual |
| `/api/library` | GET | Lista biblioteca |
| `/api/play` | POST | Reproducir archivo local |
| `/api/youtube` | POST | Reproducir URL YouTube |
| `/api/monitor` | POST | Activar/desactivar monitor |
| `/api/control/<action>` | POST | Controles (play_pause, stop, volume_up, etc.) |
| `/api/upload` | POST | Subir archivo |
| `/api/delete` | POST | Eliminar archivo |

## 🖼️ Splash Screen

El sistema muestra automáticamente una imagen de espera (`splash.png`) en estado idle:

- **Al iniciar** el servicio
- **Al detener** la reproducción
- **Al terminar** un vídeo/audio
- **Al desactivar** el modo monitor

Esto evita que se muestre la consola de texto o una pantalla negra cuando no hay contenido reproduciéndose.

La imagen splash se genera automáticamente durante la instalación (720x576 PAL).

## 🐛 Solución de Problemas

### No hay vídeo en la TV
1. Verifica `/boot/config.txt`:
   - `dtoverlay=vc4-kms-v3d,composite=1`
   - `enable_tvout=1`
   - `hdmi_ignore_hotplug=1`
2. Verifica `/boot/cmdline.txt` contenga al final:
   - `video=Composite-1:720x576@50ie vc4.tv_norm=PAL`
3. Reinicia el Pi
4. Para NTSC, cambia `vc4.tv_norm=NTSC` y resolución a `720x480@60ie`

### YouTube no funciona
1. Actualiza yt-dlp: `pip3 install -U yt-dlp`
2. Verifica conexión a Internet

### Sin audio
1. Verifica: `aplay -l`
2. Configura salida de audio: `sudo raspi-config` → Audio

### Error de memoria
1. Cierra otras aplicaciones
2. Reduce `gpu_mem` a 64 en config.txt
3. Aumenta swap si es necesario

## 📊 Optimización de Memoria

El sistema está optimizado para Pi Zero 2W (512MB RAM):
- Sin X11/escritorio
- MPV con caché limitado (10 segundos, 50MB demuxer)
- YouTube máximo 360p (optimizado para CPU limitada)
- Escalado automático a 720x576 PAL (reduce carga de CPU)
- Swappiness reducido a 10
- Límite de memoria del servicio: 200MB
- CPUQuota: 80%
- Backend asíncrono con gevent
- Frame dropping habilitado para videos pesados

## 🔒 Seguridad

- **Validación de rutas**: Los archivos solo pueden reproducirse desde `/home/pi/media`
- **Sin ejecución como root**: El servicio corre como usuario `pi`
- **Samba local**: Acceso de invitado solo en red local (ver advertencia arriba)

## 📜 Licencia

MIT License - Usa libremente este proyecto.

## 🤝 Contribuciones

¡Contribuciones bienvenidas! Por favor abre un issue o pull request.

---

**RetroCast RPI** - *Revive tu CRT con tecnología moderna* 📺✨
