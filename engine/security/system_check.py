"""Báo cáo hoạt động hệ thống (CPU, RAM, ổ đĩa, tiến trình) cho tool check_system."""

import os
import time

import psutil

_GB = 1024 ** 3


def _fmt_uptime(seconds: float) -> str:
    h, rem = divmod(int(seconds), 3600)
    d, h = divmod(h, 24)
    return f"{d} ngày {h} giờ {rem // 60} phút" if d else f"{h} giờ {rem // 60} phút"


def _top_processes(n: int = 5) -> list[dict]:
    procs = list(psutil.process_iter(["pid", "name", "memory_percent"]))
    for p in procs:  # lần gọi đầu khởi tạo bộ đếm CPU, lần sau mới có số liệu
        try:
            p.cpu_percent(None)
        except psutil.Error:
            pass
    time.sleep(0.3)
    rows = []
    for p in procs:
        try:
            rows.append({
                "pid": p.pid,
                "name": p.info["name"] or "?",
                "cpu": p.cpu_percent(None) / (psutil.cpu_count() or 1),
                "mem": p.info["memory_percent"] or 0.0,
            })
        except psutil.Error:
            continue
    return sorted(rows, key=lambda r: r["cpu"] + r["mem"], reverse=True)[:n]


def run_system_check() -> str:
    cpu = psutil.cpu_percent(interval=0.3)
    ram = psutil.virtual_memory()
    swap = psutil.swap_memory()
    report = "🖥️ **[BÁO CÁO HOẠT ĐỘNG HỆ THỐNG]**\n\n"
    report += f"- **CPU:** {cpu:.0f}% ({psutil.cpu_count(logical=False) or '?'} nhân / {psutil.cpu_count()} luồng)\n"
    report += f"- **RAM:** {ram.percent:.0f}% ({ram.used / _GB:.1f}/{ram.total / _GB:.1f} GB); swap {swap.percent:.0f}%\n"
    report += f"- **Thời gian bật máy:** {_fmt_uptime(time.time() - psutil.boot_time())}\n"

    report += "\n💽 **Ổ đĩa:**\n"
    for part in psutil.disk_partitions(all=False):
        try:
            u = psutil.disk_usage(part.mountpoint)
        except OSError:
            continue
        report += f"- `{part.mountpoint}` {u.percent:.0f}% (còn {u.free / _GB:.1f} GB / {u.total / _GB:.1f} GB)\n"

    me = psutil.Process(os.getpid())
    report += (
        f"\n🤖 **Tiến trình JARVIS:** PID {me.pid}, RAM {me.memory_info().rss / 1024 ** 2:.0f} MB, "
        f"{me.num_threads()} luồng\n"
    )

    report += "\n📊 **Tiến trình nặng nhất:**\n"
    for r in _top_processes():
        report += f"- `{r['name']}` (PID {r['pid']}): CPU {r['cpu']:.1f}%, RAM {r['mem']:.1f}%\n"

    battery = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
    if battery:
        report += f"\n🔋 **Pin:** {battery.percent:.0f}% ({'đang sạc' if battery.power_plugged else 'dùng pin'})\n"
    return report
