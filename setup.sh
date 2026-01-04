#!/bin/bash
#===============================================================================
# RetroCast RPI - Setup Script
# Headless Multimedia Server for Raspberry Pi Zero 2W
# Composite Video (PAL) Output to CRT TV
#===============================================================================

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
INSTALL_DIR="/home/pi/retrocast"
MEDIA_DIR="/home/pi/media"
SAMBA_SHARE_NAME="CRT_Media"
SERVICE_NAME="retrocast"

#===============================================================================
# FUNCTIONS
#===============================================================================

print_header() {
    echo -e "${BLUE}"
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║                     RETROCAST RPI                            ║"
    echo "║            Headless Multimedia Server Setup                  ║"
    echo "║              Raspberry Pi Zero 2W + CRT                      ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

print_step() {
    echo -e "${GREEN}[✓]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[!]${NC} $1"
}

print_error() {
    echo -e "${RED}[✗]${NC} $1"
}

check_root() {
    if [ "$EUID" -ne 0 ]; then
        print_error "Este script debe ejecutarse como root (sudo)"
        exit 1
    fi
}

check_pi() {
    if ! grep -q "Raspberry Pi" /proc/cpuinfo 2>/dev/null; then
        print_warning "Este sistema no parece ser una Raspberry Pi"
        read -p "¿Continuar de todos modos? (s/n): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Ss]$ ]]; then
            exit 1
        fi
    fi
}

#===============================================================================
# SYSTEM CONFIGURATION
#===============================================================================

configure_boot() {
    print_step "Configurando boot/config.txt para salida PAL..."
    
    CONFIG_FILE="/boot/config.txt"
    CMDLINE_FILE="/boot/cmdline.txt"
    if [ -f "/boot/firmware/config.txt" ]; then
        CONFIG_FILE="/boot/firmware/config.txt"
        CMDLINE_FILE="/boot/firmware/cmdline.txt"
    fi
    
    # Backup original config
    cp "$CONFIG_FILE" "${CONFIG_FILE}.backup.$(date +%Y%m%d%H%M%S)"
    cp "$CMDLINE_FILE" "${CMDLINE_FILE}.backup.$(date +%Y%m%d%H%M%S)"
    
    # Configure DRM/KMS driver with composite output
    # Remove any existing vc4 dtoverlay and add the correct one
    if grep -q "^dtoverlay=vc4" "$CONFIG_FILE"; then
        sed -i 's/^dtoverlay=vc4.*$/dtoverlay=vc4-kms-v3d,composite=1/' "$CONFIG_FILE"
        print_step "dtoverlay actualizado a vc4-kms-v3d,composite=1"
    else
        echo "" >> "$CONFIG_FILE"
        echo "# RetroCast RPI - DRM/KMS with Composite Output" >> "$CONFIG_FILE"
        echo "dtoverlay=vc4-kms-v3d,composite=1" >> "$CONFIG_FILE"
    fi
    
    # Enable composite video output
    if ! grep -q "^enable_tvout=1" "$CONFIG_FILE"; then
        echo "" >> "$CONFIG_FILE"
        echo "# RetroCast RPI - Composite Video Output" >> "$CONFIG_FILE"
        echo "enable_tvout=1" >> "$CONFIG_FILE"
    fi
    
    # Set 4:3 aspect ratio
    if ! grep -q "^sdtv_aspect=1" "$CONFIG_FILE"; then
        echo "sdtv_aspect=1" >> "$CONFIG_FILE"  # 4:3
    fi
    
    # CRITICAL: Ignore HDMI to force composite output
    if ! grep -q "^hdmi_ignore_hotplug=1" "$CONFIG_FILE"; then
        echo "hdmi_ignore_hotplug=1" >> "$CONFIG_FILE"
    fi
    
    # Disable overscan
    if ! grep -q "^disable_overscan=1" "$CONFIG_FILE"; then
        echo "disable_overscan=1" >> "$CONFIG_FILE"
    fi
    
    # GPU memory allocation (optimize for video playback)
    if ! grep -q "^gpu_mem=" "$CONFIG_FILE"; then
        echo "gpu_mem=128" >> "$CONFIG_FILE"
    fi
    
    # CRITICAL: Configure cmdline.txt for PAL composite output
    # This is essential for DRM to use the composite connector
    if ! grep -q "video=Composite-1" "$CMDLINE_FILE"; then
        # Append video parameters to the single line in cmdline.txt
        sed -i 's/$/ video=Composite-1:720x576@50ie vc4.tv_norm=PAL/' "$CMDLINE_FILE"
        print_step "cmdline.txt configurado para salida PAL 720x576"
    fi
    
    print_step "Configuración de vídeo completada"
}

#===============================================================================
# PACKAGE INSTALLATION
#===============================================================================

install_packages() {
    print_step "Actualizando repositorios..."
    apt-get update -qq
    
    print_step "Instalando dependencias del sistema..."
    apt-get install -y -qq \
        mpv \
        fbi \
        samba \
        samba-common-bin \
        python3-pip \
        python3-venv \
        git \
        ffmpeg \
        libffi-dev \
        libssl-dev \
        libjpeg-dev \
        zlib1g-dev
    
    print_step "Instalando yt-dlp..."
    # Install yt-dlp (latest version)
    pip3 install --break-system-packages yt-dlp 2>/dev/null || pip3 install yt-dlp
    
    # Create symlink if needed
    if [ ! -f "/usr/local/bin/yt-dlp" ] && [ -f "/home/pi/.local/bin/yt-dlp" ]; then
        ln -sf /home/pi/.local/bin/yt-dlp /usr/local/bin/yt-dlp
    fi
    
    print_step "Paquetes del sistema instalados"
}

install_python_deps() {
    print_step "Instalando dependencias de Python..."
    
    # Create virtual environment
    python3 -m venv "${INSTALL_DIR}/venv"
    
    # Activate and install
    source "${INSTALL_DIR}/venv/bin/activate"
    
    pip install --upgrade pip
    pip install \
        flask \
        flask-socketio \
        gevent \
        gevent-websocket \
        werkzeug
    
    deactivate
    
    print_step "Dependencias de Python instaladas"
}

#===============================================================================
# DIRECTORY SETUP
#===============================================================================

setup_directories() {
    print_step "Creando estructura de directorios..."
    
    # Create media directories
    mkdir -p "${MEDIA_DIR}/videos"
    mkdir -p "${MEDIA_DIR}/music"
    mkdir -p "${MEDIA_DIR}/photos"
    
    # Create install directory
    mkdir -p "${INSTALL_DIR}/templates"
    mkdir -p "${INSTALL_DIR}/static"
    
    # Set permissions
    chown -R pi:pi "${MEDIA_DIR}"
    chown -R pi:pi "${INSTALL_DIR}"
    chmod -R 755 "${MEDIA_DIR}"
    
    print_step "Directorios creados"
}

#===============================================================================
# SAMBA CONFIGURATION
#===============================================================================

configure_samba() {
    print_step "Configurando Samba..."
    
    # Backup original config
    if [ -f /etc/samba/smb.conf ]; then
        cp /etc/samba/smb.conf /etc/samba/smb.conf.backup.$(date +%Y%m%d%H%M%S)
    fi
    
    # Create Samba config
    cat > /etc/samba/smb.conf << EOF
[global]
   workgroup = WORKGROUP
   server string = RetroCast RPI Media Server
   security = user
   map to guest = Bad User
   dns proxy = no
   
   # Performance optimizations for Pi Zero 2W
   socket options = TCP_NODELAY IPTOS_LOWDELAY
   read raw = yes
   write raw = yes
   max xmit = 65535
   dead time = 15
   getwd cache = yes

[${SAMBA_SHARE_NAME}]
   path = ${MEDIA_DIR}
   browseable = yes
   read only = no
   guest ok = yes
   create mask = 0755
   directory mask = 0755
   force user = pi
   force group = pi
   comment = RetroCast Media Library
EOF

    # Restart Samba
    systemctl restart smbd
    systemctl enable smbd
    
    print_step "Samba configurado - Carpeta compartida: \\\\$(hostname)\\${SAMBA_SHARE_NAME}"
}

#===============================================================================
# SYSTEMD SERVICE
#===============================================================================

create_service() {
    print_step "Creando servicio systemd..."
    
    cat > /etc/systemd/system/${SERVICE_NAME}.service << EOF
[Unit]
Description=RetroCast RPI Multimedia Server
After=network.target

[Service]
Type=simple
User=pi
Group=pi
WorkingDirectory=${INSTALL_DIR}
Environment=PATH=${INSTALL_DIR}/venv/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=${INSTALL_DIR}/venv/bin/python ${INSTALL_DIR}/app.py
Restart=always
RestartSec=5

# TTY access for DRM video output
StandardInput=tty
TTYPath=/dev/tty1
TTYReset=yes
TTYVHangup=yes

# Memory optimization for Pi Zero 2W
MemoryMax=200M
CPUQuota=80%

[Install]
WantedBy=multi-user.target
EOF

    # Reload systemd
    systemctl daemon-reload
    systemctl enable ${SERVICE_NAME}
    
    print_step "Servicio systemd creado y habilitado"
}

#===============================================================================
# COPY APPLICATION FILES
#===============================================================================

copy_app_files() {
    print_step "Copiando archivos de aplicación..."
    
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    
    # Copy main application
    if [ -f "${SCRIPT_DIR}/app.py" ]; then
        cp "${SCRIPT_DIR}/app.py" "${INSTALL_DIR}/app.py"
    fi
    
    # Copy templates
    if [ -f "${SCRIPT_DIR}/templates/index.html" ]; then
        cp "${SCRIPT_DIR}/templates/index.html" "${INSTALL_DIR}/templates/index.html"
    fi
    
    # Create splash screen
    create_splash_screen
    
    # Set permissions
    chown -R pi:pi "${INSTALL_DIR}"
    
    print_step "Archivos copiados"
}

#===============================================================================
# SPLASH SCREEN
#===============================================================================

create_splash_screen() {
    print_step "Creando splash screen..."
    
    # Create a simple splash image using ImageMagick if available
    if command -v convert &> /dev/null; then
        convert -size 720x576 xc:black \
            -font "DejaVu-Sans-Mono-Bold" \
            -pointsize 48 \
            -fill "#39ff14" \
            -gravity center \
            -annotate 0 "RETROCAST RPI\n\nEsperando stream..." \
            "${INSTALL_DIR}/splash.png"
    else
        # Install ImageMagick for proper PNG generation
        print_warning "Instalando ImageMagick para splash screen..."
        apt-get install -y -qq imagemagick
        if command -v convert &> /dev/null; then
            convert -size 720x576 xc:black \
                -font "DejaVu-Sans-Mono-Bold" \
                -pointsize 48 \
                -fill "#39ff14" \
                -gravity center \
                -annotate 0 "RETROCAST RPI\n\nEsperando stream..." \
                "${INSTALL_DIR}/splash.png"
        else
            # Fallback: create minimal valid PNG using ffmpeg (already installed)
            print_warning "Creando splash básico con ffmpeg..."
            ffmpeg -f lavfi -i color=black:s=720x576:d=1 -frames:v 1 \
                -y "${INSTALL_DIR}/splash.png" 2>/dev/null || true
        fi
    fi
}

#===============================================================================
# CONSOLE CONFIGURATION
#===============================================================================

configure_console() {
    print_step "Configurando consola para framebuffer..."
    
    # Disable console blanking
    if ! grep -q "consoleblank=0" /boot/cmdline.txt 2>/dev/null; then
        sed -i 's/$/ consoleblank=0/' /boot/cmdline.txt 2>/dev/null || true
    fi
    
    # Set console font size for CRT
    if [ -f /etc/default/console-setup ]; then
        sed -i 's/FONTSIZE=.*/FONTSIZE="8x16"/' /etc/default/console-setup
    fi
}

#===============================================================================
# MEMORY OPTIMIZATION
#===============================================================================

optimize_memory() {
    print_step "Optimizando uso de memoria..."
    
    # Disable swap if low memory situation
    # (Actually keep minimal swap for stability)
    
    # Set swappiness low
    if ! grep -q "vm.swappiness" /etc/sysctl.conf; then
        echo "vm.swappiness=10" >> /etc/sysctl.conf
    fi
    
    # Reduce kernel logging
    if ! grep -q "kernel.printk" /etc/sysctl.conf; then
        echo "kernel.printk = 3 3 3 3" >> /etc/sysctl.conf
    fi
    
    # Apply settings
    sysctl -p 2>/dev/null || true
    
    print_step "Optimizaciones de memoria aplicadas"
}

#===============================================================================
# FINALIZATION
#===============================================================================

print_summary() {
    IP_ADDR=$(hostname -I | awk '{print $1}')
    
    echo ""
    echo -e "${GREEN}╔══════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║              INSTALACIÓN COMPLETADA                          ║${NC}"
    echo -e "${GREEN}╚══════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "  ${BLUE}Interfaz Web:${NC}     http://${IP_ADDR}:5000"
    echo -e "  ${BLUE}Carpeta Samba:${NC}    \\\\$(hostname)\\${SAMBA_SHARE_NAME}"
    echo -e "  ${BLUE}Puerto Monitor:${NC}   UDP ${IP_ADDR}:1234"
    echo ""
    echo -e "  ${YELLOW}Comandos útiles:${NC}"
    echo "    sudo systemctl start ${SERVICE_NAME}    # Iniciar servidor"
    echo "    sudo systemctl stop ${SERVICE_NAME}     # Detener servidor"
    echo "    sudo systemctl status ${SERVICE_NAME}   # Ver estado"
    echo "    journalctl -u ${SERVICE_NAME} -f        # Ver logs"
    echo ""
    echo -e "  ${YELLOW}Ubicación de archivos:${NC}"
    echo "    Aplicación:   ${INSTALL_DIR}"
    echo "    Multimedia:   ${MEDIA_DIR}"
    echo ""
    echo -e "${RED}¡REINICIAR para aplicar cambios de vídeo!${NC}"
    echo ""
    read -p "¿Reiniciar ahora? (s/n): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Ss]$ ]]; then
        reboot
    fi
}

#===============================================================================
# MAIN
#===============================================================================

main() {
    print_header
    
    check_root
    check_pi
    
    echo -e "${YELLOW}Iniciando instalación...${NC}"
    echo ""
    
    # Run installation steps
    configure_boot
    install_packages
    setup_directories
    install_python_deps
    copy_app_files
    configure_samba
    configure_console
    optimize_memory
    create_service
    
    print_summary
}

# Run main function
main "$@"
