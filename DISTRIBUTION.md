# Distribution Guide

This document explains how Paranoid is distributed across multiple platforms and how to install it in different environments.

## Distribution Channels

Paranoid v1.0.0 is available through four distribution channels:

### 1. PyPI (Python Package Index)

**Package name:** `paranoid-cli`

**Installation:**
```bash
pip install paranoid-cli
```

**Pros:**
- Universal installation method
- Works on all platforms (Linux, macOS, Windows)
- Easy to update: `pip install --upgrade paranoid-cli`
- Integrates with Python virtual environments

**Cons:**
- Requires Python 3.12+ installed
- Requires pip/setuptools

**Best for:**
- Python developers
- Users with existing Python environments
- CI/CD pipelines with Python
- Development and testing

### 2. Docker Hub

**Image name:** `yourusername/paranoid`

**Tags:**
- `latest` - Most recent release
- `v1.0.0` - Specific version
- `v1.0` - Minor version
- `v1` - Major version

**Multi-arch support:** amd64, arm64

**Installation:**
```bash
docker pull yourusername/paranoid:latest
```

**Usage:**
```bash
docker run --rm \
  -v $(pwd):/workspace \
  -e ANTHROPIC_API_KEY=sk-ant-xxx \
  yourusername/paranoid:latest \
  paranoid run /workspace/system.md
```

**Pros:**
- No Python installation required
- Isolated environment
- Consistent behavior across platforms
- Multi-arch support (x86_64, ARM64)

**Cons:**
- Requires Docker installed
- Slightly more complex command syntax
- Larger download size (~500MB)

**Best for:**
- Production deployments
- Containerized environments
- Kubernetes/cloud deployments
- Users without Python

### 3. Standalone Binaries

**Available platforms:**
- Linux x86_64: `paranoid-linux-x64`
- macOS ARM64: `paranoid-macos-arm64` (Apple Silicon)
- Windows x64: `paranoid-windows-x64.exe`

**Download from:** [GitHub Releases](https://github.com/yourusername/paranoid/releases/latest)

**Installation:**

**Linux:**
```bash
wget https://github.com/yourusername/paranoid/releases/latest/download/paranoid-linux-x64
chmod +x paranoid-linux-x64
sudo mv paranoid-linux-x64 /usr/local/bin/paranoid
paranoid --version
```

**macOS:**
```bash
curl -L -o paranoid https://github.com/yourusername/paranoid/releases/latest/download/paranoid-macos-arm64
chmod +x paranoid
sudo mv paranoid /usr/local/bin/
paranoid --version
```

**Windows:**
1. Download `paranoid-windows-x64.exe` from releases
2. Rename to `paranoid.exe`
3. Add to PATH or run from current directory
4. Run: `paranoid.exe --version`

**Pros:**
- No Python or Docker required
- Single executable file
- Fast startup
- Portable (can copy to USB drive)

**Cons:**
- Platform-specific (must download correct version)
- Larger file size (~40-60MB)
- Manual updates required

**Best for:**
- End users without development background
- Air-gapped/offline environments
- Quick demos and presentations
- Systems without Python

### 4. From Source

**Repository:** `https://github.com/yourusername/paranoid`

**Installation:**
```bash
git clone https://github.com/yourusername/paranoid
cd paranoid
pip install -e .
```

**Pros:**
- Full access to source code
- Can modify and customize
- Latest development version
- Easy to contribute

**Cons:**
- Requires Git, Python, and build tools
- More complex setup
- May have unreleased bugs

**Best for:**
- Contributors and developers
- Testing unreleased features
- Custom modifications
- Learning the codebase

## Platform-Specific Notes

### Linux

**PyPI:**
```bash
# Ubuntu/Debian
sudo apt install python3.12 python3-pip
pip install paranoid-cli

# RHEL/Rocky/Alma
sudo dnf install python3.12 python3-pip
pip install paranoid-cli

# Arch
sudo pacman -S python python-pip
pip install paranoid-cli
```

**Docker:**
```bash
# Add user to docker group (one-time)
sudo usermod -aG docker $USER
newgrp docker

# Run
docker run --rm -v $(pwd):/workspace yourusername/paranoid:latest paranoid run /workspace/system.md
```

**Binary:**
```bash
# Download and install
wget https://github.com/yourusername/paranoid/releases/latest/download/paranoid-linux-x64
chmod +x paranoid-linux-x64
sudo mv paranoid-linux-x64 /usr/local/bin/paranoid

# Verify
paranoid --version
```

### macOS

**PyPI:**
```bash
# Using Homebrew Python
brew install python@3.12
pip3 install paranoid-cli

# Using system Python (macOS 13+)
pip3 install paranoid-cli
```

**Docker:**
```bash
# Install Docker Desktop for Mac
brew install --cask docker

# Run
docker run --rm -v $(pwd):/workspace yourusername/paranoid:latest paranoid run /workspace/system.md
```

**Binary (Apple Silicon M1/M2/M3):**
```bash
# Download and install
curl -L -o paranoid https://github.com/yourusername/paranoid/releases/latest/download/paranoid-macos-arm64
chmod +x paranoid
sudo mv paranoid /usr/local/bin/

# First run may require security approval
# System Preferences → Security & Privacy → Allow

# Verify
paranoid --version
```

### Windows

**PyPI:**
```powershell
# Using Python installer from python.org
python -m pip install paranoid-cli

# Verify
paranoid --version
```

**Docker:**
```powershell
# Install Docker Desktop for Windows
winget install Docker.DockerDesktop

# Run (PowerShell)
docker run --rm -v ${PWD}:/workspace yourusername/paranoid:latest paranoid run /workspace/system.md
```

**Binary:**
```powershell
# Download paranoid-windows-x64.exe from GitHub Releases
# Add to PATH or run from current directory

# Verify
.\paranoid.exe --version
```

## CI/CD Integration

### GitHub Actions

```yaml
name: Threat Modeling

on:
  pull_request:
    paths:
      - 'architecture/**'
      - 'docs/threats/**'

jobs:
  threat-model:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install Paranoid
        run: pip install paranoid-cli

      - name: Run threat modeling
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: |
          paranoid run architecture/system.md \
            --output threats.json \
            --format simple \
            --quiet

      - name: Upload results
        uses: actions/upload-artifact@v4
        with:
          name: threat-model
          path: threats.json
```

### GitLab CI

```yaml
threat-modeling:
  image: yourusername/paranoid:latest
  stage: security
  script:
    - paranoid run architecture/system.md --output threats.json --quiet
  artifacts:
    paths:
      - threats.json
    expire_in: 30 days
  only:
    - merge_requests
  variables:
    ANTHROPIC_API_KEY: $ANTHROPIC_API_KEY
```

### Jenkins

```groovy
pipeline {
    agent {
        docker {
            image 'yourusername/paranoid:latest'
        }
    }
    environment {
        ANTHROPIC_API_KEY = credentials('anthropic-api-key')
    }
    stages {
        stage('Threat Modeling') {
            steps {
                sh 'paranoid run architecture/system.md --output threats.json --quiet'
                archiveArtifacts artifacts: 'threats.json', fingerprint: true
            }
        }
    }
}
```

## Troubleshooting

### PyPI Installation Issues

**Problem:** `pip install paranoid-cli` fails with "No matching distribution found"

**Solution:**
- Ensure Python 3.12+ is installed: `python --version`
- Upgrade pip: `pip install --upgrade pip`
- Try with verbose output: `pip install -v paranoid-cli`

**Problem:** Permission denied error

**Solution:**
- Use user install: `pip install --user paranoid-cli`
- Or use virtual environment: `python -m venv venv && source venv/bin/activate`

### Docker Issues

**Problem:** "Cannot connect to Docker daemon"

**Solution:**
- Ensure Docker is running: `docker ps`
- On Linux, add user to docker group: `sudo usermod -aG docker $USER`
- Restart Docker service: `sudo systemctl restart docker`

**Problem:** Permission denied for mounted volumes

**Solution:**
- Use absolute paths: `-v $(pwd):/workspace`
- On Windows, enable drive sharing in Docker Desktop settings

### Binary Issues

**Problem:** "Permission denied" on Linux/macOS

**Solution:**
```bash
chmod +x paranoid-linux-x64
# or
chmod +x paranoid-macos-arm64
```

**Problem:** macOS "App cannot be opened because developer cannot be verified"

**Solution:**
```bash
# Remove quarantine attribute
xattr -d com.apple.quarantine paranoid-macos-arm64

# Or approve in System Preferences → Security & Privacy
```

**Problem:** Windows "Windows protected your PC" warning

**Solution:**
- Click "More info" → "Run anyway"
- Or add exception in Windows Defender

## Version Management

### Checking Version

```bash
# PyPI
paranoid version

# Docker
docker run --rm yourusername/paranoid:latest paranoid version

# Binary
./paranoid-linux-x64 version
```

### Upgrading

**PyPI:**
```bash
pip install --upgrade paranoid-cli
```

**Docker:**
```bash
docker pull yourusername/paranoid:latest
```

**Binary:**
Download the latest binary from GitHub Releases

### Downgrading

**PyPI:**
```bash
pip install paranoid-cli==0.9.0
```

**Docker:**
```bash
docker pull yourusername/paranoid:v0.9.0
```

## Support Matrix

| Platform | PyPI | Docker | Binary |
|----------|------|--------|--------|
| Ubuntu 20.04+ | ✅ | ✅ | ✅ |
| Debian 11+ | ✅ | ✅ | ✅ |
| RHEL 8+ | ✅ | ✅ | ✅ |
| macOS 11+ (Intel) | ✅ | ✅ | ❌ |
| macOS 11+ (ARM64) | ✅ | ✅ | ✅ |
| Windows 10+ | ✅ | ✅ | ✅ |
| WSL2 | ✅ | ✅ | ✅ |

## Getting Help

- **Issues:** https://github.com/yourusername/paranoid/issues
- **Discussions:** https://github.com/yourusername/paranoid/discussions
- **Documentation:** https://github.com/yourusername/paranoid#readme
- **Changelog:** https://github.com/yourusername/paranoid/blob/main/CHANGELOG.md
