import subprocess
from pathlib import Path

def run_command(command):
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except subprocess.TimeoutExpired:
        pass
    return None

def detect_gpu_hardware():
    gpus = {"nvidia": False, "intel": False}
    detection_commands = [
        "lspci | grep -E 'VGA|3D|Display'",
        "lshw -C display",
        "glxinfo -B | grep 'OpenGL renderer string'",
    ]

    for command in detection_commands:
        output = run_command(command)
        if not output:
            continue

        output_lower = output.lower()
        if "nvidia" in output_lower:
            gpus["nvidia"] = True
        if "intel" in output_lower:
            gpus["intel"] = True

        if gpus["nvidia"] or gpus["intel"]:
            return gpus

    return gpus

def get_loaded_kernel_modules():
    modules_output = run_command("lsmod")
    if not modules_output:
        return set()
    return {line.split()[0] for line in modules_output.splitlines() if line}

def check_nvidia_driver():
    driver_info = {
        "installed": False,
        "type": None,
        "modules_loaded": [],
        "packages": [],
    }
    loaded_modules = get_loaded_kernel_modules()
    proprietary_modules = {"nvidia", "nvidia_drm", "nvidia_modeset", "nvidia_uvm"}

    found_proprietary = proprietary_modules.intersection(loaded_modules)
    if found_proprietary:
        driver_info["modules_loaded"].extend(sorted(list(found_proprietary)))
        driver_info["installed"] = True
        driver_info["type"] = "proprietary NVIDIA"

    if "nouveau" in loaded_modules:
        driver_info["modules_loaded"].append("nouveau")
        driver_info["installed"] = True
        if not driver_info["type"]:
            driver_info["type"] = "nouveau (open-source)"

    if run_command("which nvidia-smi"):
        driver_info["installed"] = True
        driver_info["type"] = "proprietary NVIDIA"

    package_checks = [
        ("dpkg -l", "nvidia-driver", "dpkg"),
        ("rpm -qa", "nvidia-driver", "rpm"),
        ("pacman -Q", "nvidia", "pacman"),
        ("zypper se -i", "nvidia", "zypper"),
    ]
    for cmd, pattern, pkg_type in package_checks:
        if run_command(f"{cmd} | grep -E '{pattern}'"):
            driver_info["packages"].append(f"Found via {pkg_type}")
            driver_info["installed"] = True
            if not driver_info["type"]:
                driver_info["type"] = "proprietary NVIDIA"

    return driver_info

def check_intel_driver():
    driver_info = {
        "installed": False,
        "modules_loaded": [],
        "packages": [],
    }
    loaded_modules = get_loaded_kernel_modules()
    intel_modules = {"i915"}

    found_modules = intel_modules.intersection(loaded_modules)
    if found_modules:
        driver_info["modules_loaded"].extend(sorted(list(found_modules)))
        driver_info["installed"] = True

    package_checks = [
        ("dpkg -l", "mesa|xserver-xorg-video-intel", "dpkg"),
        ("rpm -qa", "mesa|xorg-x11-drv-intel", "rpm"),
        ("pacman -Q", "mesa|xf86-video-intel", "pacman"),
        ("zypper se -i", "Mesa|intel", "zypper"),
    ]
    for cmd, pattern, pkg_type in package_checks:
        if run_command(f"{cmd} | grep -E '{pattern}'"):
            driver_info["packages"].append(f"Found via {pkg_type}")
            driver_info["installed"] = True

    intel_gpu_path = Path("/sys/class/drm/")
    if intel_gpu_path.exists():
        for card in intel_gpu_path.glob("card*/device/vendor"):
            try:
                if card.read_text(encoding="utf-8").strip() == "0x8086":
                    driver_info["installed"] = True
                    break
            except (IOError, OSError):
                continue

    return driver_info

def print_results(gpu_detected, driver_info, gpu_type):
    gpu_name = gpu_type.upper()

    if not gpu_detected:
        print(f"GPU Detected: No {gpu_name} GPU found")
        return

    print(f"GPU Detected: {gpu_name}")

    if driver_info["installed"]:
        if gpu_type == "nvidia" and driver_info["type"]:
            print(f"Driver Status: {driver_info['type']} driver installed")
        else:
            print(f"Driver Status: Open-source {gpu_name} driver installed")

        if driver_info["modules_loaded"]:
            modules = ", ".join(sorted(driver_info["modules_loaded"]))
            print(f"Loaded Modules: {modules}")
    else:
        print(f"Driver Status: No active {gpu_name} drivers detected.")
        print("Consider installing appropriate packages for your distribution.")

def main():
    print("Linux GPU Driver Detection")
    print("=" * 40 + "\n")

    gpus = detect_gpu_hardware()

    if gpus["nvidia"]:
        nvidia_info = check_nvidia_driver()
        print_results(gpus["nvidia"], nvidia_info, "nvidia")
        print()

    if gpus["intel"]:
        intel_info = check_intel_driver()
        print_results(gpus["intel"], intel_info, "intel")
        print()

    if not gpus["nvidia"] and not gpus["intel"]:
        print("Warning: Could not detect any supported GPU hardware.")
        print("This may be due to missing system utilities (e.g., lspci, lshw).")

if __name__ == "__main__":
    main()
