"""
System Service
Handles gathering system information such as CPU, memory, disk, and uptime.
"""

import subprocess
import logging


def get_system_status() -> str:
    """
    Returns a string with system status: CPU temp, uptime, load, disk and memory usage.
    """

    try:
        # --- CPU Temperature ---
        temp_out = subprocess.check_output(
            ["vcgencmd", "measure_temp"], text=True, stderr=subprocess.DEVNULL
        ).strip()
        temp = temp_out.replace("temp=", "") if temp_out.startswith("temp=") else "N/A"

        # --- Uptime ---
        uptime_out = subprocess.check_output(
            ["uptime", "-p"], text=True, stderr=subprocess.DEVNULL
        ).strip()
        uptime = uptime_out.replace("up ", "") if uptime_out else "N/A"

        # --- CPU Load ---
        load_out = subprocess.check_output(
            ["uptime"], text=True, stderr=subprocess.DEVNULL
        ).strip()
        load = load_out.split("load average:")[-1].strip() if "load average:" in load_out else "N/A"

        # --- Disk Usage (root /) ---
        disk_out = subprocess.check_output(
            ["df", "-h", "/"], text=True, stderr=subprocess.DEVNULL
        ).strip().split("\n")
        disk_percent = disk_out[1].split()[4] if len(disk_out) >= 2 else "N/A"

        # --- Memory Usage ---
        mem_out = subprocess.check_output(
            ["free", "-h"], text=True, stderr=subprocess.DEVNULL
        ).strip().split("\n")
        if len(mem_out) >= 2:
            mem_values = mem_out[1].split()
            used_mem = mem_values[2]
            total_mem = mem_values[1]
            try:
                mem_percent = str(int(float(used_mem[:-1].replace("Gi","").replace("Mi","")) /
                                      float(total_mem[:-1].replace("Gi","").replace("Mi","")) * 100)) + "%"
            except Exception:
                mem_percent = f"{used_mem}/{total_mem}"
        else:
            mem_percent = "N/A"

        # --- Build status string ---
        status_msg = (
            "<strong>TARS Pi Status</strong>\n\n"
            f"- CPU Temperature: {temp}\n"
            f"- Uptime: {uptime}\n"
            f"- CPU Load (1,5,15 min): {load}\n"
            f"- Disk Usage: {disk_percent}\n"
            f"- Memory Usage: {mem_percent}\n"
        )

        return status_msg

    except Exception as e:
        logging.error(f"System status error: {e}")
        return f"Ошибка получения статуса системы. Данные временно не доступны."
