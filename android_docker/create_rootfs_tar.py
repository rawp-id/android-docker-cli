#!/usr/bin/env python3
"""
Script to create root filesystem tar package using curl and Python
Used to execute Docker images in Android Termux via proot
No need for requests library and umoci, only requires curl command-line tool and Python standard library
"""

import os
import sys
import subprocess
import tempfile
import shutil
import argparse
import logging
import json
import hashlib
import tarfile
import gzip
import time
from pathlib import Path
from urllib.parse import urlparse
import platform

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class DockerRegistryClient:
    """Docker Registry API client, downloads images using curl"""

    def __init__(self, registry_url, image_name, tag='latest', username=None, password=None):
        self.registry_url = registry_url
        self.image_name = image_name
        self.tag = tag
        self.auth_token = None
        self.user_agent = 'docker-rootfs-creator/1.0'
        self.username = username
        self.password = password

    def _run_curl_command(self, cmd, print_cmd=True):
        """Execute and print curl command"""
        if print_cmd:
            # For security, hide password when printing command
            safe_cmd = []
            i = 0
            while i < len(cmd):
                safe_cmd.append(cmd[i])
                if cmd[i] == '-u' and i + 1 < len(cmd):
                    safe_cmd.append(f"{cmd[i+1].split(':')[0]}:***")
                    i += 1
                i += 1
            logger.info(f"---\n[ Executing command ]\n{' '.join(safe_cmd)}\n---")
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            if not result.stdout and not result.stderr:
                # Log warning instead of throwing exception to increase network resilience
                logger.warning(f"curl command returned empty response: {' '.join(cmd)}")
            return result
        except subprocess.CalledProcessError as e:
            logger.error(f"!!! curl command failed (error code: {e.returncode}) !!!")
            logger.error(f"""---
[ Error output ]
---\n{e.stderr.strip()}""")
            raise

    def _get_auth_token(self, www_authenticate_header):
        """Obtain authentication token from WWW-Authenticate header"""
        if not www_authenticate_header:
            return None

        # Parse Bearer token information
        if www_authenticate_header.startswith('Bearer '):
            auth_info = {}
            bearer_info = www_authenticate_header[7:]  # Remove 'Bearer '

            for item in bearer_info.split(','):
                if '=' in item:
                    key, value = item.split('=', 1)
                    auth_info[key.strip()] = value.strip('"')

            if 'realm' in auth_info:
                # Build authentication URL
                auth_url = auth_info['realm']
                params = []
                if 'service' in auth_info:
                    params.append(f"service={auth_info['service']}")
                if 'scope' in auth_info:
                    params.append(f"scope={auth_info['scope']}")

                if params:
                    auth_url += '?' + '&'.join(params)

                # Use curl to obtain token
                try:
                    cmd = ['curl', '-v'] # Token retrieval doesn't need -i
                    if self.username and self.password:
                        cmd.extend(['-u', f'{self.username}:{self.password}'])
                    cmd.extend(['-H', f'User-Agent: {self.user_agent}', auth_url])
                    
                    # For simplicity, we call directly without going through _run_curl_command
                    # because proxy has already been set via environment variables
                    logger.info("""---
[ Step 2/3: Obtaining authentication token ]
---""")
                    result = self._run_curl_command(cmd)
                    token_data = json.loads(result.stdout)
                    return token_data.get('token')
                except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
                    logger.warning(f"Failed to obtain authentication token: {e}")
                    # Print command that can be manually executed on failure
                    if isinstance(e, subprocess.CalledProcessError):
                        logger.warning(f"You can manually run the following command to test token retrieval:\n{' '.join(cmd)}")
                    return None

        return None

    def _make_registry_request(self, path, headers=None, output_file=None):
        """Send request to registry, handle authentication"""
        # Step 1: Send an initial request to obtain authentication header
        if not self.auth_token:
            url = f"{self.registry_url}/v2/{path}"
            cmd = ['curl', '-v', '-i', '--insecure', url]
            logger.info("""---
[ Step 1/3: Detecting authentication server ]
---""")
            result = self._run_curl_command(cmd)
            
            auth_header = None
            for line in result.stdout.split('\n'):
                if line.lower().startswith('www-authenticate:'):
                    auth_header = line.split(':', 1)[1].strip()
                    break
            
            if auth_header:
                # Step 2: Use authentication header to obtain token
                token = self._get_auth_token(auth_header)
                if token:
                    self.auth_token = token
                    logger.info("✓ Successfully obtained authentication token")
                else:
                    logger.error("✗ Failed to obtain authentication token, will attempt anonymous access...")
            else:
                logger.warning("'Www-Authenticate' header not found, attempting anonymous request...")

        # Step 3: Send final request using token (or anonymous)
        url = f"{self.registry_url}/v2/{path}"
        cmd = ['curl', '-v', '-i', '--insecure', '-H', f'User-Agent: {self.user_agent}']

        # Always include comprehensive Accept headers for manifest requests
        # This ensures compatibility with both OCI and Docker v2 registries
        if 'manifests' in path:
            comprehensive_accept = ', '.join([
                'application/vnd.oci.image.manifest.v1+json',
                'application/vnd.oci.image.index.v1+json',
                'application/vnd.docker.distribution.manifest.v2+json',
                'application/vnd.docker.distribution.manifest.list.v2+json'
            ])
            cmd.extend(['-H', f'Accept: {comprehensive_accept}'])

        if headers:
            for key, value in headers.items():
                # Skip Accept header if we already added comprehensive one
                if key.lower() == 'accept' and 'manifests' in path:
                    continue
                cmd.extend(['-H', f'{key}: {value}'])

        if self.auth_token:
            cmd.extend(['-H', f'Authorization: Bearer {self.auth_token}'])

        if output_file:
            cmd.extend(['-o', output_file])

        cmd.append(url)
        logger.info("""---
[ Step 3/3: Fetching image manifest ]
---""")
        result = self._run_curl_command(cmd)

        # Parse response, handle possible multiple HTTP headers (e.g., redirects)
        response_text = result.stdout
        
        # Find last HTTP header block
        last_header_block_start = response_text.rfind('HTTP/')
        
        # Separate last header and body
        if last_header_block_start != -1:
            response_part = response_text[last_header_block_start:]
            if '\r\n\r\n' in response_part:
                headers_text, body = response_part.split('\r\n\r\n', 1)
            elif '\n\n' in response_part:
                headers_text, body = response_part.split('\n\n', 1)
            else:
                headers_text = response_part
                body = ''
        else:
            # If "HTTP/" is not found, assume the entire response is body (unlikely to occur)
            headers_text = ''
            body = response_text

        # Parse status code and headers
        lines = headers_text.split('\n')
        status_line = lines[0] if lines else ''
        if ' ' in status_line:
            try:
                status_code = int(status_line.split()[1])
            except (ValueError, IndexError):
                status_code = 0 # Unable to parse status code
        else:
            status_code = 0

        response_headers = {}
        for line in lines[1:]:
            if ':' in line:
                key, value = line.split(':', 1)
                response_headers[key.strip().lower()] = value.strip()

        # If authentication is required and no token yet
        # Since we have already pre-obtained the token, no need to handle 401 here

        if status_code >= 400:
            raise Exception(f"HTTP {status_code}: {body}")

        return {
            'status_code': status_code,
            'headers': response_headers,
            'body': body
        }

    def get_manifest(self):
        """Fetch image manifest"""
        logger.info(f"Fetch image manifest: {self.image_name}:{self.tag}")

        # Support multiple manifest formats
        accept_headers = [
            'application/vnd.docker.distribution.manifest.v2+json',
            'application/vnd.docker.distribution.manifest.list.v2+json',
            'application/vnd.oci.image.manifest.v1+json',
            'application/vnd.oci.image.index.v1+json'
        ]

        headers = {
            'Accept': ', '.join(accept_headers)
        }

        path = f"{self.image_name}/manifests/{self.tag}"
        response = self._make_registry_request(path, headers)

        manifest = json.loads(response['body'])
        content_type = response['headers'].get('content-type', '')

        logger.info(f"Manifest type: {content_type}")
        return manifest, content_type

    def download_blob(self, digest, output_path):
        """Download blob to specified path"""
        logger.info(f"Downloading blob: {digest}")

        path = f"{self.image_name}/blobs/{digest}"

        # Download directly to file
        cmd = ['curl', '-v', '-L', '-H', f'User-Agent: {self.user_agent}']

        # If authentication token exists, add Authorization header
        if self.auth_token:
            cmd.extend(['-H', f'Authorization: Bearer {self.auth_token}'])

        url = f"{self.registry_url}/v2/{path}"
        cmd.extend(['-o', output_path, url])

        self._run_curl_command(cmd)

        logger.debug(f"Blob saved to: {output_path}")
        return output_path

class DockerImageToRootFS:
    def __init__(self, image_url, output_path=None, username=None, password=None, architecture=None):
        self.image_url = image_url
        self.output_path = output_path or f"{self._get_image_name()}_rootfs.tar"
        self.temp_dir = None
        self.username = username
        self.password = password
        self.architecture = architecture or self._get_current_architecture()
        logger.info(f"Target architecture: {self.architecture}")
        
    def _get_current_architecture(self):
        """Get current system architecture and normalize to Docker/OCI format"""
        machine = platform.machine().lower()
        
        # Architecture mapping dictionary
        arch_map = {
            'x86_64': 'amd64',
            'amd64': 'amd64',
            'aarch64': 'arm64',  # Key normalization: aarch64 → arm64
            'arm64': 'arm64',
            'armv7l': 'arm',
            'armv6l': 'arm',
            'i386': '386',
            'i686': '386',
        }
        
        normalized = arch_map.get(machine)
        if normalized:
            if machine == 'aarch64':
                logger.info(f"Architecture normalized: {machine} → {normalized}")
            return normalized
        else:
            logger.warning(f"Unrecognized architecture: {machine}, will default to using amd64")
            return 'amd64'

    def _get_image_name(self):
        """Extract image name from image URL"""
        # Extract image name from URL, remove domain and tag
        parts = self.image_url.split('/')
        image_name = parts[-1].split(':')[0]
        return image_name
    
    def _check_dependencies(self):
        """Check if curl is installed"""
        # Check curl
        try:
            subprocess.run(['curl', '--version'],
                         capture_output=True, check=True)
            logger.info("✓ curl is installed")
        except (subprocess.CalledProcessError, FileNotFoundError):
            logger.error("✗ curl is not installed")
            logger.info("Please install curl command-line tool")
            return False

        # Check tar command
        try:
            subprocess.run(['tar', '--version'],
                         capture_output=True, check=True)
            logger.info("✓ tar is installed")
        except (subprocess.CalledProcessError, FileNotFoundError):
            logger.error("✗ tar is not installed")
            logger.info("Please install tar command-line tool")
            return False

        return True
    
    def _run_command(self, cmd, cwd=None):
        """Execute command and handle errors"""
        logger.info(f"Executing command: {' '.join(cmd)}")
        try:
            result = subprocess.run(
                cmd, 
                cwd=cwd,
                capture_output=True, 
                text=True, 
                check=True
            )
            if result.stdout:
                logger.debug(f"Output: {result.stdout}")
            return result
        except subprocess.CalledProcessError as e:
            logger.error(f"Command execution failed: {' '.join(cmd)}")
            logger.error(f"Error code: {e.returncode}")
            logger.error(f"Error output: {e.stderr}")
            raise
    
    def _create_temp_directory(self):
        """Create temporary working directory"""
        self.temp_dir = tempfile.mkdtemp(prefix='docker_rootfs_')
        logger.info(f"Create temporary directory: {self.temp_dir}")
        return self.temp_dir
    
    def _cleanup_temp_directory(self):
        """Clean up temporary directory"""
        if self.temp_dir and os.path.exists(self.temp_dir):
            # shutil.rmtree(self.temp_dir)
            logger.info(f"Clean up temporary directory: {self.temp_dir}")

    def _parse_image_url(self):
        """Parse image URL, extract registry, image name and tag"""
        image_url = self.image_url

        # Default values
        registry = "registry-1.docker.io"
        image_name = ""
        tag = "latest"

        # Remove docker:// prefix (if exists)
        if image_url.startswith('docker://'):
            image_url = image_url[9:]

        # Separate tag
        # Improved tag separation logic
        if ':' in image_url:
            # Check if colon is after the last slash, or there is no slash at all
            last_colon = image_url.rfind(':')
            last_slash = image_url.rfind('/')
            if last_colon > last_slash:
                # Applicable to a/b:tag, a:123/b:tag, a:tag
                image_url, tag = image_url.rsplit(':', 1)

        # Separate registry and image name
        if '/' in image_url:
            parts = image_url.split('/', 1)
            if '.' in parts[0] or ':' in parts[0]:  # Contains domain name
                registry = parts[0]
                image_name = parts[1]
            else:  # Docker Hub shorthand
                registry = "registry-1.docker.io"
                image_name = image_url
                # Docker Hub library images need library/ prefix
                if '/' not in image_name:
                    image_name = f"library/{image_name}"
        else:
            # Only image name, use Docker Hub
            registry = "registry-1.docker.io"
            image_name = f"library/{image_url}"

        # Ensure registry has protocol prefix
        if not registry.startswith(('http://', 'https://')):
            registry = f"https://{registry}"

        logger.info(f"Parsing image URL: registry={registry}, image={image_name}, tag={tag}")
        return registry, image_name, tag
    
    def _download_image_with_python(self):
        """Download Docker image to OCI format using Python"""
        oci_dir = os.path.join(self.temp_dir, 'oci')
        os.makedirs(oci_dir, exist_ok=True)

        # Parsing image URL
        registry, image_name, tag = self._parse_image_url()

        # Create registry client
        client = DockerRegistryClient(registry, image_name, tag, self.username, self.password)

        # Fetch manifest
        manifest, content_type = client.get_manifest()

        # If manifest list, select a specific manifest based on architecture
        if 'manifest.list' in content_type or 'image.index' in content_type:
            logger.info("Manifest list detected, searching for matching architecture...")
            
            selected_manifest_descriptor = None
            for manifest_descriptor in manifest.get('manifests', []):
                platform_info = manifest_descriptor.get('platform', {})
                manifest_arch = platform_info.get('architecture')
                
                # Architecture equivalence check: aarch64 and arm64 are treated as equivalent
                arch_match = (manifest_arch == self.architecture or 
                             (self.architecture == 'arm64' and manifest_arch == 'aarch64') or
                             (self.architecture == 'aarch64' and manifest_arch == 'arm64'))
                
                if arch_match:
                    # Prefer OS match, if no os field then match directly
                    if platform_info.get('os') == 'linux' or 'os' not in platform_info:
                        selected_manifest_descriptor = manifest_descriptor
                        break
            
            if selected_manifest_descriptor:
                target_digest = selected_manifest_descriptor['digest']
                logger.info(f"Found matching architecture '{self.architecture}' manifest: {target_digest}")
                
                # Fetch sub-manifest
                logger.info(f"""---
[ Step 3/3: Fetching image Manifest ]
---""")
                response = client._make_registry_request(f"{client.image_name}/manifests/{target_digest}")
                manifest = json.loads(response['body'])
                content_type = response['headers'].get('content-type', '') # Update content_type
                logger.info(f"Selected sub-manifest, type: {content_type}")
            else:
                available_archs = [m.get('platform', {}).get('architecture') for m in manifest.get('manifests', [])]
                raise ValueError(f"Cannot find image in manifest list for architecture '{self.architecture}' Available architectures: {', '.join(filter(None, available_archs))}")

        # Create OCI directory structure
        blobs_dir = os.path.join(oci_dir, 'blobs', 'sha256')
        os.makedirs(blobs_dir, exist_ok=True)

        # Save manifest
        manifest_digest = self._save_manifest(oci_dir, manifest, content_type)

        # Download all layers and config
        self._download_layers(client, manifest, blobs_dir)

        # Convert config blob to OCI format
        if 'config' in manifest:
            self._convert_config_blob(client, manifest['config'], blobs_dir)

        # Create oci-layout file
        self._create_oci_layout(oci_dir)

        # Create index.json
        self._create_oci_index(oci_dir, manifest_digest, content_type)

        logger.info(f"Image downloaded to OCI format: {oci_dir}")
        return oci_dir

    def _save_manifest(self, oci_dir, manifest, content_type):
        """Save manifest and return its digest, convert to OCI format"""
        # Convert Docker format manifest to OCI format
        oci_manifest = self._convert_manifest_to_oci(manifest, content_type)

        manifest_json = json.dumps(oci_manifest, separators=(',', ':'))
        manifest_bytes = manifest_json.encode('utf-8')

        # Calculate digest
        digest = hashlib.sha256(manifest_bytes).hexdigest()

        # Save to blobs directory
        blobs_dir = os.path.join(oci_dir, 'blobs', 'sha256')
        manifest_path = os.path.join(blobs_dir, digest)

        with open(manifest_path, 'wb') as f:
            f.write(manifest_bytes)

        logger.debug(f"OCI Manifest saved: sha256:{digest}")
        return f"sha256:{digest}"

    def _convert_manifest_to_oci(self, manifest, content_type):
        """Convert Docker manifest to OCI format"""
        if 'docker' not in content_type:
            # Already in OCI format
            return manifest

        oci_manifest = manifest.copy()

        # Convert media type
        if 'layers' in oci_manifest:
            for layer in oci_manifest['layers']:
                if layer.get('mediaType') == 'application/vnd.docker.image.rootfs.diff.tar.gzip':
                    layer['mediaType'] = 'application/vnd.oci.image.layer.v1.tar+gzip'
                elif layer.get('mediaType') == 'application/vnd.docker.image.rootfs.diff.tar':
                    layer['mediaType'] = 'application/vnd.oci.image.layer.v1.tar'

        if 'config' in oci_manifest:
            if oci_manifest['config'].get('mediaType') == 'application/vnd.docker.container.image.v1+json':
                oci_manifest['config']['mediaType'] = 'application/vnd.oci.image.config.v1+json'

        # Set correct media type
        oci_manifest['mediaType'] = 'application/vnd.oci.image.manifest.v1+json'

        logger.debug("Converted Docker manifest to OCI format")
        return oci_manifest

    def _convert_config_blob(self, client, config_descriptor, blobs_dir):
        """Convert config blob to OCI format"""
        digest = config_descriptor['digest']

        if digest.startswith('sha256:'):
            digest_hash = digest[7:]
        else:
            digest_hash = digest

        config_path = os.path.join(blobs_dir, digest_hash)

        # Read original config
        if not os.path.exists(config_path):
            logger.error(f"Config blob does not exist: {config_path}")
            return

        try:
            with open(config_path, 'r') as f:
                config_data = json.load(f)

            # Convert Docker config to OCI config
            oci_config = self._convert_docker_config_to_oci(config_data)

            # Re-save converted config
            with open(config_path, 'w') as f:
                json.dump(oci_config, f, separators=(',', ':'))

            logger.debug(f"Converted config blob to OCI format: {digest}")

        except Exception as e:
            logger.warning(f"Failed to convert config blob: {e}")

    def _convert_docker_config_to_oci(self, docker_config):
        """Convert Docker config to OCI config"""
        oci_config = docker_config.copy()

        # OCI config basic structure is similar to Docker config, but has some field differences
        # Mainly ensure necessary fields exist

        if 'architecture' not in oci_config:
            oci_config['architecture'] = 'amd64'

        if 'os' not in oci_config:
            oci_config['os'] = 'linux'

        # Ensure config field exists
        if 'config' not in oci_config:
            oci_config['config'] = {}

        # Ensure rootfs field exists
        if 'rootfs' not in oci_config:
            oci_config['rootfs'] = {
                'type': 'layers',
                'diff_ids': []
            }

        # Ensure history field exists
        if 'history' not in oci_config:
            oci_config['history'] = []

        return oci_config

    def _download_layers(self, client, manifest, blobs_dir):
        """Download all layers of the image"""
        # Handle different manifest types
        layers = []

        if 'layers' in manifest and manifest['layers']:
            # Docker v2 manifest or OCI manifest
            layers = manifest['layers'][:]
            if 'config' in manifest:
                layers.append(manifest['config'])
        elif 'fsLayers' in manifest and manifest['fsLayers']:
            # Docker v1 manifest (deprecated, but still needs support)
            layers = manifest['fsLayers'][:]
            if 'history' in manifest:
                # v1 manifest config information is in history
                pass
        # manifest list handling has been moved to caller
        elif not layers:
            raise ValueError("No 'layers' or 'fsLayers' field found in Manifest, or they are empty")

        for layer in layers:
            digest = layer.get('digest') or layer.get('blobSum')
            if digest:
                # Remove sha256: prefix for filename
                if digest.startswith('sha256:'):
                    digest_hash = digest[7:]
                else:
                    digest_hash = digest

                blob_path = os.path.join(blobs_dir, digest_hash)
                if not os.path.exists(blob_path):
                    try:
                        client.download_blob(digest, blob_path)
                        logger.debug(f"Downloaded layer: {digest}")
                    except Exception as e:
                        logger.error(f"Failed to download layer {digest}: {e}")
                        raise

    def _create_oci_index(self, oci_dir, manifest_digest, content_type):
        """Create OCI index.json file"""
        # Ensure content_type conforms to OCI specification
        if 'docker' in content_type:
            # Convert Docker format to OCI format
            if 'manifest.v2+json' in content_type:
                oci_content_type = "application/vnd.oci.image.manifest.v1+json"
            elif 'manifest.list.v2+json' in content_type:
                oci_content_type = "application/vnd.oci.image.index.v1+json"
            else:
                oci_content_type = content_type
        else:
            oci_content_type = content_type

        # Fetch manifestFile size
        manifest_file_path = os.path.join(oci_dir, 'blobs', 'sha256', manifest_digest[7:])
        manifest_size = os.path.getsize(manifest_file_path) if os.path.exists(manifest_file_path) else 0

        index = {
            "schemaVersion": 2,
            "manifests": [
                {
                    "mediaType": oci_content_type,
                    "digest": manifest_digest,
                    "size": manifest_size,
                    "annotations": {
                        "org.opencontainers.image.ref.name": "latest"
                    }
                }
            ]
        }

        index_path = os.path.join(oci_dir, 'index.json')
        with open(index_path, 'w') as f:
            json.dump(index, f, indent=2)

        logger.debug(f"OCI index created: {index_path}")
        logger.debug(f"Using content type: {oci_content_type}")

    def _create_oci_layout(self, oci_dir):
        """Create oci-layout file"""
        layout = {
            "imageLayoutVersion": "1.0.0"
        }

        layout_path = os.path.join(oci_dir, 'oci-layout')
        with open(layout_path, 'w') as f:
            json.dump(layout, f, indent=2)

        logger.debug(f"OCI layout created: {layout_path}")

    def _save_image_config(self, oci_dir, rootfs_dir):
        """Save image configuration to root filesystem for proot_runner use"""
        try:
            # Read OCI index
            index_path = os.path.join(oci_dir, 'index.json')
            with open(index_path, 'r') as f:
                index = json.load(f)

            # Fetch manifest
            manifest_descriptor = index['manifests'][0]
            manifest_digest = manifest_descriptor['digest']
            manifest_path = os.path.join(oci_dir, 'blobs', 'sha256', manifest_digest[7:])

            with open(manifest_path, 'r') as f:
                manifest = json.load(f)

            # Fetch config
            if 'config' in manifest:
                config_digest = manifest['config']['digest']
                config_path = os.path.join(oci_dir, 'blobs', 'sha256', config_digest[7:])

                if os.path.exists(config_path):
                    with open(config_path, 'r') as f:
                        config_data = json.load(f)

                    # Save configuration to root filesystem
                    config_save_path = os.path.join(rootfs_dir, '.image_config.json')
                    with open(config_save_path, 'w') as f:
                        json.dump(config_data, f, indent=2)

                    logger.info(f"Image configuration saved to: {config_save_path}")

                    # Display some useful information
                    config = config_data.get('config', {})
                    if 'Cmd' in config:
                        logger.info(f"Default command: {config['Cmd']}")
                    if 'Entrypoint' in config:
                        logger.info(f"Entrypoint: {config['Entrypoint']}")
                    if 'WorkingDir' in config:
                        logger.info(f"Working directory: {config['WorkingDir']}")
                    if 'Env' in config:
                        logger.info(f"Environment variables: {len(config['Env'])} ")
                else:
                    logger.warning("Config blob not found")
            else:
                logger.warning("No config information in manifest")

        except Exception as e:
            logger.warning(f"Failed to save image configuration: {e}")
            # Does not affect main flow, continue execution
    
    def _extract_rootfs_with_python(self, oci_dir):
        """Extract root filesystem using Python"""
        rootfs_dir = os.path.join(self.temp_dir, 'rootfs')
        os.makedirs(rootfs_dir, exist_ok=True)

        # Read OCI index
        index_path = os.path.join(oci_dir, 'index.json')
        with open(index_path, 'r') as f:
            index = json.load(f)

        # Fetch manifest
        manifest_descriptor = index['manifests'][0]
        manifest_digest = manifest_descriptor['digest']
        manifest_path = os.path.join(oci_dir, 'blobs', 'sha256', manifest_digest[7:])

        with open(manifest_path, 'r') as f:
            manifest = json.load(f)

        logger.info(f"Starting extraction of {len(manifest.get('layers', []))} layers")

        # Extract all layers
        layers = manifest.get('layers', [])
        for i, layer in enumerate(layers, 1):
            layer_digest = layer['digest']
            layer_path = os.path.join(oci_dir, 'blobs', 'sha256', layer_digest[7:])

            logger.info(f"Extracting layer {i}/{len(layers)}: {layer_digest}")

            # First layer uses strict mode, subsequent layers use relaxed mode
            is_first_layer = (i == 1)
            self._extract_layer(layer_path, rootfs_dir, is_first_layer)

        logger.info(f"Root filesystem extracted to: {rootfs_dir}")
        
        # Validate if critical files exist
        missing_files = self._validate_critical_files(rootfs_dir)
        if missing_files:
            error_msg = f"Missing critical files after extraction: {', '.join(missing_files)}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)
        
        return rootfs_dir

    def _extract_layer(self, layer_path, rootfs_dir, is_first_layer=False):
        """Extract single layer to root filesystem directory"""
        # In Android environment, prefer Python tarfile as it handles hard links better
        if self._is_android_environment():
            try:
                logger.debug("Android environment: Using Python tarfile module for extraction")
                self._extract_layer_with_python(layer_path, rootfs_dir)
                return
            except Exception as e:
                logger.warning(f"Python tarfile extraction failed: {e}")
                logger.info("Trying to use tar command...")
                try:
                    self._extract_layer_with_tar(layer_path, rootfs_dir, is_first_layer)
                    return
                except Exception as e2:
                    logger.error(f"tar command also failed: {e2}")
                    raise

        # Non-Android environment: Prefer tar command
        try:
            self._extract_layer_with_tar(layer_path, rootfs_dir, is_first_layer)
            return
        except Exception as e:
            logger.warning(f"tar command extraction failed: {e}")
            logger.info("Trying to use Python tarfile module...")
            self._extract_layer_with_python(layer_path, rootfs_dir)

    def _extract_layer_with_python(self, layer_path, rootfs_dir):
        """Extract layer using Python tarfile module"""
        import tarfile
        import gzip

        # Detect file type
        with open(layer_path, 'rb') as f:
            magic = f.read(2)

        try:
            if magic == b'\x1f\x8b':  # gzip magic number
                # This is a gzip-compressed tar file
                with gzip.open(layer_path, 'rb') as gz_file:
                    with tarfile.open(fileobj=gz_file, mode='r|*') as tar:
                        self._safe_extract_tar(tar, rootfs_dir)
            else:
                # Try as regular tar file
                with tarfile.open(layer_path, 'r') as tar:
                    self._safe_extract_tar(tar, rootfs_dir)
        except Exception as e:
            # If streaming read fails, try non-streaming
            logger.debug(f"Streaming extraction failed, trying non-streaming: {e}")
            if magic == b'\x1f\x8b':
                with tarfile.open(layer_path, 'r:gz') as tar:
                    self._safe_extract_tar(tar, rootfs_dir)
            else:
                with tarfile.open(layer_path, 'r') as tar:
                    self._safe_extract_tar(tar, rootfs_dir)

    def _safe_extract_tar(self, tar, rootfs_dir):
        """Safely extract tar file, handle special cases (enhanced Android support)"""
        whiteout_count = 0
        
        # Set extraction filter to avoid warnings
        def extract_filter(member, path):
            nonlocal whiteout_count
            
            # Skipping whiteout file
            if member.name.startswith('.wh.') or '/.wh.' in member.name:
                logger.debug(f"Skipping whiteout file: {member.name}")
                whiteout_count += 1
                return None

            # Skip device files and special files
            if member.isdev() or member.isfifo():
                logger.debug(f"Skipping device/FIFO file: {member.name}")
                return None

            # Handle path security
            if member.name.startswith('/') or '..' in member.name:
                logger.warning(f"Skipping unsafe path: {member.name}")
                return None

            # In Android environment, reset permissions to avoid issues while preserving executable bit
            if self._is_android_environment():
                if member.isfile():
                    has_exec = bool(member.mode & 0o111)
                    member.mode = 0o755 if has_exec else 0o644
                elif member.isdir():
                    member.mode = 0o755
                # Reset owner information
                member.uid = 0
                member.gid = 0
                member.uname = 'root'
                member.gname = 'root'

            return member

        # Manually handle each member for better control of extraction process
        for member in tar:
            try:
                # Apply filter
                filtered_member = extract_filter(member, rootfs_dir)
                if not filtered_member:
                    continue

                # Special handling for hard links
                if member.islnk():
                    # Convert hard links to regular files or symbolic links
                    self._handle_hardlink(tar, member, rootfs_dir)
                    continue

                # Normal extraction
                tar.extract(filtered_member, rootfs_dir)

            except (OSError, PermissionError, tarfile.ExtractError) as e:
                logger.debug(f"Failed to extract file {member.name}: {e}")

                # Trying to manually create file
                if member.isfile():
                    self._manual_extract_file(tar, member, rootfs_dir)
                elif member.isdir():
                    self._manual_create_dir(member, rootfs_dir)
                elif member.islnk():
                    self._handle_hardlink(tar, member, rootfs_dir)
                elif member.issym():
                    self._manual_create_symlink(member, rootfs_dir)
        
        # If whiteout files were skipped, log warning
        if whiteout_count > 0:
            if self._is_android_environment():
                logger.warning(f"Skipped in Android environment {whiteout_count} whiteout files. Layer deletion semantics may not be fully preserved.")
            else:
                logger.info(f"Skipped {whiteout_count} whiteout files")

    def _handle_hardlink(self, tar, member, rootfs_dir):
        """Handle hard links, convert to regular files"""
        try:
            target_path = os.path.join(rootfs_dir, member.name)
            link_target_path = os.path.join(rootfs_dir, member.linkname)

            # If link target exists, copy file content
            if os.path.exists(link_target_path):
                os.makedirs(os.path.dirname(target_path), exist_ok=True)
                shutil.copy2(link_target_path, target_path)
                logger.debug(f"Hard link converted to file copy: {member.name} -> {member.linkname}")
            else:
                # If target does not exist, try to extract original file from tar
                logger.debug(f"Hard link target does not exist, skipping: {member.name} -> {member.linkname}")
        except Exception as e:
            logger.debug(f"Failed to handle hard link {member.name}: {e}")

    def _manual_extract_file(self, tar, member, rootfs_dir):
        """Manually extract file"""
        try:
            target_path = os.path.join(rootfs_dir, member.name)
            os.makedirs(os.path.dirname(target_path), exist_ok=True)

            with open(target_path, 'wb') as target_file:
                source_file = tar.extractfile(member)
                if source_file:
                    shutil.copyfileobj(source_file, target_file)

            # Set basic permissions
            try:
                os.chmod(target_path, 0o644 if not (member.mode & 0o111) else 0o755)
            except OSError:
                pass

        except Exception as e:
            logger.debug(f"Manually failed to extract file {member.name}: {e}")

    def _manual_create_dir(self, member, rootfs_dir):
        """Manually create directory"""
        try:
            target_path = os.path.join(rootfs_dir, member.name)
            os.makedirs(target_path, exist_ok=True)
            try:
                os.chmod(target_path, 0o755)
            except OSError:
                pass
        except Exception as e:
            logger.debug(f"Failed to manually create directory {member.name}: {e}")

    def _manual_create_symlink(self, member, rootfs_dir):
        """Manually create symbolic link"""
        try:
            target_path = os.path.join(rootfs_dir, member.name)
            os.makedirs(os.path.dirname(target_path), exist_ok=True)

            # If target already exists, delete first
            if os.path.exists(target_path) or os.path.islink(target_path):
                os.remove(target_path)

            os.symlink(member.linkname, target_path)
        except Exception as e:
            logger.debug(f"Failed to manually create symbolic link {member.name}: {e}")

    def _is_android_environment(self):
        """Detect if running in Android environment (enhanced version)"""
        android_indicators = [
            '/data/data/com.termux' in os.getcwd(),
            os.path.exists('/system/build.prop'),
            os.environ.get('ANDROID_DATA') is not None,
            os.environ.get('TERMUX_VERSION') is not None,
            os.path.exists('/data/data/com.termux'),
            'com.termux' in os.environ.get('PREFIX', ''),
        ]

        is_android = any(android_indicators)

        if is_android:
            logger.debug("Detected Android/Termux environment")

        return is_android

    def _validate_critical_files(self, rootfs_dir):
        """Validate if critical files exist (relaxed mode, warnings only)"""
        missing_files = []
        
        # In Android environment, use more relaxed validation
        # Because some images may use non-standard paths
        if self._is_android_environment():
            logger.debug("Android environment: Using relaxed file validation mode")
            
            # Only check if rootfs is empty
            if not os.listdir(rootfs_dir):
                missing_files.append('rootfs is empty')
                return missing_files
            
            # Check if at least some basic directories exist
            basic_dirs = ['bin', 'usr', 'lib', 'etc', 'var']
            has_basic_structure = any(
                os.path.exists(os.path.join(rootfs_dir, d)) 
                for d in basic_dirs
            )
            
            if not has_basic_structure:
                logger.warning(f"Warning: rootfs missing basic directory structure ({', '.join(basic_dirs)})")
                logger.warning("This may be normal, some images use non-standard layouts")
            
            # In Android environment, specific files are not mandatory
            return []
        
        # Non-Android environment: Use standard validation
        # Check shell
        shells = ['/bin/sh', '/bin/bash', '/bin/ash']
        has_shell = False
        for shell in shells:
            shell_path = os.path.join(rootfs_dir, shell.lstrip('/'))
            if os.path.exists(shell_path):
                has_shell = True
                break
        
        if not has_shell:
            missing_files.append('shell (checked: /bin/sh, /bin/bash, /bin/ash)')
        
        # Check lib directory
        lib_dirs = ['/lib', '/lib64', '/usr/lib']
        has_lib = False
        for lib_dir in lib_dirs:
            lib_path = os.path.join(rootfs_dir, lib_dir.lstrip('/'))
            if os.path.exists(lib_path) and os.path.isdir(lib_path) and os.listdir(lib_path):
                has_lib = True
                break
        
        if not has_lib:
            missing_files.append('library directory (checked: /lib, /lib64, /usr/lib)')
        
        # Check /usr/bin
        usr_bin_path = os.path.join(rootfs_dir, 'usr/bin')
        if not os.path.exists(usr_bin_path) or not os.path.isdir(usr_bin_path) or not os.listdir(usr_bin_path):
            missing_files.append('/usr/bin directory')
        
        return missing_files

    def _extract_layer_with_tar(self, layer_path, rootfs_dir, is_first_layer=False):
        """Extract layer using tar command (enhanced Android support)"""
        # Detect file type and use appropriate tar options
        with open(layer_path, 'rb') as f:
            magic = f.read(2)

        # Build base command
        if magic == b'\x1f\x8b':  # gzip
            base_cmd = ['tar', '-xzf', layer_path, '-C', rootfs_dir]
        else:
            base_cmd = ['tar', '-xf', layer_path, '-C', rootfs_dir]

        # Select different options based on whether it's first layer and environment
        if self._is_android_environment():
            # Android environment uses enhanced relaxed options
            tar_options = [
                '--no-same-owner',           # Ignore owner information
                '--no-same-permissions',     # Ignore permission information
                '--warning=no-unknown-keyword',  # Ignore unknown keyword warnings
                '--exclude=.wh.*',           # Skipping whiteout file
                '--exclude=.wh.wh.*',        # Skip whiteout opaque markers
            ]
            
            if not is_first_layer:
                # Subsequent layers allow overwriting and skip existing files (avoid hard link issues)
                tar_options.extend(['--overwrite', '--skip-old-files'])
            else:
                # First layer also skips existing files
                tar_options.append('--skip-old-files')
        else:
            # Standard Linux environment options
            tar_options = [
                '--no-same-owner',
                '--no-same-permissions'
            ]

        cmd = base_cmd + tar_options

        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                logger.debug("tar extraction successful")
            elif result.returncode == 2:
                # tar exit code 2 usually indicates warnings (like hard link failures), but files are extracted
                logger.info("tar extraction completed (with warnings, but files extracted)")
                if self._is_android_environment():
                    logger.debug("Android environment: Ignoring hard link related warnings")
            else:
                # Other error codes, try fallback
                logger.warning(f"tar command failed (exit code{result.returncode}), trying relaxed mode")
                self._extract_with_fallback(base_cmd, rootfs_dir)
        except Exception as e:
            logger.warning(f"tar command exception: {e}, trying relaxed mode")
            self._extract_with_fallback(base_cmd, rootfs_dir)

    def _extract_with_fallback(self, base_cmd, rootfs_dir):
        """Retry tar extraction with most relaxed options"""
        fallback_cmd = base_cmd + [
            '--no-same-owner',
            '--no-same-permissions',
            '--warning=no-unknown-keyword',
            '--exclude=.wh.*',
            '--exclude=.wh.wh.*',
            '--skip-old-files',          # Skip existing files (avoid hard link conflicts)
            '--ignore-failed-read',      # Ignore read failures
        ]

        result = subprocess.run(fallback_cmd, capture_output=True, text=True)

        if result.returncode == 0:
            logger.info("Extraction successful with relaxed mode")
        elif result.returncode == 2:
            # tar exit code 2 indicates warnings but partial success (usually hard link issues)
            logger.info("tar extraction completed (with warnings, but most files extracted)")
            if self._is_android_environment():
                logger.info("Android environment: Hard link errors ignored, container should run normally")
            logger.debug(f"tar warnings: {result.stderr[:500]}...")
        else:
            error_msg = f"tar extraction failed, exit code: {result.returncode}"
            if self._is_android_environment():
                error_msg += "\nTip: In Android environment, some permission operations may fail. Try using --verbose to view details."
            logger.error(error_msg)
            logger.error(f"Error details: {result.stderr[:1000]}")
            raise subprocess.CalledProcessError(result.returncode, fallback_cmd, result.stderr)


    
    def _create_tar_archive(self, rootfs_dir):
        """Create tar archive file"""
        output_path = os.path.abspath(self.output_path)
        
        # Use tar command to create archive, preserve permissions and owner information
        cmd = [
            'tar', 
            '-czf', output_path,
            '-C', rootfs_dir,
            '.'
        ]
        
        self._run_command(cmd)
        logger.info(f"Root filesystem tar package created: {output_path}")
        return output_path
    
    def _optimize_for_proot(self, rootfs_dir):
        """Optimize root filesystem for proot"""
        logger.info("Optimize root filesystem for proot...")

        # Create necessary directories
        essential_dirs = [
            'proc', 'sys', 'dev', 'tmp', 'run',
            'var/tmp', 'var/log', 'var/run'
        ]

        for dir_path in essential_dirs:
            full_path = os.path.join(rootfs_dir, dir_path)
            try:
                os.makedirs(full_path, exist_ok=True)
                logger.debug(f"Ensure directory exists: {dir_path}")
            except OSError as e:
                # If directory already exists but is a file, try to delete and rebuild
                if os.path.exists(full_path) and not os.path.isdir(full_path):
                    try:
                        os.remove(full_path)
                        os.makedirs(full_path, exist_ok=True)
                        logger.debug(f"Replace file with directory: {dir_path}")
                    except OSError as e2:
                        logger.warning(f"Unable to create directory {dir_path}: {e2}")
                else:
                    logger.debug(f"Directory already exists: {dir_path}")
        
        # Create basic device files (if not exist)
        dev_dir = os.path.join(rootfs_dir, 'dev')
        if os.path.exists(dev_dir):
            essential_devs = [
                ('null', 'c', 1, 3),
                ('zero', 'c', 1, 5),
                ('random', 'c', 1, 8),
                ('urandom', 'c', 1, 9)
            ]

            for dev_name, dev_type, major, minor in essential_devs:
                dev_path = os.path.join(dev_dir, dev_name)
                if not os.path.exists(dev_path):
                    try:
                        # Note: In some environments may not have permission to create device files
                        # Just trying here, failure does not affect main functionality
                        if dev_type == 'c' and hasattr(os, 'mknod'):
                            os.mknod(dev_path, 0o666 | os.stat.S_IFCHR,
                                    os.makedev(major, minor))
                            logger.debug(f"Creating character device: {dev_name}")
                        else:
                            # If unable to create device file, create regular file as placeholder
                            with open(dev_path, 'w') as f:
                                f.write('')
                            logger.debug(f"Creating device file placeholder: {dev_name}")
                    except (OSError, AttributeError) as e:
                        logger.debug(f"Unable to create device file {dev_name}: {e} (this is usually normal)")
    
    def create_rootfs_tar(self):
        """Main processing flow"""
        try:
            # Check dependencies
            if not self._check_dependencies():
                return False
            
            # Create temporary directory
            self._create_temp_directory()
            
            # Download image using Python
            logger.info("Step 1/4: Downloading Docker image using Python...")
            oci_dir = self._download_image_with_python()
            
            # Extract root filesystem using Python
            logger.info("Step 2/4: Extracting root filesystem using Python...")
            rootfs_dir = self._extract_rootfs_with_python(oci_dir)
            
                # Save image configuration
            logger.info("Step 3/5: Saving image configuration...")
            self._save_image_config(oci_dir, rootfs_dir)

            # Optimize for proot
            logger.info("Step 4/5: Optimizing root filesystem for proot...")
            self._optimize_for_proot(rootfs_dir)

            # Create tar archive
            logger.info("Step 5/5: Creating tar archive...")
            output_file = self._create_tar_archive(rootfs_dir)
            
            logger.info(f"✓ Successfully created root filesystem tar package: {output_file}")
            logger.info(f"File size: {os.path.getsize(output_file) / 1024 / 1024:.2f} MB")
            
            # Provide usage instructions
            self._print_usage_instructions(output_file)
            
            return True
            
        except Exception as e:
            logger.error(f"Processing failed: {str(e)}")
            return False
        finally:
            # Clean up temporary directory
            self._cleanup_temp_directory()
    
    def _print_usage_instructions(self, tar_file):
        """Print usage instructions"""
        logger.info("\n" + "="*50)
        logger.info("Instructions for using proot in Android Termux:")
        logger.info("="*50)
        logger.info("1. Transfer tar file to Android device")
        logger.info("2. Install proot in Termux:")
        logger.info("   pkg install proot")
        logger.info("3. Extract root filesystem:")
        logger.info(f"   mkdir rootfs && tar -xzf {os.path.basename(tar_file)} -C rootfs")
        logger.info("4. Enter container using proot:")
        logger.info("   proot -r rootfs -b /dev -b /proc -b /sys /bin/sh")
        logger.info("Or use more complete binding:")
        logger.info("   proot -r rootfs -b /dev -b /proc -b /sys -b /sdcard -w / /bin/sh")
        logger.info("="*50)
        logger.info("Note: This script only requires curl and tar command-line tools, no need for skopeo, umoci and requests library")
        logger.info("Uses Python standard library for image unpacking, suitable for running in various environments")

def main():
    parser = argparse.ArgumentParser(
        description='Create Docker image root filesystem tar package using curl and Python'
    )
    parser.add_argument(
        'image_url',
        nargs='?',
        default='swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/jeessy/ddns-go:v6.9.1-linuxarm64',
        help='Docker image URL (default: ddns-go image)'
    )
    parser.add_argument(
        '-o', '--output',
        help='Output tar file path (default: auto-generated based on image name)'
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Show detailed logs'
    )
    parser.add_argument(
        '--username',
        help='Docker Registry username'
    )
    parser.add_argument(
        '--password',
        help='Docker Registry password or token'
    )
    parser.add_argument(
        '--proxy',
        help='Specify network proxy for curl (e.g., "http://user:pass@host:port" or "socks5://host:port")'
    )
    
    parser.add_argument(
        '--arch',
        help='Specify target architecture (e.g., amd64, arm64). Defaults to auto-detect.'
    )
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    logger.info(f"Starting to process Docker image: {args.image_url}")
    
    # Pass proxy parameter to processor
    processor = DockerImageToRootFS(args.image_url, args.output, args.username, args.password, args.arch)
    # Proxy also needs to be set in client
    if args.proxy:
        # This is a simplified handling, ideally should be handled in DockerRegistryClient
        # But for quick problem resolution, we set via environment variables
        os.environ['https_proxy'] = args.proxy
        os.environ['http_proxy'] = args.proxy
        logger.info(f"Network proxy set: {args.proxy}")
    success = processor.create_rootfs_tar()
    
    sys.exit(0 if success else 1)

if __name__ == '__main__':
    main()
