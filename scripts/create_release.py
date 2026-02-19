#!/usr/bin/env python3
"""
Script to automate creating GitHub Releases
Usage: python scripts/create_release.py <version> [--notes "release notes"]
Example: python scripts/create_release.py v1.1.0
"""

import subprocess
import sys
import argparse
from datetime import datetime


def run_command(cmd, check=True):
    """Execute command and return output"""
    result = subprocess.run(
        cmd,
        shell=True,
        capture_output=True,
        text=True,
        encoding='utf-8'
    )
    if check and result.returncode != 0:
        print(f"Error: {result.stderr}")
        sys.exit(1)
    return result.stdout.strip()


def get_recent_commits(count=5):
    """Get recent commit history"""
    commits = run_command(f"git log --oneline -n {count}")
    return commits


def create_release_notes(version, custom_notes=None):
    """Generate Release notes"""
    if custom_notes:
        return custom_notes
    
    commits = get_recent_commits()
    date = datetime.now().strftime("%Y-%m-%d")
    
    notes = f"""## Android Docker CLI {version}

Release Date: {date}

### Changelog
{commits}

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
```bash
curl -sSL https://raw.githubusercontent.com/rawp-id/android-docker-cli/{version}/scripts/install.sh | sh
```
"""
    return notes


def main():
    parser = argparse.ArgumentParser(description='Automatically create GitHub Release')
    parser.add_argument('version', help='Version number (e.g., v1.1.0)')
    parser.add_argument('--notes', help='Custom Release notes', default=None)
    parser.add_argument('--draft', action='store_true', help='Create draft Release')
    parser.add_argument('--prerelease', action='store_true', help='Mark as pre-release version')
    
    args = parser.parse_args()
    version = args.version
    
    # Ensure version number format is correct
    if not version.startswith('v'):
        version = f'v{version}'
    
    print(f"📦 Preparing to create Release: {version}")
    
    # Check for uncommitted changes
    status = run_command("git status --porcelain", check=False)
    if status:
        print("⚠️  Warning: There are uncommitted changes")
        response = input("Continue anyway? (y/n): ")
        if response.lower() != 'y':
            print("Cancelled")
            sys.exit(0)
    
    # Create tag
    print(f"🏷️  Creating tag: {version}")
    run_command(f'git tag -a {version} -m "Release {version}"')
    
    # Push tag
    print(f"⬆️  Pushing tag to GitHub")
    run_command(f'git push origin {version}')
    
    # Generate Release notes
    notes = create_release_notes(version, args.notes)
    
    # Create Release
    print(f"🚀 Creating GitHub Release")
    
    cmd = f'gh release create {version} --title "{version}" --notes "{notes}"'
    
    if args.draft:
        cmd += ' --draft'
    if args.prerelease:
        cmd += ' --prerelease'
    
    release_url = run_command(cmd)
    
    print(f"\n✅ Release created successfully!")
    print(f"🔗 {release_url}")


if __name__ == '__main__':
    main()
