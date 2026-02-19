#!/usr/bin/env python3
"""
Docker-style command-line interface
Mimics Docker command-line tools, providing pull, run, ps, images and other commands
Used to manage containers running through proot
"""

import os
import sys
import argparse
import json
import logging
import time
import subprocess
import signal
from pathlib import Path
from datetime import datetime
import getpass
from urllib.parse import urlparse

# Import existing modules
from .proot_runner import ProotRunner
from .create_rootfs_tar import DockerImageToRootFS

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class DockerCLI:
    """Docker-style command-line interface"""
    
    def __init__(self, cache_dir=None):
        self.cache_dir = cache_dir or self._get_default_cache_dir()
        self.runner = ProotRunner(cache_dir=self.cache_dir)
        self.containers_file = os.path.join(self.cache_dir, 'containers.json')
        self.config_file = self._get_config_file_path()
        self._ensure_cache_dir()
        
    def _get_default_cache_dir(self):
        """Get default cache directory"""
        home_dir = os.path.expanduser('~')
        return os.path.join(home_dir, '.docker_proot_cache')

    def _get_config_file_path(self):
        """Get configuration file path"""
        return os.path.join(self.cache_dir, 'config.json')

    def _ensure_cache_dir(self):
        """Ensure cache directory exists"""
        os.makedirs(self.cache_dir, exist_ok=True)
        
    def _load_containers(self):
        """Load container information"""
        if os.path.exists(self.containers_file):
            try:
                with open(self.containers_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to read container information: {e}")
        return {}
        
    def _save_containers(self, containers):
        """Save container information"""
        try:
            with open(self.containers_file, 'w') as f:
                json.dump(containers, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save container information: {e}")

    def _load_config(self):
        """Load configuration information, including authentication credentials"""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to read configuration file: {e}")
        return {'auths': {}}

    def _save_config(self, config):
        """Save configuration information"""
        try:
            with open(self.config_file, 'w') as f:
                json.dump(config, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save configuration file: {e}")
            
    def _generate_container_id(self):
        """Generate container ID"""
        import hashlib
        import uuid
        return hashlib.sha256(str(uuid.uuid4()).encode()).hexdigest()[:12]
    def _is_process_running(self, pid):
        """Check if process is still running"""
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False

    def _get_container_dir(self, container_id):
        """Get persistent data directory for container"""
        return os.path.join(self.cache_dir, 'containers', container_id)

    def _get_pid_file(self, container_dir):
        """Get PID file path"""
        return os.path.join(container_dir, 'container.pid')

    def _get_log_file(self, container_dir):
        """Get log file path"""
        return os.path.join(container_dir, 'container.log')

            
    def login(self, server, username, password):
        """Login to Docker Registry"""
        if not username:
            username = input("Username: ")
        if not password:
            password = getpass.getpass("Password: ")

        config = self._load_config()
        if 'auths' not in config:
            config['auths'] = {}
        
        # Default server is Docker Hub
        if not server:
            server = "https://index.docker.io/v1/"

        config['auths'][server] = {
            'username': username,
            'password': password # For simplicity, storing plain text.
        }
        self._save_config(config)
        logger.info(f"Login successful: {server}")
        return True

    def pull(self, image_url, force=False):
        """Pull image"""
        logger.info(f"Pulling image: {image_url}")

        # Check if already cached
        if not force and self.runner._is_image_cached(image_url):
            cache_info = self.runner._load_cache_info(image_url)
            if cache_info:
                logger.info(f"Image already exists in cache")
                logger.info(f"Cache time: {cache_info.get('created_time_str', 'Unknown')}")
                return True

        # Load credentials
        config = self._load_config()
        auths = config.get('auths', {})
        
        # Simple matching logic, might need more complex matching in practice
        # Here we assume the domain part of image URL can match to keys in auths
        username, password = None, None
        for server, creds in auths.items():
            server_name = urlparse(server).hostname or server
            if server_name in image_url or (server_name == "index.docker.io" and '/' not in image_url.split(':')[0]):
                username = creds.get('username')
                password = creds.get('password')
                logger.info(f"Found credentials for {server}")
                break
        
        # Now pull directly calls runner's download method
        cache_path = self.runner._download_image(
            image_url,
            force_download=force,
            username=username,
            password=password
        )

        if cache_path:
            logger.info(f"✓ Image pulled successfully: {image_url}")
            return True
        else:
            logger.error(f"✗ Image pull failed: {image_url}")
            return False
            
    def run(self, image_url, command=None, name=None, **kwargs):
        """Run container"""
        # Ensure image exists before running
        if not self.runner._is_image_cached(image_url) or kwargs.get('force_download', False):
            logger.info(f"Image does not exist or force download required, performing 'pull' operation...")
            pull_success = self.pull(image_url, force=kwargs.get('force_download', False))
            if not pull_success:
                logger.error(f"Cannot run container because image pull failed: {image_url}")
                return None

        container_id = name if name else self._generate_container_id()
        container_dir = self._get_container_dir(container_id)
        os.makedirs(container_dir, exist_ok=True)
        
        # Build run arguments
        class Args:
            def __init__(self):
                self.env = kwargs.get('env', [])
                self.bind = kwargs.get('bind', [])
                for v in self.bind:
                    host_path = v.split(':')[0]
                    if not os.path.exists(host_path):
                        # Only log warning, not abort, as some paths may become available after container starts
                        logger.warning(f"Volume mount source path does not exist: {host_path}")
                self.workdir = kwargs.get('workdir')
                self.detach = kwargs.get('detach', False)
                self.interactive = kwargs.get('interactive', False)
                self.force_download = kwargs.get('force_download', False)
                self.username = kwargs.get('username')
                self.password = kwargs.get('password')
                self.command = command
                # Internal: used to persist/reuse the effective Android fake-root setting for detached containers.
                self.fake_root = kwargs.get('fake_root', None)
                if self.command and self.command[0] == '--':
                    self.command = self.command[1:]
                
        args = Args()

        # Compute the effective setting once and persist it for detached containers so start/restart
        # is stable even if process environment changes later.
        try:
            effective_fake_root = self.runner._resolve_fake_root(args)
        except Exception:
            effective_fake_root = None
        args.fake_root = effective_fake_root

        # Record container information
        containers = self._load_containers()
        container_info = {
            'id': container_id,
            'image': image_url,
            'name': name,
            'command': command or [],
            'created': time.time(),
            'created_str': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'status': 'created',
            'pid': None,
            'container_dir': container_dir, 
            'detached': args.detach,
            'run_args': { # Store all arguments needed to restart
                'env': args.env,
                'bind': args.bind,
                'workdir': args.workdir,
                'fake_root': args.fake_root,
            }
        }
        
        containers[container_id] = container_info
        self._save_containers(containers)

        logger.info(f"Starting container: {container_id}")
        
        try:
            # Run container
            if args.detach:
                success = self._run_detached(image_url, args, container_id, container_dir)
            else:
                # For foreground mode, ProotRunner handles the temporary rootfs.
                container_info['status'] = 'running'
                containers[container_id] = container_info
                self._save_containers(containers)
                
                # We pass None for rootfs_dir so ProotRunner creates a temporary one
                success = self.runner.run(image_url, args, rootfs_dir=None)
                
                # Update status after completion
                container_info['status'] = 'exited'
                container_info['finished'] = time.time()
                container_info['finished_str'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                containers[container_id] = container_info
                # In foreground mode, the temporary rootfs is cleaned up by ProotRunner,
                # so we can remove the persistent container dir.
                if os.path.exists(container_dir):
                    import shutil
                    shutil.rmtree(container_dir)
                del containers[container_id]
                self._save_containers(containers)
                
            if success:
                if args.detach:
                    logger.info(f"Container {container_id} started in background")
                else:
                    logger.info(f"Container {container_id} completed")
                return container_id
            else:
                container_info['status'] = 'failed'
                containers[container_id] = container_info
                self._save_containers(containers)
                return None
                
        except KeyboardInterrupt:
            container_info['status'] = 'interrupted'
            containers[container_id] = container_info
            self._save_containers(containers)
            logger.info(f"Container {container_id} interrupted by user")
            return container_id
            
    def _run_detached(self, image_url, args, container_id, container_dir):
        """Run container in background, directly calling proot_runner.py script"""
        rootfs_dir = os.path.join(container_dir, 'rootfs')
        pid_file = self._get_pid_file(container_dir)
        log_file = self._get_log_file(container_dir)

        # Build command-line arguments for proot_runner.py
        cmd = [
            sys.executable,
            '-m', 'android_docker.proot_runner',
            '--rootfs-dir', rootfs_dir,
            '--pid-file', pid_file,
            '--log-file', log_file,
            '--cache-dir', self.cache_dir,  # Pass unified cache directory
            '--detach',
        ]
        
        # Uniformly get credentials from args object
        if hasattr(args, 'username') and args.username:
            cmd.extend(['--username', args.username])
        if hasattr(args, 'password') and args.password:
            cmd.extend(['--password', args.password])

        # Add parameters passed from docker_cli
        if args.force_download:
            cmd.append('--force-download')
        if args.workdir:
            cmd.extend(['--workdir', args.workdir])
        if args.interactive:
            cmd.append('--interactive')
        for e in args.env:
            cmd.extend(['-e', e])
        for b in args.bind:
            cmd.extend(['-b', b])
        
        # Add image URL and command
        # Add -- separator to distinguish proot_runner.py arguments from container commands
        cmd.append(image_url)
        if args.command:
            cmd.append('--')
            cmd.extend(args.command)

        try:
            logger.debug(f"Executing detached command: {' '.join(cmd)}")
            # Ensure detached containers reuse the effective fake-root setting.
            child_env = os.environ.copy()
            if hasattr(args, 'fake_root') and args.fake_root is not None:
                child_env[self.runner.FAKE_ROOT_ENV] = '1' if args.fake_root else '0'
            # Open log file to redirect output
            with open(log_file, 'a') as lf:
                lf.write(f"--- Starting container at {datetime.now()} ---\\n")
                process = subprocess.Popen(
                    cmd,
                    stdout=lf,
                    stderr=lf,
                    stdin=subprocess.DEVNULL,
                    start_new_session=True,
                    env=child_env,
                )
            
            # Wait for pid file to be created, wait up to 5 seconds
            pid = None
            # Extend wait time to 15 seconds (30 * 0.5s)
            for i in range(30):
                time.sleep(0.5)
                if os.path.exists(pid_file):
                    with open(pid_file, 'r') as pf:
                        pid_str = pf.read().strip()
                        if pid_str:
                            try:
                                pid = int(pid_str)
                                logger.debug(f"Successfully obtained PID from PID file: {pid}")
                                break
                            except ValueError:
                                logger.debug(f"Invalid PID file content: '{pid_str}', continuing to wait...")
                logger.debug(f"Waiting for PID file... (attempt {i+1}/30)")
            
            if not pid:
                logger.error("Unable to get PID of background process, startup may have failed.")
                logger.error(f"Please check log file for more information: {log_file}")
                return False

            # Update container information
            containers = self._load_containers()
            containers[container_id]['status'] = 'running'
            containers[container_id]['pid'] = pid
            self._save_containers(containers)
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to start background container: {e}")
            logger.error(f"Please check log file for more information: {log_file}")
            return False

            
    def _cleanup_stale_lock_files(self, rootfs_dir):
        """Clean up common stale lock or PID files before restart"""
        logger.debug(f"Cleaning stale lock files in rootfs: {rootfs_dir}")
        lock_dirs = ['run', 'var/run', 'tmp']
        cleaned_files = 0

        for l_dir in lock_dirs:
            full_dir_path = os.path.join(rootfs_dir, l_dir.lstrip('/'))
            if os.path.isdir(full_dir_path):
                try:
                    for filename in os.listdir(full_dir_path):
                        if filename.endswith('.pid'):
                            file_path = os.path.join(full_dir_path, filename)
                            try:
                                os.remove(file_path)
                                logger.debug(f"Removed stale PID file: {file_path}")
                                cleaned_files += 1
                            except OSError as e:
                                logger.warning(f"Failed to remove PID file {file_path}: {e}")
                except Exception as e:
                    logger.warning(f"Failed to scan directory {full_dir_path}: {e}")
        
        if cleaned_files > 0:
            logger.info(f"Cleaned {cleaned_files} stale PID/lock files.")
        else:
            logger.debug("No stale PID/lock files found to clean.")

    def start(self, container_id):
        """Start a stopped container, preserving its ID and data"""
        containers = self._load_containers()
        if container_id not in containers:
            logger.error(f"Container does not exist: {container_id}")
            return False

        container_info = containers[container_id]
        status = container_info.get('status')

        if status == 'running':
            logger.error(f"Container {container_id} is already running")
            return False

        if status not in ['created', 'exited', 'killed', 'interrupted', 'failed']:
            logger.error(f"Cannot start container {container_id} in '{status}' state")
            return False

        logger.info(f"Starting container: {container_id}")

        image_url = container_info['image']
        command = container_info['command']
        run_args = container_info.get('run_args', {})
        is_detached = container_info.get('detached', False)
        container_dir = container_info.get('container_dir')

        if not container_dir or not os.path.exists(container_dir):
            logger.error(f"Cannot find data directory for container {container_id}.")
            return False

        rootfs_dir = os.path.join(container_dir, 'rootfs')
        if not os.path.exists(rootfs_dir):
            logger.error(f"Cannot find rootfs for container {container_id}.")
            return False

        # Clean up old lock files, this is key fix
        self._cleanup_stale_lock_files(rootfs_dir)

        class Args:
            def __init__(self):
                self.env = run_args.get('env', [])
                self.bind = run_args.get('bind', [])
                self.workdir = run_args.get('workdir')
                self.command = command
                self.detach = is_detached
                self.interactive = run_args.get('interactive', False)
                self.force_download = False
                self.fake_root = run_args.get('fake_root', None)

        args = Args()

        if is_detached:
            # For detached containers, we can reuse the _run_detached logic
            # It will handle logging, PID files, and command construction correctly.
            # We must first update the container status to 'restarting' or similar
            # because _run_detached assumes it's creating a new container.
            # However, a simpler fix is to call it and then update the container info.
            # The _run_detached method already saves container status.
            logger.info(f"Calling _run_detached to restart container {container_id}")
            success = self._run_detached(image_url, args, container_id, container_dir)
            
            if success:
                logger.info(f"Container {container_id} started successfully")
            else:
                logger.error(f"Failed to start container {container_id}")

            return success
        else:
            # Foreground restart logic remains the same
            container_info['status'] = 'running'
            containers[container_id] = container_info
            self._save_containers(containers)
            success = self.runner.run(image_url, args, rootfs_dir=rootfs_dir)
            
            containers = self._load_containers()
            container_info = containers.get(container_id, {})
            container_info['status'] = 'exited'
            container_info['finished'] = time.time()
            container_info['finished_str'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            containers[container_id] = container_info
            self._save_containers(containers)
            return success

    def restart(self, container_id):
        """Restart a container"""
        logger.info(f"Restarting container: {container_id}")

        # 1. Stop container (if running)
        containers = self._load_containers()
        if container_id not in containers:
            logger.error(f"Container does not exist: {container_id}")
            return False

        status = containers[container_id].get('status')
        if status == 'running':
            stop_success = self.stop(container_id)
            if not stop_success:
                logger.error(f"Unable to stop container {container_id}, restart failed")
                return False

        # 2. Start container
        start_success = self.start(container_id)
        if start_success:
            logger.info(f"Successfully restarted container {container_id}")
        else:
            logger.error(f"Failed to restart container {container_id}")

        return start_success

    def logs(self, container_id, follow=False):
        """Display container logs"""
        containers = self._load_containers()
        if container_id not in containers:
            logger.error(f"Container does not exist: {container_id}")
            return False

        container_info = containers[container_id]
        container_dir = container_info.get('container_dir')
        if not container_dir:
            logger.error(f"Cannot find log file path for container {container_id}")
            return False
            
        log_file = self._get_log_file(container_dir)
        if not os.path.exists(log_file):
            logger.info(f"Container {container_id} has no logs")
            return True

        try:
            with open(log_file, 'r') as f:
                if not follow:
                    # Print existing content and exit
                    print(f.read(), end='')
                    return True
                else:
                    # Follow mode (like tail -f)
                    # Print existing content first
                    print(f.read(), end='')
                    # Then wait for new content
                    while True:
                        line = f.readline()
                        if not line:
                            time.sleep(0.1)
                            continue
                        print(line, end='')
        except KeyboardInterrupt:
            print() # Print a newline after Ctrl+C
            return True
        except Exception as e:
            logger.error(f"Failed to read logs: {e}")
            return False

    def attach(self, container_id):
        """Attach to container by executing an interactive shell in the container"""
        logger.info(f"Attaching to container {container_id} (implemented via 'exec -it <shell>')")
        logger.info("Type 'exit' or press Ctrl+D to exit.")
        # Attach is implemented by executing an interactive shell in the container.
        return self.exec(container_id, [], interactive=True)

    def exec(self, container_id, command, interactive=False):
        """Execute command in running container"""
        containers = self._load_containers()
        if container_id not in containers:
            logger.error(f"Container does not exist: {container_id}")
            return False

        container_info = containers[container_id]
        status = container_info.get('status')
        if status != 'running':
            logger.error(f"Container {container_id} is not running")
            return False

        pid = container_info.get('pid')
        if not pid:
            logger.error(f"Container {container_id} has no PID information")
            return False

        if not self._is_process_running(pid):
            logger.error(f"Container {container_id} process is not running")
            return False

        # Get container directory and rootfs path
        container_dir = container_info.get('container_dir')
        if not container_dir:
            logger.error(f"Cannot find directory for container {container_id}")
            return False

        rootfs_dir = os.path.join(container_dir, 'rootfs')
        if not os.path.exists(rootfs_dir):
            logger.error(f"Cannot find rootfs for container {container_id}")
            return False

        # Build exec command using proot
        proot_cmd = ['proot']

        # Keep Android proot compatibility behavior consistent with `docker run`.
        # `args` here is not the same type as proot_runner args; we only rely on env + android detection.
        try:
            proot_cmd.extend(self.runner._get_proot_compat_flags(args=None))
        except Exception:
            pass

        proot_cmd.extend(['-r', rootfs_dir])
        
        # Add default binds
        default_binds = ['/dev', '/proc', '/sys']
        for bind in default_binds:
            if os.path.exists(bind):
                proot_cmd.extend(['-b', bind])

        # Add user specified binds from original container
        original_binds = container_info.get('run_args', {}).get('bind', [])
        for bind in original_binds:
            proot_cmd.extend(['-b', bind])

        # Set working directory
        workdir = container_info.get('run_args', {}).get('workdir') or '/'
        proot_cmd.extend(['-w', workdir])

        # If no command provided, use default shell
        if not command:
            # Find available shell
            default_shells = ['/bin/bash', '/bin/sh']
            shell = '/bin/sh'  # default fallback
            for s in default_shells:
                shell_path = os.path.join(rootfs_dir, s.lstrip('/'))
                if os.path.exists(shell_path):
                    shell = s
                    break
            command = [shell]
        elif isinstance(command, str):
            # If command is a string, convert it to a list
            command = [command]
        
        # Ensure command is a list and not None
        if not isinstance(command, list):
            command = [str(command)] if command else ['/bin/sh']

        # Add the command to execute
        proot_cmd.extend(command)

        logger.info(f"Executing command in container {container_id}: {' '.join(command)}")
        
        try:
            if interactive:
                # Interactive mode: connect stdin/stdout/stderr
                env = os.environ.copy()
                # Remove LD_PRELOAD for Android Termux compatibility
                if 'LD_PRELOAD' in env:
                    del env['LD_PRELOAD']
                subprocess.run(proot_cmd, env=env)
            else:
                # Non-interactive mode: capture output
                env = os.environ.copy()
                # Remove LD_PRELOAD for Android Termux compatibility
                if 'LD_PRELOAD' in env:
                    del env['LD_PRELOAD']
                result = subprocess.run(proot_cmd, env=env, capture_output=True, text=True)
                if result.stdout:
                    print(result.stdout, end='')
                if result.stderr:
                    print(result.stderr, end='', file=sys.stderr)
                return result.returncode == 0
            return True
        except Exception as e:
            logger.error(f"Failed to execute command: {e}")
            return False

    def ps(self, all_containers=False):
        """List containers"""
        containers = self._load_containers()
        
        if not containers:
            logger.info("No containers")
            return
            
        # Update status of running containers
        for container_id, info in containers.items():
            if info.get('status') == 'running' and info.get('pid'):
                # For containers started via new method, pid is the real pid of proot process
                if not self._is_process_running(info['pid']):
                    info['status'] = 'exited'
                    info['finished'] = time.time()
                    info['finished_str'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            elif info.get('status') == 'running' and info.get('script_path'):
                 # Compatible with old containers started via wrapper script
                if not self._is_process_running(info['pid']):
                    info['status'] = 'exited'
                    info['finished'] = time.time()
                    info['finished_str'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        
        self._save_containers(containers)
        
        # Filter containers
        if not all_containers:
            containers = {k: v for k, v in containers.items() 
                         if v.get('status') in ['running', 'created']}
            
        if not containers:
            logger.info("No running containers")
            return
            
        # Display container list
        print(f"{'CONTAINER ID':<12} {'IMAGE':<30} {'COMMAND':<20} {'CREATED':<20} {'STATUS':<10}")
        print("-" * 100)
        
        for container_id, info in containers.items():
            image = info.get('image', 'unknown')[:28]
            command = ' '.join(info.get('command', []))[:18] or 'default'
            created = info.get('created_str', 'unknown')
            status = info.get('status', 'unknown')
            
            print(f"{container_id:<12} {image:<30} {command:<20} {created:<20} {status:<10}")
            
    def images(self):
        """List images"""
        logger.info("Listing cached images:")
        self.runner.list_cache()
    
    def load(self, tar_path):
        """Load image from tar archive"""
        from .image_loader import LocalImageLoader
        
        logger.info(f"Loading image from tar file: {tar_path}")
        
        # Create loader
        loader = LocalImageLoader(self.cache_dir)
        
        # Load image
        success, image_name, error_msg = loader.load_image(tar_path)
        
        if success:
            logger.info(f"✓ Successfully loaded image: {image_name}")
            # Display updated image list
            logger.info("\nCurrent image list:")
            self.images()
            return True
        else:
            logger.error(f"✗ Failed to load image: {error_msg}")
            return False
        
    def rmi(self, image_url):
        """Remove image"""
        logger.info(f"Removing image: {image_url}")
        try:
            self.runner.clear_cache(image_url)
            return True
        except Exception as e:
            logger.error(f"Failed to remove image: {e}")
            return False
        
    def stop(self, container_id):
        """Stop container"""
        containers = self._load_containers()
        
        if container_id not in containers:
            logger.error(f"Container does not exist: {container_id}")
            return False
            
        container_info = containers[container_id]
        pid = container_info.get('pid')
        
        if pid and not self._is_process_running(pid):
            logger.info(f"Container {container_id} process already stopped, updating status to 'exited'")
            container_info['status'] = 'exited'
            container_info['finished'] = time.time()
            container_info['finished_str'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            self._save_containers(containers)
            return True

        # If no PID, or the process corresponding to PID is not running, and container status is not running, consider it already stopped
        if not pid or not self._is_process_running(pid):
            if container_info.get('status') in ['exited', 'killed', 'failed', 'created']:
                logger.info(f"Container {container_id} is already stopped or in non-running state ({container_info.get('status')}).")
                # Ensure status is correctly updated even if PID is missing
                if container_info.get('status') != 'exited':
                    container_info['status'] = 'exited'
                    container_info['finished'] = time.time()
                    container_info['finished_str'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    self._save_containers(containers)
                return True
            else:
                logger.warning(f"Container {container_id} has no valid PID info or process not running, but status is {container_info.get('status')}. Attempting force stop.")
                # For abnormal status (e.g., 'running' but no PID or process), attempt force cleanup
                # This logic needs to be very careful to avoid accidentally deleting data
                # For docker-compose down scenario, if stop fails, rm will take over cleanup
                # So the main purpose here is to make stop return True, allowing rm to proceed
                container_info['status'] = 'exited' # Force mark as exited so rm can handle it
                container_info['finished'] = time.time()
                container_info['finished_str'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                self._save_containers(containers)
                return True
            
        try:
            # Send SIGTERM signal to the entire process group
            os.killpg(pid, signal.SIGTERM)
            logger.info(f"Sent stop signal to container process group {container_id} (PGID: {pid})")
            
            # Check if stopped after waiting
            time.sleep(2)
            if not self._is_process_running(pid):
                container_info['status'] = 'exited'
                container_info['finished'] = time.time()
                container_info['finished_str'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                containers[container_id] = container_info
                self._save_containers(containers)
                logger.info(f"Container {container_id} stopped")
                return True
            else:
                logger.warning(f"Container {container_id} did not respond to SIGTERM, trying SIGKILL")
                os.killpg(pid, signal.SIGKILL)
                container_info['status'] = 'killed'
                containers[container_id] = container_info
                self._save_containers(containers)
                return True
                
        except (OSError, ProcessLookupError) as e:
            logger.error(f"Failed to stop container: {e}")
            return False
            
    def rm(self, container_id, force=False):
        """Remove container"""
        containers = self._load_containers()
        
        if container_id not in containers:
            logger.error(f"Container does not exist: {container_id}")
            return False
            
        container_info = containers[container_id]
        
        # Check if container is running
        # Update status just in case
        if container_info.get('status') == 'running' and container_info.get('pid'):
            if not self._is_process_running(container_info['pid']):
                container_info['status'] = 'exited'
        
        if container_info.get('status') == 'running':
            if not force:
                logger.error(f"Container {container_id} is running, use --force to force removal")
                return False
            else:
                # Force stop container
                logger.info(f"Force stopping container: {container_id}")
                self.stop(container_id)
                # Reload information
                containers = self._load_containers()
                container_info = containers.get(container_id, {})
                if not container_info:
                    logger.info(f"Container {container_id} was removed after stopping")
                    return True
                
        # Clean up container's persistent directory
        container_dir = container_info.get('container_dir')
        if container_dir and os.path.isdir(container_dir):
            try:
                import shutil
                shutil.rmtree(container_dir)
                logger.debug(f"Cleaned container directory: {container_dir}")
                
                # Clean up writable_dirs (if exists)
                writable_dirs_path = os.path.join(os.path.dirname(container_dir), 'writable_dirs')
                if os.path.isdir(writable_dirs_path):
                    shutil.rmtree(writable_dirs_path)
                    logger.debug(f"Cleaned writable directory: {writable_dirs_path}")
            except OSError as e:
                logger.warning(f"Failed to clean container directory {container_dir}: {e}")

        # Compatible with old cleanup logic
        rootfs_dir = container_info.get('rootfs_dir')
        if rootfs_dir and os.path.isdir(rootfs_dir):
            try:
                import shutil
                shutil.rmtree(rootfs_dir)
            except OSError:
                pass

        script_path = container_info.get('script_path')
        if script_path and os.path.exists(script_path):
            try:
                os.remove(script_path)
            except OSError:
                pass
                
        # Delete container record
        if container_id in containers:
            del containers[container_id]
            self._save_containers(containers)
        
        logger.info(f"Container {container_id} removed")
        return True

def create_parser():
    """Create command-line parser"""
    parser = argparse.ArgumentParser(
        prog='docker',
        description='Docker-style proot container management tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Pull image
  %(prog)s pull alpine:latest
  %(prog)s pull nginx:alpine

  # Load image from local tar file
  %(prog)s load -i alpine.tar

  # Run container
  %(prog)s run alpine:latest
  %(prog)s run -d nginx:alpine
  %(prog)s run -it alpine:latest /bin/sh
  %(prog)s run -e "API_KEY=123" -v /host:/container alpine:latest /bin/sh

  # View containers
  %(prog)s ps
  %(prog)s ps -a

  # View images
  %(prog)s images

  # Stop and remove container
  %(prog)s stop <container_id>
  %(prog)s rm <container_id>

  # Attach to running container
  %(prog)s attach <container_id>

  # Execute command in running container
  %(prog)s exec <container_id> ls -l
  %(prog)s exec -it <container_id> /bin/sh

  # Remove image
  %(prog)s rmi alpine:latest
        """
    )

    parser.add_argument(
        '--cache-dir',
        help='Specify cache directory path'
    )

    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Show verbose logs'
    )

    subparsers = parser.add_subparsers(dest='subcommand', help='Available commands', required=True)

    # login command
    login_parser = subparsers.add_parser('login', help='Login to Docker Registry')
    login_parser.add_argument('server', nargs='?', default=None, help='Registry server address (defaults to Docker Hub)')
    login_parser.add_argument('-u', '--username', help='Username')
    login_parser.add_argument('-p', '--password', help='Password')

    # pull command
    pull_parser = subparsers.add_parser('pull', help='Pull image')
    pull_parser.add_argument('image', help='Image URL')
    pull_parser.add_argument('--force', action='store_true', help='Force re-download')

    # run command
    run_parser = subparsers.add_parser('run', help='Run container')
    run_parser.add_argument('image', help='Image URL')
    run_parser.add_argument('--name', help='Assign a name to the container')
    run_parser.add_argument('command', nargs='*', help='Command to execute')
    run_parser.add_argument('-d', '--detach', action='store_true', help='Run in background')
    run_parser.add_argument('-it', '--interactive-tty', action='store_true', help='Run container interactively (allocate pseudo-TTY and keep stdin open)')
    run_parser.add_argument('-e', '--env', action='append', default=[], help='Environment variable (KEY=VALUE)')
    run_parser.add_argument('-v', '--volume', dest='bind', action='append', default=[], help='Mount volume (HOST:CONTAINER)')
    run_parser.add_argument('-w', '--workdir', help='Working directory')
    run_parser.add_argument('--force-download', action='store_true', help='Force re-download image')

    # start command
    start_parser = subparsers.add_parser('start', help='Start a stopped container')
    start_parser.add_argument('container', help='Container ID')

    # restart command
    restart_parser = subparsers.add_parser('restart', help='Restart a container')
    restart_parser.add_argument('container', help='Container ID')

    # ps command
    ps_parser = subparsers.add_parser('ps', help='List containers')
    ps_parser.add_argument('-a', '--all', action='store_true', help='Show all containers (including stopped)')

    # logs command
    logs_parser = subparsers.add_parser('logs', help='View container logs')
    logs_parser.add_argument('container', help='Container ID')
    logs_parser.add_argument('-f', '--follow', action='store_true', help='Continuously output logs')

    # images command
    subparsers.add_parser('images', help='List images')

    # rmi command
    rmi_parser = subparsers.add_parser('rmi', help='Remove image')
    rmi_parser.add_argument('image', help='Image URL')

    # stop command
    stop_parser = subparsers.add_parser('stop', help='Stop container')
    stop_parser.add_argument('container', help='Container ID')

    # rm command
    rm_parser = subparsers.add_parser('rm', help='Remove container')
    rm_parser.add_argument('container', help='Container ID')
    rm_parser.add_argument('-f', '--force', action='store_true', help='Force remove running container')
    
    # attach command
    attach_parser = subparsers.add_parser('attach', help='Attach to running container and view output')
    attach_parser.add_argument('container', help='Container ID')
    
    # exec command
    exec_parser = subparsers.add_parser('exec', help='Execute command in running container')
    exec_parser.add_argument('container', help='Container ID')
    exec_parser.add_argument('command', nargs='*', help='Command to execute')
    exec_parser.add_argument('-it', '--interactive-tty', action='store_true', help='Run container interactively (allocate pseudo-TTY and keep stdin open)')

    # load command
    load_parser = subparsers.add_parser('load', help='Load image from tar archive')
    load_parser.add_argument('-i', '--input', required=True, help='Input tar file path')

    return parser

def main():
    """Main function"""
    parser = create_parser()
    args, unknown = parser.parse_known_args()

    # Handle the command part for 'run' and 'exec'
    if args.subcommand in ['run', 'exec']:
        # Combine the command parts that argparse might have split.
        # `args.command` will have any command parts found before an unknown option.
        # `unknown` will have any arguments that were not recognized.
        # For `run` and `exec`, these are part of the command to be executed.
        args.command.extend(unknown)
    elif unknown:
        # For other subcommands, unknown arguments are an error.
        parser.error(f"unrecognized arguments: {' '.join(unknown)}")

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # If no command specified, show help
    if not args.subcommand:
        parser.print_help()
        return

    # Create CLI instance
    cli = DockerCLI(cache_dir=args.cache_dir)

    try:
        if args.subcommand == 'login':
            success = cli.login(args.server, args.username, args.password)
            sys.exit(0 if success else 1)

        elif args.subcommand == 'pull':
            success = cli.pull(args.image, force=args.force)
            sys.exit(0 if success else 1)

        elif args.subcommand == 'run':
            # Load credentials before calling run and attach to kwargs
            config = cli._load_config()
            auths = config.get('auths', {})
            username, password = None, None
            for server, creds in auths.items():
                server_name = urlparse(server).hostname or server
                if server_name in args.image or (server_name == "index.docker.io" and '/' not in args.image.split(':')[0]):
                    username = creds.get('username')
                    password = creds.get('password')
                    break
            
            container_id = cli.run(
                args.image,
                command=args.command,
                name=args.name,
                env=args.env,
                bind=args.bind,
                workdir=args.workdir,
                detach=args.detach,
                interactive=args.interactive_tty,
                force_download=args.force_download,
                username=username,
                password=password
            )
            sys.exit(0 if container_id else 1)

        elif args.subcommand == 'start':
            success = cli.start(args.container)
            sys.exit(0 if success else 1)

        elif args.subcommand == 'restart':
            success = cli.restart(args.container)
            sys.exit(0 if success else 1)

        elif args.subcommand == 'ps':
            cli.ps(all_containers=args.all)

        elif args.subcommand == 'logs':
            success = cli.logs(args.container, follow=args.follow)
            sys.exit(0 if success else 1)

        elif args.subcommand == 'images':
            cli.images()

        elif args.subcommand == 'rmi':
            success = cli.rmi(args.image)
            sys.exit(0 if success else 1)

        elif args.subcommand == 'stop':
            success = cli.stop(args.container)
            sys.exit(0 if success else 1)

        elif args.subcommand == 'rm':
            success = cli.rm(args.container, force=args.force)
            sys.exit(0 if success else 1)
            
        elif args.subcommand == 'attach':
            success = cli.attach(args.container)
            sys.exit(0 if success else 1)
            
        elif args.subcommand == 'exec':
            success = cli.exec(args.container, args.command, interactive=args.interactive_tty)
            sys.exit(0 if success else 1)

        elif args.subcommand == 'load':
            success = cli.load(args.input)
            sys.exit(0 if success else 1)

        else:
            logger.error(f"Unknown command: {args.subcommand}")
            parser.print_help()
            sys.exit(1)

    except KeyboardInterrupt:
        logger.info("User interrupted")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Execution failed: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()
