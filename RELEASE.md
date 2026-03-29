# Release Checklist

Internal maintainer guide for publishing Paranoid releases.

## Prerequisites

- Maintainer access to GitHub repository (`theAstiv/paranoid`)
- Docker Hub push access to `theastiv/paranoid`
- PyPI project maintainer for `paranoid-cli` (uses Trusted Publishers — no secret needed)
- GitHub Secrets: `DOCKER_USERNAME`, `DOCKER_PASSWORD`

## Pre-Release

```bash
# Run all tests
pytest tests/ -v

# Test CLI
paranoid --help
paranoid version
paranoid run examples/stride-example-api-gateway.md

# Test package build
./scripts/build_package.sh
pip install dist/paranoid_cli-*.whl && paranoid version && pip uninstall paranoid-cli

# Test Docker build
docker build -t paranoid:test .
docker run --rm paranoid:test paranoid --help
```

Update before tagging:
- [ ] Version in `pyproject.toml`
- [ ] `CHANGELOG.md` with release notes
- [ ] `README.md` if needed
- [ ] Verify examples still work

## Release

```bash
# Commit version bump
git add pyproject.toml CHANGELOG.md
git commit -m "chore: bump version to vX.Y.Z"
git push origin main

# Create and push tag — triggers all automated workflows
git tag -a vX.Y.Z -m "Release vX.Y.Z"
git push origin vX.Y.Z
```

**Automated workflows triggered by tag push:**

| Workflow | Duration | Output |
|----------|----------|--------|
| `release.yml` — Python package | ~5 min | .tar.gz + .whl uploaded to PyPI |
| `release.yml` — Binaries | ~15 min | Linux/macOS/Windows binaries on GitHub Release |
| `docker.yml` — Docker images | ~20 min | Multi-arch images (amd64, arm64) to Docker Hub |

Monitor at: https://github.com/theAstiv/paranoid/actions

## Verify

```bash
# PyPI
pip install paranoid-cli==X.Y.Z && paranoid version

# Docker Hub
docker pull theastiv/paranoid:vX.Y.Z
docker run --rm theastiv/paranoid:vX.Y.Z paranoid version

# GitHub Release — check all artifacts attached:
#   Source .tar.gz, .whl, paranoid-linux-x64, paranoid-macos-arm64, paranoid-windows-x64.exe
```

## Post-Release

- [ ] Create GitHub Discussions announcement
- [ ] Monitor issues for installation problems
- [ ] Watch PyPI download stats and Docker Hub pulls

## Contact

Maintainer: Astitva
Issues: https://github.com/theAstiv/paranoid/issues
