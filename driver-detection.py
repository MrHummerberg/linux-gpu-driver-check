#!/usr/bin/env python3
import logging
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    from colorama import Fore, Style, init as colorama_init
    colorama_init(autoreset=True)
    COLOR_ENABLED = True
except ImportError:
    # Create dummy color classes and functions if colorama is not installed
    COLOR_ENABLED = False
    class DummyColor:
        def __getattr__(self, name: str) -> str:
            return ""
    Fore = DummyColor()
    Style = DummyColor()

# -------------------- Logging Setup --------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s"
)

# -------------------- Constants --------------------

# --- Core System Commands ---
REQUIRED_COMMANDS: Set[str] = {"lspci", "lsmod"}

# --- GPU Hardware Detection ---
GPU_DETECTION_COMMANDS: List[List[str]] = [
    ["lspci"],
    ["lshw", "-C", "display"],
    ["glxinfo", "-B"],
]

# --- Kernel Module Definitions ---
NVIDIA_PROPRIETARY_MODULES: Set[str] = {"nvidia", "nvidia_drm", "nvidia_modeset", "nvidia_uvm"}
NVIDIA_OPEN_MODULES: Set[str] = {"nouveau"}
INTEL_MODULES: Set[str] = {"i915"}

# --- Package Manager Definitions ---
PACKAGE_MANAGERS: Dict[str, List[str]] = {
    "dpkg": ["dpkg", "-l"],
    "rpm": ["rpm", "-qa"],
    "pacman": ["pacman", "-Q"],
    "zypper": ["zypper", "se", "-i"],
}

# --- Package Name Patterns (as Regex) ---
NVIDIA_PACKAGE_PATTERNS: Dict[str, str] = {
    "dpkg": r"nvidia-driver|nvidia-\d+",
    "rpm": r"nvidia-driver|kmod-nvidia|akmod-nvidia",
    "pacman": r"nvidia",
    "zypper": r"nvidia",
}

INTEL_PACKAGE_PATTERNS: Dict[str, str] = {
    "dpkg": r"i965-va-driver|intel-media-va-driver|xserver-xorg-video-intel",
    "rpm": r"libva-intel-driver|xorg-x11-drv-intel",
    "pacman": r"libva-intel-driver|xf86-video-intel",
    "zypper": r"libva-intel-driver|xorg-x11-drv-intel",
}

# --- PCI Vendor IDs ---
VENDOR_IDS: Dict[str, str] = {
    "intel": "0x8086",
    "nvidia": "0x10de",
}

# -------------------- Color Utilities --------------------

def colorize(text: str, color: str) -> str:
    """Return colorized text if colorama is available."""
    return f"{color}{text}{Style.RESET_ALL}" if COLOR_ENABLED else text

def status_ok(text: str) -> str:
    """Return green-colored text for success status."""
    return colorize(text, Fore.GREEN)

def status_warn(text: str) -> str:
    """Return yellow-colored text for warning status."""
    return colorize(text, Fore.YELLOW)

def status_err(text: str) -> str:
    """Return red-colored text for error status."""
    return colorize(text, Fore.RED)

def status_info(text: str) -> str:
    """Return cyan-colored text for informational messages."""
    return colorize(text, Fore.CYAN)

def status_title(text: str) -> str:
    """Return magenta-colored text for titles."""
    return colorize(text, Fore.MAGENTA)

# -------------------- Utility Functions --------------------

def is_command_available(cmd: str) -> bool:
    """Check if a system command is available in PATH."""
    return shutil.which(cmd) is not None

def run_command(command: List[str], timeout: int = 5) -> Optional[str]:
    """
    Run a system command and return its stdout, or None on failure.
    Logs errors and timeouts.
    """
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False  # We check the returncode manually
        )
        if result.returncode == 0:
            return result.stdout.strip()
        else:
            logging.debug(
                f"Command '{' '.join(command)}' failed with code {result.returncode}: {result.stderr.strip()}"
            )
    except FileNotFoundError:
        logging.error(f"Command not found: {command[0]}")
    except subprocess.TimeoutExpired:
        logging.warning(f"Command timed out: {' '.join(command)}")
    except Exception as e:
        logging.error(f"Error running command '{' '.join(command)}': {e}")
    return None

def check_required_commands(commands: Set[str]) -> bool:
    """Ensure all required system commands are available."""
    missing = {cmd for cmd in commands if not is_command_available(cmd)}
    if missing:
        for cmd in sorted(missing):
            logging.error(f"Missing required system utility: {cmd}")
        return False
    return True

# -------------------- GPU Detection & Driver Checks --------------------

def detect_gpus() -> Dict[str, bool]:
    """
    Detect presence of NVIDIA and Intel GPUs using available system utilities.
    Returns a dict mapping vendor name to a boolean.
    """
    gpus: Dict[str, bool] = {"nvidia": False, "intel": False}
    for cmd in GPU_DETECTION_COMMANDS:
        if not is_command_available(cmd[0]):
            continue
        if output := run_command(cmd):
            out_lower = output.lower()
            if "nvidia" in out_lower:
                gpus["nvidia"] = True
            if "intel" in out_lower:
                gpus["intel"] = True
            if all(gpus.values()):
                break  # Stop early if all are found
    return gpus

def get_loaded_kernel_modules() -> Set[str]:
    """Get a set of currently loaded kernel module names."""
    if not (modules_output := run_command(["lsmod"])):
        return set()
    return {line.split()[0] for line in modules_output.splitlines()[1:] if line}

def check_packages(patterns: Dict[str, str]) -> List[str]:
    """Check for installed packages matching given regex patterns."""
    found_via = []
    for pm, cmd in PACKAGE_MANAGERS.items():
        if not is_command_available(cmd[0]):
            continue
        if (output := run_command(cmd)) and re.search(patterns[pm], output, re.IGNORECASE):
            found_via.append(f"Found via {pm}")
    return found_via

def check_nvidia_driver(loaded_modules: Set[str]) -> Dict[str, Any]:
    """Check for NVIDIA driver installation and status."""
    info: Dict[str, Any] = {"installed": False, "type": None, "modules_loaded": [], "packages": []}

    found_proprietary = NVIDIA_PROPRIETARY_MODULES & loaded_modules
    found_nouveau = NVIDIA_OPEN_MODULES & loaded_modules

    if found_proprietary:
        info.update({"installed": True, "type": "proprietary NVIDIA", "modules_loaded": sorted(found_proprietary)})
    elif found_nouveau:
        info.update({"installed": True, "type": "nouveau (open-source)", "modules_loaded": sorted(found_nouveau)})

    # nvidia-smi is a definitive sign of the proprietary driver
    if is_command_available("nvidia-smi") and run_command(["nvidia-smi"]):
        info["installed"] = True
        info["type"] = "proprietary NVIDIA"

    # If no modules are loaded, check for installed packages as a fallback
    if not info["installed"]:
        if packages := check_packages(NVIDIA_PACKAGE_PATTERNS):
            info.update({"installed": True, "type": "proprietary NVIDIA (inactive)", "packages": packages})
    return info

def check_intel_driver(loaded_modules: Set[str]) -> Dict[str, Any]:
    """Check for Intel driver installation and status."""
    info: Dict[str, Any] = {"installed": False, "modules_loaded": [], "packages": []}

    found_modules = INTEL_MODULES & loaded_modules
    if found_modules:
        info.update({"installed": True, "modules_loaded": sorted(found_modules)})

    # Corroborate with package checks or use them as a fallback
    if packages := check_packages(INTEL_PACKAGE_PATTERNS):
        info["installed"] = True
        info["packages"] = packages
    
    return info

# -------------------- Output & Main Logic --------------------

def print_results(gpu_detected: bool, driver_info: Dict[str, Any], gpu_type: str) -> None:
    """Print formatted results for a given GPU and its driver info."""
    gpu_name = gpu_type.upper()
    print(status_title(f"----- {gpu_name} GPU -----"))

    if not gpu_detected:
        print(f"{status_warn('Detection:')} {gpu_name} hardware not found.")
        return

    print(f"{status_ok('Detection:')} {gpu_name} hardware found.")

    if driver_info["installed"]:
        driver_type = driver_info.get("type", f"open-source {gpu_name}")
        print(f"{status_ok('Driver Status:')} {driver_type.capitalize()} driver detected.")
        if modules := driver_info.get("modules_loaded"):
            print(f"{status_info('  -> Loaded Modules:')} {', '.join(modules)}")
        if packages := driver_info.get("packages"):
            print(f"{status_info('  -> Detected Packages:')} {', '.join(packages)}")
    else:
        print(f"{status_err('Driver Status:')} No active {gpu_name} driver detected.")
        print(status_warn("  -> Consider installing the appropriate drivers for your distribution."))

def main() -> None:
    """Main entry point for GPU driver detection."""
    print(status_title("\nLinux GPU & Driver Detection Utility"))
    print("=" * 40)

    if not check_required_commands(REQUIRED_COMMANDS):
        print(status_err("\nAborting: Missing one or more required system utilities."))
        sys.exit(1)

    # Perform detection once to avoid redundant calls
    gpus_found = detect_gpus()
    loaded_modules = get_loaded_kernel_modules()
    any_gpu_processed = False
    print()

    # --- Vendor-specific checks ---
    if gpus_found.get("nvidia"):
        nvidia_info = check_nvidia_driver(loaded_modules)
        print_results(True, nvidia_info, "nvidia")
        print()
        any_gpu_processed = True

    if gpus_found.get("intel"):
        intel_info = check_intel_driver(loaded_modules)
        print_results(True, intel_info, "intel")
        print()
        any_gpu_processed = True

    if not any_gpu_processed:
        print(status_warn("Warning: Could not detect any supported GPU hardware (NVIDIA, Intel)."))
        print(status_info("This may be due to missing optional utilities (lshw, glxinfo) or an unsupported GPU."))

if __name__ == "__main__":
    main()
