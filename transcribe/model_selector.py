"""Hardware scanning and Whisper/ASR model recommendation engine."""

from dataclasses import dataclass
import os
import platform
import shutil
import subprocess
from typing import Optional

try:
    import psutil
except ImportError:
    psutil = None


@dataclass
class SystemSpecs:
    """Captured hardware and operating system specifications."""

    os_platform: str
    ram_total_gb: float
    ram_available_gb: float
    cpu_model: str
    cpu_physical_cores: int
    cpu_logical_cores: int
    cpu_freq_mhz: Optional[float]
    has_gpu: bool
    gpu_name: Optional[str]
    gpu_vram_gb: Optional[float]
    gpu_device_type: str  # 'cuda', 'mps', 'rocm', 'none'
    disk_free_gb: float


@dataclass
class ModelRecommendation:
    """Model recommendation based on hardware capabilities."""

    recommended_provider: str  # 'local' or 'deepgram'
    model_name: str  # 'tiny', 'base', 'small', 'medium', 'large-v3', 'deepgram-nova-2'
    device: str  # 'cuda', 'mps', 'cpu'
    compute_type: str  # 'float16', 'int8', 'int8_float16', 'default'
    estimated_ram_vram: str
    reason: str


def _get_cpu_name() -> str:
    """Retrieve human-readable CPU brand name."""
    try:
        if platform.system() == "Linux":
            with open("/proc/cpuinfo", "r") as f:
                for line in f:
                    if "model name" in line:
                        return line.split(":", 1)[1].strip()
        elif platform.system() == "Windows":
            return platform.processor() or "Generic x86_64 CPU"
        elif platform.system() == "Darwin":
            out = subprocess.check_output(["sysctl", "-n", "machdep.cpu.brand_string"]).decode().strip()
            return out or platform.processor()
    except Exception:
        pass
    return platform.processor() or "Unknown CPU"


def _detect_gpu() -> tuple[bool, Optional[str], Optional[float], str]:
    """Detect GPU hardware and VRAM across CUDA, Apple Silicon MPS, and ROCm."""
    # 1. Try PyTorch CUDA if available
    try:
        import torch

        if torch.cuda.is_available():
            name = torch.cuda.get_device_name(0)
            vram_bytes = torch.cuda.get_device_properties(0).total_memory
            vram_gb = round(vram_bytes / (1024**3), 2)
            return True, name, vram_gb, "cuda"
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return True, "Apple Silicon GPU (MPS)", None, "mps"
    except Exception:
        pass

    # 2. Check nvidia-smi command line
    try:
        cmd = ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"]
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, timeout=2).decode().strip()
        if out:
            line = out.splitlines()[0]
            parts = [p.strip() for p in line.split(",")]
            name = parts[0]
            vram_mb = float(parts[1]) if len(parts) > 1 else 0.0
            return True, name, round(vram_mb / 1024.0, 2), "cuda"
    except Exception:
        pass

    # 3. Check Apple Silicon macOS
    if platform.system() == "Darwin" and platform.machine() == "arm64":
        return True, "Apple Silicon Neural Engine / Metal", None, "mps"

    return False, None, None, "none"


def scan_system(cache_path: Optional[str] = None) -> SystemSpecs:
    """Scan and analyze system resources (RAM, CPU, GPU, Disk)."""
    os_name = f"{platform.system()} {platform.release()} ({platform.machine()})"

    if psutil:
        mem = psutil.virtual_memory()
        ram_total = round(mem.total / (1024**3), 2)
        ram_avail = round(mem.available / (1024**3), 2)
        cpu_phys = psutil.cpu_count(logical=False) or 1
        cpu_log = psutil.cpu_count(logical=True) or 1
        cpu_freq_info = psutil.cpu_freq()
        cpu_freq = round(cpu_freq_info.current, 1) if cpu_freq_info else None
    else:
        ram_total, ram_avail = 8.0, 4.0
        cpu_phys, cpu_log = 4, 4
        cpu_freq = None

    cpu_model = _get_cpu_name()
    has_gpu, gpu_name, gpu_vram, gpu_type = _detect_gpu()

    # Free disk space on cache partition
    target_dir = cache_path or os.getcwd()
    try:
        disk_usage = shutil.disk_usage(target_dir)
        disk_free_gb = round(disk_usage.free / (1024**3), 2)
    except Exception:
        disk_free_gb = 10.0

    return SystemSpecs(
        os_platform=os_name,
        ram_total_gb=ram_total,
        ram_available_gb=ram_avail,
        cpu_model=cpu_model,
        cpu_physical_cores=cpu_phys,
        cpu_logical_cores=cpu_log,
        cpu_freq_mhz=cpu_freq,
        has_gpu=has_gpu,
        gpu_name=gpu_name,
        gpu_vram_gb=gpu_vram,
        gpu_device_type=gpu_type,
        disk_free_gb=disk_free_gb,
    )


def suggest_model(specs: SystemSpecs) -> ModelRecommendation:
    """Determine the optimal Whisper model and runtime settings based on specs."""
    # 1. Dedicated NVIDIA / ROCm GPU
    if specs.has_gpu and specs.gpu_device_type == "cuda":
        vram = specs.gpu_vram_gb or 0.0
        if vram >= 8.0:
            return ModelRecommendation(
                recommended_provider="local",
                model_name="large-v3",
                device="cuda",
                compute_type="float16",
                estimated_ram_vram="~4.5 GB VRAM",
                reason=(
                    f"High-end NVIDIA GPU ({specs.gpu_name}, {vram:.1f} GB VRAM) detected. "
                    "Whisper large-v3 will deliver maximum transcription accuracy in real time."
                ),
            )
        elif vram >= 4.0:
            return ModelRecommendation(
                recommended_provider="local",
                model_name="small",
                device="cuda",
                compute_type="float16",
                estimated_ram_vram="~2.0 GB VRAM",
                reason=(
                    f"Mid-tier NVIDIA GPU ({specs.gpu_name}, {vram:.1f} GB VRAM) detected. "
                    "'small' (float16) offers low latency and excellent spoken translation accuracy."
                ),
            )
        else:
            return ModelRecommendation(
                recommended_provider="local",
                model_name="base",
                device="cuda",
                compute_type="int8_float16",
                estimated_ram_vram="~1.0 GB VRAM",
                reason=(
                    f"Entry-level GPU ({specs.gpu_name}, {vram:.1f} GB VRAM) detected. "
                    "'base' model fits comfortably within available VRAM."
                ),
            )

    # 2. Apple Silicon (MPS / unified memory)
    if specs.has_gpu and specs.gpu_device_type == "mps":
        if specs.ram_total_gb >= 16.0:
            return ModelRecommendation(
                recommended_provider="local",
                model_name="small",
                device="cpu",
                compute_type="int8",
                estimated_ram_vram="~1.5 GB RAM",
                reason=(
                    f"Apple Silicon ({specs.ram_total_gb:.1f} GB RAM) detected. "
                    "'small' (int8) running on ARM NEON/Accelerate provides fast real-time transcription."
                ),
            )
        else:
            return ModelRecommendation(
                recommended_provider="local",
                model_name="base",
                device="cpu",
                compute_type="int8",
                estimated_ram_vram="~1.0 GB RAM",
                reason=(
                    f"Apple Silicon ({specs.ram_total_gb:.1f} GB RAM) detected. "
                    "'base' (int8) balances low CPU consumption and snappy response."
                ),
            )

    # 3. CPU Only
    if specs.ram_total_gb >= 16.0:
        return ModelRecommendation(
            recommended_provider="local",
            model_name="small",
            device="cpu",
            compute_type="int8",
            estimated_ram_vram="~1.5 GB RAM",
            reason=(
                f"Sufficient CPU RAM ({specs.ram_total_gb:.1f} GB total, {specs.cpu_logical_cores} threads). "
                "'small' (int8) is recommended for local transcription."
            ),
        )
    elif specs.ram_total_gb >= 8.0:
        return ModelRecommendation(
            recommended_provider="local",
            model_name="base",
            device="cpu",
            compute_type="int8",
            estimated_ram_vram="~1.0 GB RAM",
            reason=(
                f"Moderate CPU RAM ({specs.ram_total_gb:.1f} GB total). "
                "'base' (int8) provides lightweight real-time transcription without audio lag."
            ),
        )
    else:
        return ModelRecommendation(
            recommended_provider="deepgram",
            model_name="deepgram-nova-2",
            device="cloud",
            compute_type="n/a",
            estimated_ram_vram="<100 MB RAM",
            reason=(
                f"Limited RAM ({specs.ram_total_gb:.1f} GB total). "
                "Cloud Deepgram (Nova-2) is strongly recommended for near-zero latency and high accuracy without host load."
            ),
        )


def print_system_specs(specs: SystemSpecs, recommendation: Optional[ModelRecommendation] = None) -> None:
    """Print hardware specs and model recommendation table."""
    try:
        from rich.console import Console
        from rich.table import Table
        from rich.panel import Panel

        console = Console()

        table = Table(title="[bold cyan]System Hardware Specifications[/bold cyan]", show_header=True)
        table.add_column("Component", style="cyan", width=18)
        table.add_column("Specification", style="white")

        table.add_row("Operating System", specs.os_platform)
        table.add_row(
            "System Memory (RAM)",
            f"{specs.ram_total_gb:.1f} GB Total ({specs.ram_available_gb:.1f} GB Available)",
        )
        freq_str = f" @ {specs.cpu_freq_mhz} MHz" if specs.cpu_freq_mhz else ""
        table.add_row(
            "Processor (CPU)",
            f"{specs.cpu_model} ({specs.cpu_physical_cores} Cores / {specs.cpu_logical_cores} Threads{freq_str})",
        )

        if specs.has_gpu:
            vram_str = f" ({specs.gpu_vram_gb:.1f} GB VRAM)" if specs.gpu_vram_gb else ""
            table.add_row("Graphics (GPU)", f"{specs.gpu_name}{vram_str} [{specs.gpu_device_type.upper()}]")
        else:
            table.add_row("Graphics (GPU)", "No dedicated GPU detected (CPU mode)")

        table.add_row("Disk Free Space", f"{specs.disk_free_gb:.1f} GB Free")

        console.print(table)

        if recommendation:
            rec_content = (
                f"[bold green]Suggested Provider:[/bold green] {recommendation.recommended_provider.upper()}\n"
                f"[bold green]Suggested Model:[/bold green]    {recommendation.model_name}\n"
                f"[bold green]Runtime Device:[/bold green]     {recommendation.device} ({recommendation.compute_type})\n"
                f"[bold green]Estimated Footprint:[/bold green]{recommendation.estimated_ram_vram}\n\n"
                f"[italic yellow]Rationale:[/italic yellow] {recommendation.reason}"
            )
            console.print(Panel(rec_content, title="[bold magenta]Model Recommendation[/bold magenta]"))
        return
    except ImportError:
        pass

    # Fallback ASCII table
    print("=" * 65)
    print(" SYSTEM HARDWARE SPECIFICATIONS ")
    print("=" * 65)
    print(f"OS:         {specs.os_platform}")
    print(f"RAM:        {specs.ram_total_gb:.1f} GB Total ({specs.ram_available_gb:.1f} GB Available)")
    print(f"CPU:        {specs.cpu_model} ({specs.cpu_physical_cores}C/{specs.cpu_logical_cores}T)")
    if specs.has_gpu:
        vram_str = f" ({specs.gpu_vram_gb:.1f} GB VRAM)" if specs.gpu_vram_gb else ""
        print(f"GPU:        {specs.gpu_name}{vram_str} [{specs.gpu_device_type}]")
    else:
        print("GPU:        None (CPU mode)")
    print(f"Disk Free:  {specs.disk_free_gb:.1f} GB")
    print("=" * 65)

    if recommendation:
        print("\nMODEL RECOMMENDATION:")
        print(f"Provider:   {recommendation.recommended_provider}")
        print(f"Model:      {recommendation.model_name} (Device: {recommendation.device}, Compute: {recommendation.compute_type})")
        print(f"Footprint:  {recommendation.estimated_ram_vram}")
        print(f"Reason:     {recommendation.reason}")
        print("=" * 65)
