"""Probe OpenVINO devices. Run this FIRST, before anything else:

    .venv\\Scripts\\python scripts\\probe_devices.py

Needs only `pip install openvino`. Exits 0 if the NPU enumerates, 1 otherwise.
"""

import sys

import openvino as ov


def main() -> int:
    core = ov.Core()
    devices = core.available_devices
    print(f"OpenVINO {ov.get_version()}")
    print(f"available devices: {devices}")
    for dev in devices:
        try:
            name = core.get_property(dev, "FULL_DEVICE_NAME")
        except Exception as exc:
            name = f"<could not query: {exc}>"
        print(f"  {dev}: {name}")

    if any(d.startswith("NPU") for d in devices):
        print("\nNPU OK — safe to proceed with NPU-first device order.")
        return 0

    print(
        "\nNPU NOT FOUND. Check Device Manager > Neural processors for"
        " 'Intel(R) AI Boost'.\n"
        "- Device missing entirely: enable the NPU in BIOS/UEFI.\n"
        "- Device present but not enumerating: install/update the Intel NPU"
        " driver ('Intel NPU Driver' from intel.com, or via Windows Update),\n"
        "  then reboot and re-run this probe.\n"
        "- Also ensure the 'openvino' pip package is current (2025.x)."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
