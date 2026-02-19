#!/usr/bin/env python3
"""
One-stop service script for running Docker images with proot
Supports direct image URL input, automatic pulling, rootfs creation, and container startup
Supports Docker-like command-line arguments and environment variables, includes image caching functionality
"""

import os
import sys
import subprocess
import argparse
import json
import tempfile
import shutil
import logging
import hashlib
import shlex
import time
import ipaddress
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class ProotRunner:
    """Class for running containers with proot, supports one-stop service"""

    FAKE_ROOT_ENV = "ANDROID_DOCKER_FAKE_ROOT"
    LINK2SYMLINK_ENV = "ANDROID_DOCKER_LINK2SYMLINK"
    ENABLE_IMAGE_PATCHES_ENV = "ANDROID_DOCKER_ENABLE_IMAGE_PATCHES"
    DISABLE_SUPERVISOR_SOCKET_PATCH_ENV = "ANDROID_DOCKER_DISABLE_SUPERVISOR_SOCKET_PATCH"
    SUPERVISORD_INET_PORT = "127.0.0.1:9001"

    _cached_proot_help_text = None
    _cached_proot_supports_link2symlink = None

    def __init__(self, cache_dir=None):
        self.temp_dir = None
        self.rootfs_dir = None
        self.config_data = None
        # Best-effort env overrides passed to host exec when shell-based startup script is unavailable.
        self._container_env_overrides = {}
        self.cache_dir = cache_dir or self._get_default_cache_dir()
        self._ensure_cache_dir()

    def _get_default_cache_dir(self):
        """Get default cache directory"""
        # Create cache in user's home directory
        home_dir = os.path.expanduser('~')
        cache_dir = os.path.join(home_dir, '.proot_runner_cache')
        return cache_dir

    def _ensure_cache_dir(self):
        """Ensure cache directory exists"""
        os.makedirs(self.cache_dir, exist_ok=True)
        logger.debug(f"Cache directory: {self.cache_dir}")

    def _get_image_cache_path(self, image_url):
        """Generate cache path based on image URL"""
        # Use hash of image URL as cache filename
        url_hash = hashlib.sha256(image_url.encode()).hexdigest()[:16]

        # Extract image name as readable part
        image_name = image_url.split('/')[-1].split(':')[0]
        cache_filename = f"{image_name}_{url_hash}.tar.gz"

        return os.path.join(self.cache_dir, cache_filename)

    def _is_image_cached(self, image_url):
        """Check if image is cached"""
        cache_path = self._get_image_cache_path(image_url)
        return os.path.exists(cache_path)

    def _get_cache_info_path(self, image_url):
        """Get cache info file path"""
        cache_path = self._get_image_cache_path(image_url)
        return cache_path + '.info'

    def _save_cache_info(self, image_url, cache_path):
        """Save cache info"""
        info = {
            'image_url': image_url,
            'cache_path': cache_path,
            'created_time': time.time(),
            'created_time_str': time.strftime('%Y-%m-%d %H:%M:%S')
        }

        info_path = self._get_cache_info_path(image_url)
        with open(info_path, 'w') as f:
            json.dump(info, f, indent=2)

    def _load_cache_info(self, image_url):
        """Load cache info"""
        info_path = self._get_cache_info_path(image_url)
        if os.path.exists(info_path):
            try:
                with open(info_path, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to read cache info: {e}")
        return None

    def _download_image(self, image_url, force_download=False, username=None, password=None):
        """Download image to cache"""
        cache_path = self._get_image_cache_path(image_url)

        # Checking cache
        if not force_download and self._is_image_cached(image_url):
            cache_info = self._load_cache_info(image_url)
            if cache_info:
                logger.info(f"Using cached image: {cache_path}")
                logger.info(f"Cache creation time: {cache_info.get('created_time_str', 'Unknown')}")
                return cache_path

        logger.info(f"Downloading image: {image_url}")

        # Calling create_rootfs_tar.py script
        cmd = [
            sys.executable,
            '-m', 'android_docker.create_rootfs_tar',
            '-o', cache_path,
        ]
        if username:
            cmd.extend(['--username', username])
        if password:
            cmd.extend(['--password', password])
        
        # Get and pass proxy parameters
        proxy = os.environ.get('https_proxy') or os.environ.get('HTTPS_PROXY')
        if proxy:
            cmd.extend(['--proxy', proxy])

        cmd.append(image_url)

        try:
            subprocess.run(cmd, check=True)
            logger.info(f"Image downloaded and cached: {cache_path}")

            # Save cache info
            self._save_cache_info(image_url, cache_path)

            return cache_path

        except subprocess.CalledProcessError as e:
            logger.error(f"Image download failed: {e}")
            return None

    def _is_image_url(self, input_str):
        """Determine if input is an image URL"""
        # Simple heuristic check
        url_indicators = [
            '/' in input_str and ':' in input_str,  # Contains registry and tag
            input_str.count('/') >= 1,  # At least one slash
            not input_str.endswith('.tar'),  # Not a tar file
            not input_str.endswith('.tar.gz'),  # Not a tar.gz file
            not os.path.exists(input_str)  # Not a local file/directory
        ]

        return any(url_indicators)

    def _prepare_rootfs(self, input_path, args, provided_rootfs_dir=None):
        """Prepare rootfs (download or use existing)"""
        
        # For restart operation, if persistent directory exists and is non-empty, use it directly
        if provided_rootfs_dir and os.path.exists(provided_rootfs_dir) and os.listdir(provided_rootfs_dir):
            logger.info(f"Using existing persistent rootfs: {provided_rootfs_dir}")
            self.rootfs_dir = provided_rootfs_dir
            self.temp_dir = None # We are not managing a temporary directory
            return self.rootfs_dir

        # Otherwise, execute normal download and extract logic
        if self._is_image_url(input_path):
            # This is an image URL, needs download
            logger.info(f"Detected image URL: {input_path}")
            cache_path = self._download_image(
                input_path,
                force_download=getattr(args, 'force_download', False),
                username=getattr(args, 'username', None),
                password=getattr(args, 'password', None)
            )
            if not cache_path:
                return None
            return self._extract_rootfs_if_needed(cache_path, provided_rootfs_dir=provided_rootfs_dir)
        else:
            # This is a local file or directory
            logger.info(f"Using local rootfs: {input_path}")
            return self._extract_rootfs_if_needed(input_path, provided_rootfs_dir=provided_rootfs_dir)
        
    def _check_dependencies(self):
        """Check if necessary dependencies are installed"""
        # Check proot
        try:
            subprocess.run(['proot', '--version'],
                         capture_output=True, check=True)
            logger.info("✓ proot installed")
        except (subprocess.CalledProcessError, FileNotFoundError):
            logger.error("✗ proot not installed")
            logger.info("Please install proot: pkg install proot (Termux) or apt install proot")
            return False

        # Check create_rootfs_tar.py script
        # Since we are using `python -m`, we don't need to check for the script path here.
        # The python interpreter will find the module.
        logger.info("✓ create_rootfs_tar.py module is available")

        # Check curl (required by create_rootfs_tar.py)
        try:
            subprocess.run(['curl', '--version'],
                         capture_output=True, check=True)
            logger.info("✓ curl installed")
        except (subprocess.CalledProcessError, FileNotFoundError):
            logger.error("✗ curl not installed")
            logger.info("Please install curl: pkg install curl (Termux) or apt install curl")
            return False

        # Check tar
        try:
            subprocess.run(['tar', '--version'],
                         capture_output=True, check=True)
            logger.info("✓ tar installed")
        except (subprocess.CalledProcessError, FileNotFoundError):
            logger.error("✗ tar not installed")
            logger.info("Please install tar: pkg install tar (Termux) or apt install tar")
            return False

        return True
    
    def _extract_rootfs_if_needed(self, rootfs_path, provided_rootfs_dir=None):
        """If input is a tar file, extract to specified directory"""

        # 1. If inputNot a tar file，handle with old logic
        if not (rootfs_path.endswith('.tar') or rootfs_path.endswith('.tar.gz')):
            if os.path.isdir(rootfs_path):
                self.rootfs_dir = os.path.abspath(rootfs_path)
                logger.info(f"Using existing rootfs directory: {self.rootfs_dir}")
                return self.rootfs_dir
            else:
                logger.error(f"Invalid rootfs path: {rootfs_path}")
                return None

        # 2. Determine extract target directory
        is_temp = False
        if provided_rootfs_dir:
            target_dir = provided_rootfs_dir
            self.temp_dir = None
        else:
            self.temp_dir = tempfile.mkdtemp(prefix='proot_runner_')
            target_dir = os.path.join(self.temp_dir, 'rootfs')
            is_temp = True
        
        self.rootfs_dir = target_dir
        os.makedirs(self.rootfs_dir, exist_ok=True)

        # 3. Extract tar file
        logger.info(f"Detected tar file, extracting: {rootfs_path} -> {self.rootfs_dir}")
        if rootfs_path.endswith('.tar.gz'):
            cmd = ['tar', '-xzf', rootfs_path, '-C', self.rootfs_dir]
        else:
            cmd = ['tar', '-xf', rootfs_path, '-C', self.rootfs_dir]
        
        try:
            subprocess.run(cmd, check=True)
            logger.info(f"Rootfs extracted to: {self.rootfs_dir}")
            return self.rootfs_dir
        except subprocess.CalledProcessError as e:
            logger.error(f"Extract failed: {e}")
            if is_temp:
                self._cleanup()
            return None
    
    def _find_image_config(self):
        """Find image config information"""
        # Try to find config from multiple possible locations
        config_paths = [
            os.path.join(self.rootfs_dir, '.image_config.json'),
            os.path.join(self.rootfs_dir, 'image_config.json'),
            os.path.join(self.rootfs_dir, 'etc', 'image_config.json')
        ]
        
        for config_path in config_paths:
            if os.path.exists(config_path):
                try:
                    with open(config_path, 'r') as f:
                        self.config_data = json.load(f)
                    logger.info(f"Found image config: {config_path}")
                    return True
                except Exception as e:
                    logger.warning(f"Failed to read config file {config_path}: {e}")
        
        logger.info("Image config file not found, will use default settings")
        return False
    
    def _get_default_command(self):
        """Get default startup command"""
        if self.config_data:
            # Get CMD or ENTRYPOINT from config
            config = self.config_data.get('config', {})

            # Prefer Entrypoint + Cmd
            entrypoint = config.get('Entrypoint', [])
            cmd = config.get('Cmd', [])

            logger.debug(f"Image config - Entrypoint: {entrypoint}, Cmd: {cmd}")

            if entrypoint:
                if cmd:
                    result = entrypoint + cmd
                    logger.info(f"Using image default command: Entrypoint + Cmd = {result}")
                    return result
                else:
                    logger.info(f"Using image default command: Entrypoint = {entrypoint}")
                    return entrypoint
            elif cmd:
                logger.info(f"Using image default command: Cmd = {cmd}")
                return cmd

        # Default command - find available shell
        logger.warning("Entrypoint or Cmd not found in image config, using default shell")
        default_shells = ['/bin/bash', '/bin/sh', '/bin/ash', '/bin/dash']
        for shell in default_shells:
            shell_path = os.path.join(self.rootfs_dir, shell.lstrip('/'))
            if os.path.exists(shell_path):
                logger.debug(f"Found available shell: {shell}")
                return [shell]

        # If no shell found, try busybox
        busybox_path = os.path.join(self.rootfs_dir, 'bin/busybox')
        if os.path.exists(busybox_path):
            logger.debug("Using busybox shell")
            return ['/bin/busybox', 'sh']

        logger.warning("No available shell found, using default /bin/sh")
        return ['/bin/sh']  # Last fallback

    def _get_available_shell(self):
        """Get available shell path (for script execution)"""
        # Find available shell
        default_shells = ['/bin/bash', '/bin/sh', '/bin/ash', '/bin/dash']
        for shell in default_shells:
            shell_path = os.path.join(self.rootfs_dir, shell.lstrip('/'))
            if os.path.exists(shell_path):
                logger.debug(f"Found available shell for script execution: {shell}")
                return shell

        # If no shell found, try busybox
        busybox_path = os.path.join(self.rootfs_dir, 'bin/busybox')
        if os.path.exists(busybox_path):
            logger.debug("Using busybox shellfor script execution")
            return '/bin/busybox'

        logger.warning("No available shell found for script execution")
        return None

    def _get_default_env(self):
        """Get default environment variables"""
        env_vars = {}
        
        if self.config_data:
            config = self.config_data.get('config', {})
            env_list = config.get('Env', [])
            
            for env_str in env_list:
                if '=' in env_str:
                    key, value = env_str.split('=', 1)
                    env_vars[key] = value
        
        # Add some basic environment variables
        env_vars.setdefault('PATH', '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin')
        env_vars.setdefault('HOME', '/root')
        env_vars.setdefault('TERM', 'xterm')
        
        return env_vars
    
    def _get_working_directory(self):
        """Get working directory"""
        if self.config_data:
            config = self.config_data.get('config', {})
            workdir = config.get('WorkingDir')
            if workdir:
                return workdir
        
        return '/'
    
    def _build_proot_command(self, args):
        """Build proot command (enhanced Android support)"""
        cmd = ['proot']
        self._container_env_overrides = {}

        # Android/Termux compatibility flags.
        cmd.extend(self._get_proot_compat_flags(args))

        # Basic options
        cmd.extend(['-r', self.rootfs_dir])

        # If running in background, disable TTY and specify PID file
        if args.detach:
            # This block is now empty as proot doesn't support pid file args
            pass

        # Bind mounts
        default_binds = [
            '/dev',
            '/proc',
            '/sys'
        ]

        # Add extra binds in Android/Termux
        if self._is_android_environment():
            default_binds.extend([
                '/sdcard',
            ])

            # Add writable system directory binds
            # Use rootfs_dir as container_dir to store writable directories
            if self.rootfs_dir:
                writable_binds = self._prepare_writable_directories(self.rootfs_dir)
                default_binds.extend(writable_binds)
                hosts_bind = self._prepare_android_hosts_bind(self.rootfs_dir)
                if hosts_bind:
                    default_binds.append(hosts_bind)
                resolv_bind = self._prepare_android_resolv_bind(self.rootfs_dir)
                if resolv_bind:
                    default_binds.append(resolv_bind)
                logger.info("Android writable directory support enabled")

        for bind in default_binds:
            if ':' in bind:
                src, dst = bind.rsplit(':', 1)
                if os.path.exists(src):
                    cmd.extend(['-b', bind])
            else:
                if os.path.exists(bind):
                    cmd.extend(['-b', bind])

        # User-specifiedBind mounts
        for bind in args.bind:
            cmd.extend(['-b', bind])

        # Working directory
        workdir = args.workdir or self._get_working_directory()
        cmd.extend(['-w', workdir])

        # Environment variables
        env_vars = self._get_default_env()

        # AddUser-specifiedEnvironment variables
        for env in args.env:
            if '=' in env:
                key, value = env.split('=', 1)
                env_vars[key] = value

        # If running in background, force set TERM to dumb to avoid interactive behavior
        if args.detach:
            env_vars['TERM'] = 'dumb'

        # proot doesn't support -E option, need to set environment variables another way
        # We will set environment variables by modifying startup command

        # Build final execution command
        if args.command:
            final_command = args.command
            logger.info(f"Using user-specified command: {final_command}")
        else:
            default_cmd = self._get_default_command()
            final_command = default_cmd
            logger.debug(f"Using default command: {final_command}")

        # Create startup script to setEnvironment variables
        if env_vars or self._is_android_environment():
            # Get available shell to execute startup script
            available_shell = self._get_available_shell()
            if available_shell:
                startup_script = self._create_startup_script(env_vars, final_command, available_shell=available_shell)

                # If busybox, need to add sh argument
                if available_shell == '/bin/busybox':
                    cmd.extend([available_shell, 'sh', startup_script])
                else:
                    cmd.extend([available_shell, startup_script])
            else:
                # Distroless/no-shell images still need to run their entrypoint directly.
                # We cannot inject env via startup script in this mode, so pass a host-safe subset
                # through subprocess env. Avoid PATH override to keep host-side proot lookup stable.
                self._container_env_overrides = {
                    key: value for key, value in env_vars.items() if key != 'PATH'
                }
                logger.warning("No available shell in image, executing entrypoint directly and injecting variables through host environment")
                cmd.extend(final_command)
        else:
            cmd.extend(final_command)

        return cmd

    @staticmethod
    def _parse_env_bool(value):
        """Parse common boolean env var strings.

        Returns:
            True/False, or None if value is empty/unknown.
        """
        if value is None:
            return None
        text = str(value).strip().lower()
        if text == "":
            return None
        if text in {"1", "true", "yes", "y", "on"}:
            return True
        if text in {"0", "false", "no", "n", "off"}:
            return False
        return None

    def _resolve_fake_root(self, args=None):
        """Return whether to enable proot fake-root for this run.

        Precedence:
        - If args.fake_root is explicitly set (True/False), use it (for persisted detached containers).
        - Otherwise, only consider fake-root on Android/Termux:
          - Default enabled.
          - Can be disabled via ANDROID_DOCKER_FAKE_ROOT=0 (escape hatch).
        """
        if args is not None and hasattr(args, "fake_root") and args.fake_root is not None:
            return bool(args.fake_root)

        if not self._is_android_environment():
            return False

        env_value = os.environ.get(self.FAKE_ROOT_ENV)
        parsed = self._parse_env_bool(env_value)
        if parsed is None:
            return True
        return parsed

    def _get_proot_help_text(self):
        """Return cached `proot --help` output (best-effort)."""
        if ProotRunner._cached_proot_help_text is not None:
            return ProotRunner._cached_proot_help_text

        try:
            result = subprocess.run(
                ['proot', '--help'],
                capture_output=True,
                text=True,
                timeout=3,
            )
            text = (result.stdout or "") + "\n" + (result.stderr or "")
        except Exception:
            text = ""

        ProotRunner._cached_proot_help_text = text
        return text

    def _proot_supports_link2symlink(self):
        """Detect whether this proot build supports `--link2symlink`."""
        if ProotRunner._cached_proot_supports_link2symlink is not None:
            return ProotRunner._cached_proot_supports_link2symlink

        help_text = self._get_proot_help_text()
        supported = "link2symlink" in (help_text or "")
        ProotRunner._cached_proot_supports_link2symlink = supported
        return supported

    def _resolve_link2symlink(self):
        """Return whether to enable proot `--link2symlink` for Android runs.

        This is a broadly applicable workaround for Android/Termux hard-link restrictions.
        Default: enabled on Android if the proot build supports it.
        Escape hatch: ANDROID_DOCKER_LINK2SYMLINK=0
        """
        if not self._is_android_environment():
            return False

        parsed = self._parse_env_bool(os.environ.get(self.LINK2SYMLINK_ENV))
        if parsed is False:
            return False

        # Default enabled, but only if supported by the installed proot.
        if parsed is None or parsed is True:
            return self._proot_supports_link2symlink()

        return False

    def _get_proot_compat_flags(self, args=None):
        """Flags added before `-r rootfs` to improve Android/Termux compatibility."""
        flags = []

        # Default to proot fake-root semantics so images that assume "start as root then drop
        # privileges" behave closer to Docker defaults.
        if self._resolve_fake_root(args):
            flags.append('-0')

        # Emulate hardlinks using symlinks when possible. This avoids common loops/hangs in
        # images that rely on os.link() for atomic unix socket creation (e.g. supervisord).
        if self._resolve_link2symlink():
            flags.append('--link2symlink')

        return flags

    def _create_startup_script(self, env_vars, command, available_shell=None):
        """Create startup script to set environment variables and execute command"""
        # Get available shell to use as script shebang
        if available_shell is None:
            available_shell = self._get_available_shell()
        if not available_shell:
            raise RuntimeError("Cannot create startup script: no available shell in image")

        # If busybox, need special handling
        if available_shell == '/bin/busybox':
            script_content = ['#!/bin/busybox sh']
        else:
            script_content = [f'#!{available_shell}']

        # AddEnvironment variablessettings
        for key, value in env_vars.items():
            # Escape special characters
            escaped_value = value.replace('"', '\\"').replace('$', '\\$').replace('`', '\\`')
            script_content.append(f'export {key}="{escaped_value}"')

        # Add special handling in Android environment
        if self._is_android_environment():
            script_content.extend([
                '# Android Termux special handling',
                'unset LD_PRELOAD'  # Disable termux-exec
            ])

        # Add execution command
        if len(command) >= 2 and command[0] == 'sh' and command[1] == '-c':
            # For 'sh -c "command string"', ensure command string is properly quoted
            quoted_command_str = shlex.quote(command[2])
            script_content.append(f'exec {command[0]} {command[1]} {quoted_command_str}')
        else:
            command_str = ' '.join(f'"{arg}"' if ' ' in arg else arg for arg in command)
            script_content.append(f'exec {command_str}')

        # Write to temporary script file
        script_path = os.path.join(self.rootfs_dir, 'startup.sh')
        with open(script_path, 'w') as f:
            f.write('\n'.join(script_content) + '\n')

        # Set execute permissions
        os.chmod(script_path, 0o755)

        logger.debug(f"Creating startup script: {script_path}")
        logger.debug(f"Script content:\n{chr(10).join(script_content)}")
        return '/startup.sh'
    
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

    def _seed_writable_directory_structure(self, rootfs_dir, dir_path, host_dir):
        """Mirror rootfs directory structure into the host writable directory."""
        if not rootfs_dir:
            return

        source_dir = os.path.join(rootfs_dir, dir_path)
        if not os.path.isdir(source_dir):
            return

        for root, dirnames, _ in os.walk(source_dir):
            rel_root = os.path.relpath(root, source_dir)
            target_root = host_dir if rel_root == '.' else os.path.join(host_dir, rel_root)
            try:
                os.makedirs(target_root, exist_ok=True)
            except OSError as exc:
                logger.debug(f"Failed to create writable directory structure: {target_root}: {exc}")
                dirnames[:] = []

    def _prepare_writable_directories(self, rootfs_dir):
        """Prepare writable system directories for Android environment"""
        if not self._is_android_environment():
            return []

        # List of system directories that need to be writable
        writable_dirs = [
            'var/log',
            'var/cache',
            'var/tmp',
            'var/run',
            'tmp',
            'run',
        ]

        # Create writable_dirs directory at the same level as rootfs directory
        # If rootfs_dir is a temporary directory, writable_dirs will also be in temporary directory
        # If rootfs_dir is a persistent directory, writable_dirs will also be persistent
        parent_dir = os.path.dirname(rootfs_dir) if os.path.dirname(rootfs_dir) else rootfs_dir
        writable_storage = os.path.join(parent_dir, 'writable_dirs')
        os.makedirs(writable_storage, exist_ok=True)

        bind_mounts = []

        # Many distros treat /var/run as a symlink to /run. Ensure they share the same host dir
        # so software (e.g. supervisord) doesn't see inconsistent runtime state.
        shared_run_host_dir = os.path.join(writable_storage, 'run')

        for dir_path in writable_dirs:
            # Create writable directory on host side
            if dir_path in ('run', 'var/run'):
                host_dir = shared_run_host_dir
            else:
                host_dir = os.path.join(writable_storage, dir_path.replace('/', '_'))
            os.makedirs(host_dir, exist_ok=True)

            # Set permissions
            try:
                os.chmod(host_dir, 0o777)  # Fully writable
            except OSError:
                pass

            # Best-effort cleanup for known stale supervisor artifacts. These are transient and can
            # block startup if persisted across runs in host-side writable dirs.
            if host_dir == shared_run_host_dir:
                for stale_name in ('supervisor.sock', 'supervisord.pid', 'supervisord.sock'):
                    stale_path = os.path.join(host_dir, stale_name)
                    try:
                        if os.path.exists(stale_path):
                            os.remove(stale_path)
                    except OSError:
                        pass

            self._seed_writable_directory_structure(rootfs_dir, dir_path, host_dir)

            # Add to bind mounts list
            container_path = f"/{dir_path}"
            bind_mounts.append(f"{host_dir}:{container_path}")

            logger.debug(f"Preparing writable directory: {host_dir} -> {container_path}")

        logger.info(f"Prepared {len(bind_mounts)} writable system directories")
        return bind_mounts

    def _prepare_android_hosts_bind(self, rootfs_dir):
        """Create a host-side /etc/hosts file for Android and return its bind spec."""
        if not rootfs_dir:
            return None

        parent_dir = os.path.dirname(rootfs_dir) if os.path.dirname(rootfs_dir) else rootfs_dir
        writable_storage = os.path.join(parent_dir, 'writable_dirs')
        os.makedirs(writable_storage, exist_ok=True)

        host_hosts_path = os.path.join(writable_storage, 'etc_hosts')
        source_path = host_hosts_path if os.path.exists(host_hosts_path) else None

        if not source_path:
            rootfs_hosts_path = os.path.join(rootfs_dir, 'etc', 'hosts')
            if os.path.exists(rootfs_hosts_path):
                source_path = rootfs_hosts_path

        lines = []
        if source_path:
            try:
                with open(source_path, 'r', encoding='utf-8', errors='ignore') as handle:
                    lines = handle.read().splitlines()
            except OSError as exc:
                logger.debug(f"Failed to read hosts file {source_path}: {exc}")

        def has_localhost(ip_address):
            for line in lines:
                stripped = line.strip()
                if not stripped or stripped.startswith('#'):
                    continue
                parts = stripped.split()
                if ip_address in parts and 'localhost' in parts:
                    return True
            return False

        if not has_localhost('127.0.0.1'):
            lines.append('127.0.0.1 localhost')
        if not has_localhost('::1'):
            lines.append('::1 localhost')

        try:
            with open(host_hosts_path, 'w', encoding='utf-8') as handle:
                handle.write('\n'.join(lines) + '\n')
            try:
                os.chmod(host_hosts_path, 0o644)
            except OSError:
                pass
        except OSError as exc:
            logger.debug(f"Failed to write hosts file {host_hosts_path}: {exc}")
            return None

        return f"{host_hosts_path}:/etc/hosts"

    @staticmethod
    def _is_localhost_dns_server(server):
        """Return True when a DNS server points to loopback/unspecified addresses."""
        if not server:
            return True

        normalized = str(server).strip()
        if '%' in normalized:
            normalized = normalized.split('%', 1)[0]

        try:
            addr = ipaddress.ip_address(normalized)
        except ValueError:
            return True

        return addr.is_loopback or addr.is_unspecified

    @staticmethod
    def _read_nameservers_from_resolv(path):
        """Read nameserver entries from a resolv.conf style file."""
        nameservers = []
        if not path or not os.path.exists(path):
            return nameservers

        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as handle:
                for line in handle:
                    stripped = line.strip()
                    if not stripped or stripped.startswith('#'):
                        continue
                    parts = stripped.split()
                    if len(parts) >= 2 and parts[0].lower() == 'nameserver':
                        nameservers.append(parts[1])
        except OSError as exc:
            logger.debug(f"Failed to read resolv file {path}: {exc}")

        return nameservers

    def _get_android_dns_properties(self):
        """Best-effort DNS server discovery from Android system properties."""
        keys = ('net.dns1', 'net.dns2', 'net.dns3', 'net.dns4')
        values = []

        for key in keys:
            try:
                result = subprocess.run(
                    ['getprop', key],
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
            except Exception:
                continue

            value = (result.stdout or '').strip()
            if value:
                values.append(value)

        return values

    def _prepare_android_resolv_bind(self, rootfs_dir):
        """Create Android /etc/resolv.conf bind.

        Default behavior: pin DNS to 1.1.1.1 for stability.
        Override: set ANDROID_DOCKER_DNS (comma/space separated).
        """
        if not rootfs_dir:
            return None

        parent_dir = os.path.dirname(rootfs_dir) if os.path.dirname(rootfs_dir) else rootfs_dir
        writable_storage = os.path.join(parent_dir, 'writable_dirs')
        os.makedirs(writable_storage, exist_ok=True)

        host_resolv_path = os.path.join(writable_storage, 'etc_resolv.conf')
        dns_servers = []

        def add_servers(candidates):
            for candidate in candidates:
                value = str(candidate).strip()
                if not value:
                    continue
                if self._is_localhost_dns_server(value):
                    continue
                if value in dns_servers:
                    continue
                dns_servers.append(value)

        env_dns = os.environ.get('ANDROID_DOCKER_DNS', '')
        if env_dns:
            add_servers(env_dns.replace(',', ' ').split())
        if not dns_servers:
            dns_servers = ['1.1.1.1']
            logger.info("Android DNS fixed to 1.1.1.1 (can be overridden via ANDROID_DOCKER_DNS)")

        lines = [f'nameserver {server}' for server in dns_servers]

        try:
            with open(host_resolv_path, 'w', encoding='utf-8') as handle:
                handle.write('\n'.join(lines) + '\n')
            try:
                os.chmod(host_resolv_path, 0o644)
            except OSError:
                pass
        except OSError as exc:
            logger.debug(f"Failed to write resolv file {host_resolv_path}: {exc}")
            return None

        return f"{host_resolv_path}:/etc/resolv.conf"

    def _prepare_environment(self):
        """Prepare runtime environment, handle Android Termux special issues"""
        env = os.environ.copy()

        # In Android Termux, need to unset LD_PRELOAD to avoid termux-exec interference
        if self._is_android_environment():
            logger.info("Detected Android environment, adjusting environment variables...")

            # Unset LD_PRELOAD
            if 'LD_PRELOAD' in env:
                logger.debug("Unset LD_PRELOAD to avoid termux-exec interference")
                del env['LD_PRELOAD']

            # Set safer PATH
            termux_path = env.get('PATH', '')
            # Remove termux-specific paths that may cause problems
            path_parts = termux_path.split(':')
            safe_paths = []
            for path in path_parts:
                if not path.startswith('/data/data/com.termux/files/usr/libexec'):
                    safe_paths.append(path)

            env['PATH'] = ':'.join(safe_paths)
            logger.debug(f"Adjusted PATH: {env['PATH']}")

        # Inject container env overrides when script-based env export is unavailable.
        for key, value in (self._container_env_overrides or {}).items():
            env[key] = value

        return env

    def _maybe_patch_supervisord_socket(self, rootfs_dir):
        """Android compatibility: patch supervisord unix socket config to avoid hardlink behavior.

        Some images (including those using Python supervisor) create unix domain sockets via a
        hard-link strategy (os.link). On Android/Termux this can fail due to hard-link restrictions,
        causing supervisord to loop printing "Unlinking stale socket ...".

        Preferred workaround: convert unix_http_server to inet_http_server on 127.0.0.1 so
        supervisord can start without relying on hardlinks for unix socket creation.
        """
        if not self._is_android_environment():
            return

        # Image config patching is opt-in; prefer proot-level compatibility flags.
        if self._parse_env_bool(os.environ.get(self.ENABLE_IMAGE_PATCHES_ENV)) is not True:
            return

        if self._parse_env_bool(os.environ.get(self.DISABLE_SUPERVISOR_SOCKET_PATCH_ENV)) is True:
            return

        if not rootfs_dir:
            return

        candidate_paths = [
            os.path.join(rootfs_dir, 'etc', 'supervisord.conf'),
            os.path.join(rootfs_dir, 'etc', 'supervisor', 'supervisord.conf'),
        ]

        for config_path in candidate_paths:
            if not os.path.exists(config_path):
                continue

            try:
                with open(config_path, 'r', encoding='utf-8', errors='ignore') as handle:
                    original_lines = handle.read().splitlines()
            except OSError:
                continue

            # Fast check: only patch configs that define a unix socket control interface.
            if not any(line.strip() == '[unix_http_server]' for line in original_lines):
                continue
            if not any('supervisor.sock' in line for line in original_lines):
                continue
            # If inet server already exists, or supervisorctl already uses http, don't touch it.
            if any(line.strip() == '[inet_http_server]' for line in original_lines):
                continue
            if any(line.strip().startswith('serverurl=http') for line in original_lines):
                continue

            port = self.SUPERVISORD_INET_PORT
            changed = False
            patched = []
            in_unix = False
            in_supervisorctl = False
            inserted_inet = False

            def maybe_insert_inet():
                nonlocal inserted_inet, changed
                if inserted_inet:
                    return
                patched.append('[inet_http_server]')
                patched.append(f'port={port}')
                patched.append('')
                inserted_inet = True
                changed = True

            for line in original_lines:
                stripped = line.strip()

                if stripped.startswith('[') and stripped.endswith(']') and len(stripped) > 2:
                    in_supervisorctl = (stripped.lower() == '[supervisorctl]')
                    if stripped.lower() == '[unix_http_server]':
                        in_unix = True
                        changed = True
                        continue
                    if in_unix:
                        in_unix = False

                    if stripped.lower() == '[supervisorctl]':
                        maybe_insert_inet()

                if in_unix:
                    continue

                if in_supervisorctl and stripped.startswith('serverurl=unix://'):
                    patched.append(f'serverurl=http://{port}')
                    changed = True
                    continue

                patched.append(line)

            if not changed:
                continue

            # Write a one-time backup for troubleshooting.
            backup_path = config_path + '.android-docker-cli.bak'
            try:
                if not os.path.exists(backup_path):
                    with open(backup_path, 'w', encoding='utf-8', errors='ignore') as handle:
                        handle.write('\n'.join(original_lines) + '\n')
            except OSError:
                pass

            try:
                with open(config_path, 'w', encoding='utf-8', errors='ignore') as handle:
                    handle.write('\n'.join(patched) + '\n')
                logger.info(f"Android compatibility: Changed supervisord unix socket to inet_http_server: {config_path}")
            except OSError:
                pass

    def run(self, input_path, args, rootfs_dir=None, pid_file=None):
        """Run container (one-stop service)"""
        log_file_handle = None
        try:
            # Check dependencies
            if not self._check_dependencies():
                return False

            # Show warning in Android environment
            if self._is_android_environment():
                logger.warning("Running container in Android environment. Note: proot provides process isolation, not full containerization. Some system calls may not be supported, performance may be lower than native Docker.")

            # Prepare rootfs (download or use existing)
            logger.info("Preparing rootfs...")
            rootfs_dir = self._prepare_rootfs(input_path, args, provided_rootfs_dir=rootfs_dir)
            if not rootfs_dir:
                return False

            self.rootfs_dir = rootfs_dir

            # If command starts with '--', remove it
            if args.command and args.command[0] == '--':
                args.command = args.command[1:]

            # Find image config
            self._find_image_config()

            # Android compatibility patches for known runtime limitations.
            self._maybe_patch_supervisord_socket(self.rootfs_dir)

            # If running in background mode, force set to non-interactive
            if args.detach:
                args.interactive = False

            # Build proot command
            proot_cmd = self._build_proot_command(args)

            logger.info(f"Starting container...")
            logger.debug(f"proot command: {' '.join(proot_cmd)}")

            # Log file handling
            log_file_path = getattr(args, 'log_file', None)
            log_file_handle = None
            if log_file_path:
                try:
                    # Append to the log file
                    log_file_handle = open(log_file_path, 'a')
                except IOError as e:
                    logger.error(f"Cannot open log file {log_file_path}: {e}")

            # Run proot
            if args.detach:
                # Manually implement backgrounding (fork/exec)
                env = self._prepare_environment()
                pid_file_path = getattr(args, 'pid_file', None)

                try:
                    pid = os.fork()
                    if pid > 0:
                        # Parent process
                        logger.info(f"Container started in background, PID: {pid}")
                        if pid_file_path:
                            try:
                                with open(pid_file_path, 'w') as f:
                                    f.write(str(pid))
                                logger.debug(f"PID {pid} written to {pid_file_path}")
                            except IOError as e:
                                logger.error(f"Failed to write PID file: {e}")
                        # Parent processSuccessfully written PID and exiting
                        return True

                    # Child process
                    os.setsid() # Create new session, detach from controlling terminal
                    
                    # Redirect standard file descriptors
                    sys.stdout.flush()
                    sys.stderr.flush()
                    
                    stdout_dest = log_file_handle or open(os.devnull, 'wb')
                    stderr_dest = log_file_handle or open(os.devnull, 'wb')
                    
                    os.dup2(stdout_dest.fileno(), sys.stdout.fileno())
                    os.dup2(stderr_dest.fileno(), sys.stderr.fileno())
                    
                    # stdin redirected to /dev/null
                    with open(os.devnull, 'rb') as devnull:
                        os.dup2(devnull.fileno(), sys.stdin.fileno())

                    # Execute proot command
                    os.execvpe(proot_cmd[0], proot_cmd, env)

                except Exception as e:
                    logger.error(f"Background startup failed (fork/exec): {e}")
                    # Child process needs to manually exit if exec fails
                    sys.exit(1)
            else:
                # Run in foreground (interactive or non-interactive)
                logger.info("Entering container environment...")
                env = self._prepare_environment()
                
                # Set stdin/stdout/stderr based on whether it's interactive mode
                if getattr(args, 'interactive', False):
                    # Interactive mode: connect to terminal
                    subprocess.run(proot_cmd, env=env)
                else:
                    # Non-interactive mode: redirect to log file (if provided)
                    subprocess.run(proot_cmd, env=env, stdout=log_file_handle, stderr=log_file_handle)
                return True

        except KeyboardInterrupt:
            logger.info("User interrupted")
            return True
        except Exception as e:
            logger.error(f"Run failed: {e}")
            return False
        finally:
            # Close log file handle
            if log_file_handle:
                log_file_handle.close()

            # Only cleanup when running in foreground and we created a temporary directory
            if hasattr(args, 'detach') and not args.detach:
                self._cleanup()
    
    def _cleanup(self):
        """Cleanup temporary files"""
        if self.temp_dir and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
            logger.info(f"Cleaning up temporary directory: {self.temp_dir}")

    def list_cache(self):
        """List cached images"""
        if not os.path.exists(self.cache_dir):
            logger.info("Cache directory does not exist")
            return

        cache_files = []
        for filename in os.listdir(self.cache_dir):
            if filename.endswith('.tar.gz'):
                cache_path = os.path.join(self.cache_dir, filename)
                info_path = cache_path + '.info'

                # Get file information
                stat = os.stat(cache_path)
                size_mb = stat.st_size / 1024 / 1024

                # Try to read cache info
                image_url = "Unknown"
                created_time = "Unknown"

                if os.path.exists(info_path):
                    try:
                        with open(info_path, 'r') as f:
                            info = json.load(f)
                        image_url = info.get('image_url', 'Unknown')
                        created_time = info.get('created_time_str', 'Unknown')
                    except Exception:
                        pass

                cache_files.append({
                    'filename': filename,
                    'image_url': image_url,
                    'size_mb': size_mb,
                    'created_time': created_time
                })

        if not cache_files:
            logger.info("No cached images")
            return

        logger.info(f"Cache directory: {self.cache_dir}")
        logger.info(f"Total {len(cache_files)} cached images:")
        logger.info("-" * 80)

        for cache in cache_files:
            logger.info(f"File: {cache['filename']}")
            logger.info(f"Image: {cache['image_url']}")
            logger.info(f"Size: {cache['size_mb']:.2f} MB")
            logger.info(f"Created: {cache['created_time']}")
            logger.info("-" * 80)

    def clear_cache(self, image_url=None):
        """Clean cache"""
        if image_url:
            # Clean cache for specific image
            cache_path = self._get_image_cache_path(image_url)
            info_path = self._get_cache_info_path(image_url)

            removed = False
            for path in [cache_path, info_path]:
                if os.path.exists(path):
                    os.remove(path)
                    removed = True

            if removed:
                logger.info(f"Cleaned image cache: {image_url}")
            else:
                logger.info(f"Image not cached: {image_url}")
        else:
            # Clean all caches
            if os.path.exists(self.cache_dir):
                shutil.rmtree(self.cache_dir)
                self._ensure_cache_dir()
                logger.info("Cleaned all caches")
            else:
                logger.info("Cache directory does not exist")

def main():
    parser = argparse.ArgumentParser(
        description='One-stop service for running Docker images with proot',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run image URL directly
  %(prog)s alpine:latest
  %(prog)s swr.cn-north-4.myhuaweicloud.com/ddn-k8s/ghcr.io/snailyp/gemini-balance:latest-linuxarm64

  # withEnvironment variablesrun
  %(prog)s -e "API_KEY=sk-12345" -e "MODE=test" alpine:latest env

  # Use local rootfs
  %(prog)s -b /host/data:/container/data rootfs.tar.gz /bin/bash

  # Run in background
  %(prog)s -w /app -d nginx:alpine
  
  # Interactive run
  %(prog)s -it alpine:latest /bin/sh

  # Cache management
  %(prog)s --list-cache
  %(prog)s --clear-cache alpine:latest
        """
    )

    parser.add_argument(
        'image_or_rootfs',
        nargs='?',
        help='Docker image URL or rootfs path (tar file or directory)'
    )
    
    parser.add_argument(
        'command',
        nargs='*',
        help="Command to execute (default uses image's default command)"
    )
    
    parser.add_argument(
        '-e', '--env',
        action='append',
        default=[],
        help='Set environment variable (format: KEY=VALUE)'
    )
    
    parser.add_argument(
        '-b', '--bind',
        action='append', 
        default=[],
        help='Bind mount (format: HOST_PATH:CONTAINER_PATH)'
    )
    
    parser.add_argument(
        '-w', '--workdir',
        help='Working directory'
    )
    
    parser.add_argument(
        '-d', '--detach',
        action='store_true',
        help='Run in background'
    )
    
    parser.add_argument(
        '-it', '--interactive',
        action='store_true',
        help='Run container interactively (allocate pseudo-TTY and keep stdin open)'
    )
    
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Show verbose logs'
    )

    parser.add_argument(
        '--force-download',
        action='store_true',
        help='Force re-download image, ignore cache'
    )

    parser.add_argument(
        '--cache-dir',
        help='Specify cache directory path'
    )
    parser.add_argument('--username', help='Registry username')
    parser.add_argument('--password', help='Registry password')

    parser.add_argument(
        '--rootfs-dir',
        help='Specify persistent rootfs path (mainly used by docker_cli.py in background mode)'
    )
    parser.add_argument(
        '--pid-file',
        help='File path to save real PID in background mode (mainly used by docker_cli.py in background mode)'
    )

    parser.add_argument(
        '--log-file',
        help='File path to save container internal stdout/stderr in background mode (mainly used by docker_cli.py)'
    )
    
    parser.add_argument(
        '--list-cache',
        action='store_true',
        help='List cached images'
    )

    parser.add_argument(
        '--clear-cache',
        metavar='IMAGE_URL',
        help='Clean cache for specified image, or use "all" to clean all caches'
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Create runner instance
    runner = ProotRunner(cache_dir=args.cache_dir)

    # Handle cache management commands
    if args.list_cache:
        runner.list_cache()
        return

    if args.clear_cache:
        if args.clear_cache.lower() == 'all':
            runner.clear_cache()
        else:
            runner.clear_cache(args.clear_cache)
        return

    # Check if image or rootfs was provided
    if not args.image_or_rootfs:
        parser.error("Please provide Docker image URL or rootfs path")

    # Run container
    success = runner.run(args.image_or_rootfs, args, rootfs_dir=args.rootfs_dir, pid_file=args.pid_file)

    sys.exit(0 if success else 1)

if __name__ == '__main__':
    main()
