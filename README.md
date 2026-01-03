# 📺 RetroCast RPI - Headless Multimedia Server

Servidor multimedia sin interfaz gráfica para Raspberry Pi Zero 2W conectada por vídeo compuesto (PAL) a una TV CRT. Optimizado para 512MB de RAM.

## 🎯 Características

- **Reproducción Local**: Vídeo, audio e imágenes desde biblioteca local
- **YouTube Casting**: Streaming de YouTube limitado a 480p para optimizar CPU
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
2. Desde VLC en tu PC:
   - Medio → Emitir → Selecciona archivo
   - Destino: UDP → [IP_DEL_PI]:1234
   - Códec: H.264 + MP3 (para compatibilidad)

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

El script configura automáticamente `/boot/config.txt` (o `/boot/firmware/config.txt`) para salida PAL:

| Parámetro | Valor | Descripción |
|-----------|-------|-------------|
| `dtoverlay` | `vc4-kms-v3d,composite=1` | Driver KMS con salida compuesta |
| `enable_tvout` | 1 | Habilita salida compuesta |
| `sdtv_mode` | 2 | PAL (usar 0 para NTSC) |
| `sdtv_aspect` | 1 | Aspect ratio 4:3 |
| `disable_overscan` | 1 | Desactiva overscan |
| `gpu_mem` | 128 | Memoria GPU para vídeo |

> **Nota**: El driver `vc4-kms-v3d` con `composite=1` es requerido en versiones modernas de Raspberry Pi OS para la salida de vídeo compuesto.

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
1. Verifica que `/boot/config.txt` tenga `dtoverlay=vc4-kms-v3d,composite=1`
2. Verifica que tenga `enable_tvout=1`
3. Reinicia el Pi
4. Prueba diferentes valores de `sdtv_mode` (0=NTSC, 2=PAL)

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

El sistema está optimizado para 512MB de RAM:
- Sin X11/escritorio
- MPV con caché limitado (10 segundos, 50MB demuxer)
- YouTube máximo 480p con caché en `/tmp/yt-dlp-cache`
- Swappiness reducido a 10
- Límite de memoria del servicio: 200MB
- CPUQuota: 80%
- Backend asíncrono con eventlet (menor overhead que threading)

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
