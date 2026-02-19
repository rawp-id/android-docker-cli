#!/bin/bash
# Script to automate creating GitHub Releases
# Usage: bash scripts/create_release.sh <version>
# Example: bash scripts/create_release.sh v1.1.0

set -e

VERSION=$1

if [ -z "$VERSION" ]; then
    echo "Error: Please provide version number"
    echo "Usage: bash scripts/create_release.sh <version>"
    echo "Example: bash scripts/create_release.sh v1.1.0"
    exit 1
fi

# Ensure version number starts with v
if [[ ! $VERSION == v* ]]; then
    VERSION="v$VERSION"
fi

echo "📦 Preparing to create Release: $VERSION"

# Check for uncommitted changes
if [[ -n $(git status --porcelain) ]]; then
    echo "⚠️  Warning: There are uncommitted changes"
    read -p "Continue anyway? (y/n): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Cancelled"
        exit 0
    fi
fi

# Get recent commit history
COMMITS=$(git log --oneline -n 5)
DATE=$(date +%Y-%m-%d)

# Create Release notes
NOTES="## Android Docker CLI $VERSION

Release Date: $DATE

### Changelog
$COMMITS

### Key Features
- ✅ Docker image pull and caching
- ✅ Container lifecycle management (run, start, stop, restart, rm)
- ✅ Docker Compose support
- ✅ Persistent container filesystem
- ✅ Private registry authentication support
- ✅ Volume mounts and environment variable injection

### Supported Environments
- Android Termux
- Linux (Ubuntu/Debian)

### Installation
\`\`\`bash
curl -sSL https://raw.githubusercontent.com/rawp-id/android-docker-cli/$VERSION/scripts/install.sh | sh
\`\`\`"

# Create tag
echo "🏷️  Creating tag: $VERSION"
git tag -a "$VERSION" -m "Release $VERSION"

# Push tag
echo "⬆️  Pushing tag to GitHub"
git push origin "$VERSION"

# Create Release
echo "🚀 Creating GitHub Release"
gh release create "$VERSION" --title "$VERSION" --notes "$NOTES"

echo ""
echo "✅ Release created successfully!"
echo "🔗 https://github.com/rawp-id/android-docker-cli/releases/tag/$VERSION"
