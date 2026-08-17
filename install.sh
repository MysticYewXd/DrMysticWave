#!/bin/bash
# Funk Check — installer for Ubuntu 24.04
# Installs dependencies and sets up a desktop launcher.
set -e

echo "==> Installing system dependencies (ffmpeg, python3-tk)..."
sudo apt update
sudo apt install -y ffmpeg python3-tk python3-pip

echo "==> Installing Python libraries..."
pip install --break-system-packages --user numpy matplotlib

# Install location
APPDIR="$HOME/.local/share/funkcheck"
mkdir -p "$APPDIR"
cp analyzer.py funkcheck.py "$APPDIR/"
chmod +x "$APPDIR/funkcheck.py"

# CLI launcher on PATH
mkdir -p "$HOME/.local/bin"
cat > "$HOME/.local/bin/funkcheck" << EOF
#!/bin/bash
exec python3 "$APPDIR/funkcheck.py" "\$@"
EOF
chmod +x "$HOME/.local/bin/funkcheck"

# Desktop entry (shows up in your app menu)
mkdir -p "$HOME/.local/share/applications"
cat > "$HOME/.local/share/applications/funkcheck.desktop" << EOF
[Desktop Entry]
Name=Funk Check
Comment=Detect fake FLAC / check real audio format
Exec=python3 $APPDIR/funkcheck.py --gui
Icon=audio-x-generic
Terminal=false
Type=Application
Categories=AudioVideo;Audio;
EOF

echo ""
echo "==> Done!"
echo "   GUI:  search 'Funk Check' in your apps, or run:  funkcheck --gui"
echo "   CLI:  funkcheck ~/Music"
echo ""
echo "If 'funkcheck' isn't found, add ~/.local/bin to PATH:"
echo '   echo "export PATH=\$HOME/.local/bin:\$PATH" >> ~/.bashrc && source ~/.bashrc'
