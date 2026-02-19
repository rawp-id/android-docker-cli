#!/usr/bin/env python3
"""
Local Image Loader
Used to load Docker images from local tar files into cache
"""

import os
import json
import tarfile
import hashlib
import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)


class LocalImageLoader:
    """Handle loading Docker images from local tar archive files"""
    
    def __init__(self, cache_dir):
        """
        Initialize the loader
        
        Args:
            cache_dir: Cache directory path
        """
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)
    
    def load_image(self, tar_path):
        """
        Load image from tar file
        
        Args:
            tar_path: Path to Docker image tar archive file
            
        Returns:
            tuple: (success: bool, image_name: str, error_message: str)
        """
        # Verify file exists
        if not os.path.exists(tar_path):
            return False, None, f"File does not exist: {tar_path}"
        
        # Validate tar structure
        is_valid, error_msg = self._validate_tar_structure(tar_path)
        if not is_valid:
            return False, None, error_msg
        
        try:
            # Extract image information
            with tarfile.open(tar_path, 'r') as tar:
                # Read manifest.json
                manifest_member = tar.getmember('manifest.json')
                manifest_file = tar.extractfile(manifest_member)
                manifest_data = json.load(manifest_file)
                
                if not manifest_data or len(manifest_data) == 0:
                    return False, None, "manifest.json is empty or invalid format"
                
                # Get information for the first image
                image_info = manifest_data[0]
                repo_tags = image_info.get('RepoTags', [])
                
                if not repo_tags:
                    # If no RepoTags, use config file hash as name
                    config_file = image_info.get('Config', '')
                    image_name = f"<none>:<none>_{config_file[:12]}"
                else:
                    image_name = repo_tags[0]
                
                # Extract to cache
                cache_path = self._extract_to_cache(tar_path, image_name, tar)
                
                # Register image
                self._register_image(image_name, cache_path, tar_path)
                
                logger.info(f"✓ Successfully loaded image: {image_name}")
                return True, image_name, None
                
        except tarfile.ReadError as e:
            return False, None, f"Corrupted tar archive file: {tar_path} - {str(e)}"
        except PermissionError as e:
            return False, None, f"Permission denied: Unable to read {tar_path} - {str(e)}"
        except Exception as e:
            return False, None, f"Failed to load image: {str(e)}"
    
    def _validate_tar_structure(self, tar_path):
        """
        Validate that tar contains required Docker image files
        
        Required files:
        - manifest.json
        - <layer>.tar files
        - <config>.json
        
        Args:
            tar_path: tar file path
            
        Returns:
            tuple: (is_valid: bool, error_message: str)
        """
        try:
            with tarfile.open(tar_path, 'r') as tar:
                members = tar.getnames()
                
                # Check manifest.json
                if 'manifest.json' not in members:
                    return False, "Invalid Docker image tar: missing manifest.json"
                
                # Read manifest to validate structure
                manifest_member = tar.getmember('manifest.json')
                manifest_file = tar.extractfile(manifest_member)
                manifest_data = json.load(manifest_file)
                
                if not manifest_data or len(manifest_data) == 0:
                    return False, "Invalid Docker image tar: manifest.json is empty"
                
                image_info = manifest_data[0]
                
                # Check config file
                config_file = image_info.get('Config')
                if not config_file:
                    return False, "Invalid Docker image tar: missing Config field in manifest"
                
                if config_file not in members:
                    return False, f"Invalid Docker image tar: missing config file {config_file}"
                
                # Check layer files
                layers = image_info.get('Layers', [])
                if not layers:
                    return False, "Invalid Docker image tar: missing Layers field in manifest"
                
                for layer in layers:
                    if layer not in members:
                        return False, f"Invalid Docker image tar: missing layer file {layer}"
                
                return True, None
                
        except tarfile.ReadError:
            return False, f"Corrupted tar archive file: {tar_path}"
        except json.JSONDecodeError:
            return False, "Invalid Docker image tar: manifest.json is not valid JSON"
        except Exception as e:
            return False, f"Failed to validate tar structure: {str(e)}"
    
    def _extract_to_cache(self, tar_path, image_name, tar):
        """
        Extract tar to cache directory with appropriate naming
        
        Args:
            tar_path: Original tar file path
            image_name: Image name
            tar: Opened tarfile object
            
        Returns:
            str: Cache file path
        """
        # Generate cache filename
        # Use image name and tar file content hash
        with open(tar_path, 'rb') as f:
            file_hash = hashlib.sha256(f.read()).hexdigest()[:16]
        
        # Clean image name for filename
        safe_name = image_name.replace(':', '_').replace('/', '_').replace('<', '').replace('>', '')
        cache_filename = f"{safe_name}_{file_hash}.tar.gz"
        cache_path = os.path.join(self.cache_dir, cache_filename)
        
        # If already exists, delete old one first
        if os.path.exists(cache_path):
            logger.info(f"Image already exists, will update: {cache_path}")
            os.remove(cache_path)
        
        # Copy tar file to cache (keep original format or convert to .tar.gz)
        # For simplicity, just copy the original file
        shutil.copy2(tar_path, cache_path)
        
        logger.info(f"Image extracted to cache: {cache_path}")
        return cache_path
    
    def _register_image(self, image_name, cache_path, original_tar):
        """
        Register loaded image in local image list
        
        Args:
            image_name: Image name
            cache_path: Cache file path
            original_tar: Original tar file path
        """
        # Create or update image info file
        info_path = cache_path + '.info'
        
        import time
        created_time = int(time.time())
        created_time_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(created_time))
        
        info_data = {
            'image_url': image_name,
            'cache_path': cache_path,
            'created_time': created_time,
            'created_time_str': created_time_str,
            'source': 'local',
            'original_tar': original_tar
        }
        
        with open(info_path, 'w') as f:
            json.dump(info_data, f, indent=2)
        
        logger.info(f"Image registered: {image_name}")
