# Release Checklist

This document outlines the release process for Paranoid.

## Prerequisites

1. **GitHub Secrets Configured:**
   - `DOCKER_USERNAME` - Docker Hub username
   - `DOCKER_PASSWORD` - Docker Hub access token
   - PyPI publishing uses Trusted Publishers (no secret needed)

2. **Local Tools Installed:**
   ```bash
   pip install build twine pyinstaller
   ```

3. **Permissions:**
   - Maintainer access to GitHub repository
   - Push access to Docker Hub `yourusername/paranoid`
   - PyPI project maintainer for `paranoid-cli`

## Pre-Release Testing

### 1. Run Full Test Suite

```bash
# Run all tests
pytest tests/ -v

# Test CLI commands
paranoid --help
paranoid version
paranoid run examples/stride-example-api-gateway.md
paranoid config show
```

### 2. Test Build Locally

**Test Python package build:**
```bash
./scripts/build_package.sh
# Verify output in dist/
pip install dist/paranoid_cli-*.whl
paranoid version
pip uninstall paranoid-cli
```

**Test binary build (optional):**
```bash
./scripts/build_binary.sh
# Test the binary
./dist/paranoid --help
./dist/paranoid version
```

**Test Docker build:**
```bash
docker build -t paranoid:test .
docker run --rm paranoid:test paranoid --help
```

### 3. Update Documentation

- [ ] Update `CHANGELOG.md` with release notes
- [ ] Update version in `pyproject.toml` (if not already updated)
- [ ] Update `README.md` if needed
- [ ] Verify all examples still work
- [ ] Update `.claude/tasks/CLI-implementation-plan.md` status

## Release Process

### 1. Version Bump

Update version in `pyproject.toml`:

```toml
[project]
version = "1.0.0"  # Update this
```

Commit the version bump:

```bash
git add pyproject.toml CHANGELOG.md
git commit -m "chore: bump version to v1.0.0"
git push origin main
```

### 2. Create Git Tag

```bash
# Create annotated tag
git tag -a v1.0.0 -m "Release v1.0.0"

# Push tag to trigger release workflows
git push origin v1.0.0
```

### 3. Monitor Automated Workflows

Once the tag is pushed, GitHub Actions will automatically:

1. **Build Python Package** (`release.yml`)
   - Build source distribution (.tar.gz)
   - Build wheel (.whl)
   - Upload to PyPI
   - ⏱️ Duration: ~3-5 minutes

2. **Build Binaries** (`release.yml`)
   - Linux x86_64 binary
   - macOS ARM64 binary
   - Windows x64 executable
   - ⏱️ Duration: ~10-15 minutes per platform

3. **Create GitHub Release** (`release.yml`)
   - Attach all artifacts
   - Use CHANGELOG.md as release notes
   - ⏱️ Duration: ~2-3 minutes

4. **Build Docker Images** (`docker.yml`)
   - Build multi-arch images (amd64, arm64)
   - Push to Docker Hub with tags:
     - `latest`
     - `v1.0.0`
     - `v1.0`
     - `v1`
   - ⏱️ Duration: ~15-20 minutes

Monitor at: `https://github.com/yourusername/paranoid/actions`

### 4. Verify Release

**Check PyPI:**
```bash
pip install paranoid-cli==1.0.0
paranoid version
```
Visit: https://pypi.org/project/paranoid-cli/

**Check Docker Hub:**
```bash
docker pull yourusername/paranoid:v1.0.0
docker run --rm yourusername/paranoid:v1.0.0 paranoid version
```
Visit: https://hub.docker.com/r/yourusername/paranoid

**Check GitHub Release:**
- Visit: https://github.com/yourusername/paranoid/releases/latest
- Verify all artifacts are attached:
  - Source tarball (`.tar.gz`)
  - Wheel (`.whl`)
  - `paranoid-linux-x64`
  - `paranoid-macos-arm64`
  - `paranoid-windows-x64.exe`
- Verify CHANGELOG is displayed

## Post-Release Tasks

### 1. Announce Release

- [ ] Create GitHub Discussions post
- [ ] Tweet/social media announcement
- [ ] Update project website (if applicable)
- [ ] Notify stakeholders/users

### 2. Update Documentation Sites

- [ ] Update any external documentation
- [ ] Update badges in README.md if needed

### 3. Monitor Issues

- [ ] Watch for installation issues
- [ ] Monitor PyPI download stats
- [ ] Check Docker Hub pulls
- [ ] Respond to user feedback

## Rollback Procedure

If critical issues are found immediately after release:

### 1. Yank PyPI Release (if needed)

```bash
# This prevents new installs but doesn't delete the release
pip install twine
twine upload --skip-existing --repository pypi dist/*
# Or use PyPI web interface to yank
```

### 2. Delete Git Tag

```bash
# Delete local tag
git tag -d v1.0.0

# Delete remote tag
git push origin :refs/tags/v1.0.0
```

### 3. Delete GitHub Release

- Go to: https://github.com/yourusername/paranoid/releases
- Click "Delete" on the problematic release

### 4. Issue Hotfix

1. Create hotfix branch
2. Fix the issue
3. Bump to v1.0.1
4. Follow release process again

## Troubleshooting

### PyPI Upload Fails

**Issue:** Trusted Publisher not configured

**Solution:**
1. Go to https://pypi.org/manage/account/publishing/
2. Add GitHub repository as trusted publisher:
   - Repository owner: `yourusername`
   - Repository name: `paranoid`
   - Workflow name: `release.yml`
   - Environment: `pypi`

### Docker Build Fails

**Issue:** Multi-arch build fails on ARM

**Solution:**
Check QEMU setup in workflow. May need to adjust `docker/setup-qemu-action` version.

### Binary Build Fails

**Issue:** PyInstaller missing dependencies

**Solution:**
Update `paranoid.spec` with missing `hiddenimports`:

```python
hiddenimports += [
    'missing.module.name',
]
```

### GitHub Release Creation Fails

**Issue:** Missing GITHUB_TOKEN permissions

**Solution:**
Verify `permissions: contents: write` in workflow.

## Version Strategy

- **Major version (x.0.0):** Breaking changes, major new features
- **Minor version (0.x.0):** New features, backward compatible
- **Patch version (0.0.x):** Bug fixes, minor improvements

Examples:
- `v1.0.0` → Initial stable release
- `v1.1.0` → Add new CLI command
- `v1.1.1` → Fix bug in existing command
- `v2.0.0` → Breaking API changes

## Support Policy

- **v1.x:** Active development, security fixes, bug fixes
- **v0.x:** Deprecated after v1.0.0 release (no support)

## Questions?

Contact: Astitva / StateCheck Security
Issues: https://github.com/yourusername/paranoid/issues
