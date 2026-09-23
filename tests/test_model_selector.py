"""Unit tests for system scanner and model recommendation engine."""

import pytest

from transcribe.model_selector import (
    ModelRecommendation,
    SystemSpecs,
    scan_system,
    suggest_model,
)


def make_specs(
    ram_total_gb: float = 16.0,
    has_gpu: bool = False,
    gpu_name: str = None,
    gpu_vram_gb: float = None,
    gpu_device_type: str = "none",
    logical_cores: int = 8,
) -> SystemSpecs:
    return SystemSpecs(
        os_platform="Linux 6.5.0-generic",
        ram_total_gb=ram_total_gb,
        ram_available_gb=ram_total_gb * 0.7,
        cpu_model="Mock CPU @ 3.0GHz",
        cpu_physical_cores=logical_cores // 2,
        cpu_logical_cores=logical_cores,
        cpu_freq_mhz=3000.0,
        has_gpu=has_gpu,
        gpu_name=gpu_name,
        gpu_vram_gb=gpu_vram_gb,
        gpu_device_type=gpu_device_type,
        disk_free_gb=100.0,
    )


def test_high_end_gpu_recommendation():
    """Systems with >= 8GB VRAM GPU should receive large-v3 recommendation."""
    specs = make_specs(
        ram_total_gb=32.0,
        has_gpu=True,
        gpu_name="NVIDIA GeForce RTX 4080",
        gpu_vram_gb=16.0,
        gpu_device_type="cuda",
    )
    rec = suggest_model(specs)
    assert rec.recommended_provider == "local"
    assert rec.model_name == "large-v3"
    assert rec.device == "cuda"
    assert rec.compute_type == "float16"


def test_mid_tier_gpu_recommendation():
    """Systems with 4-8GB VRAM GPU should receive small model recommendation."""
    specs = make_specs(
        ram_total_gb=16.0,
        has_gpu=True,
        gpu_name="NVIDIA GeForce RTX 3050",
        gpu_vram_gb=6.0,
        gpu_device_type="cuda",
    )
    rec = suggest_model(specs)
    assert rec.recommended_provider == "local"
    assert rec.model_name == "small"
    assert rec.device == "cuda"


def test_apple_silicon_recommendation():
    """Apple Silicon systems with MPS should receive appropriate models."""
    specs = make_specs(
        ram_total_gb=16.0,
        has_gpu=True,
        gpu_name="Apple Silicon Neural Engine / Metal",
        gpu_device_type="mps",
    )
    rec = suggest_model(specs)
    assert rec.recommended_provider == "local"
    assert rec.model_name == "small"
    assert rec.compute_type == "int8"


def test_cpu_high_ram_recommendation():
    """CPU-only system with >= 16GB RAM should get small model."""
    specs = make_specs(ram_total_gb=16.0, has_gpu=False, logical_cores=12)
    rec = suggest_model(specs)
    assert rec.recommended_provider == "local"
    assert rec.model_name == "small"
    assert rec.device == "cpu"


def test_cpu_medium_ram_recommendation():
    """CPU-only system with 8-16GB RAM should get base model."""
    specs = make_specs(ram_total_gb=8.0, has_gpu=False, logical_cores=8)
    rec = suggest_model(specs)
    assert rec.recommended_provider == "local"
    assert rec.model_name == "base"
    assert rec.device == "cpu"


def test_cpu_low_ram_recommendation():
    """CPU-only system with < 8GB RAM should recommend Deepgram cloud for performance."""
    specs = make_specs(ram_total_gb=4.0, has_gpu=False, logical_cores=4)
    rec = suggest_model(specs)
    assert rec.recommended_provider == "deepgram"
    assert rec.model_name == "deepgram-nova-2"
    assert rec.device == "cloud"


def test_scan_system_runs_without_exceptions():
    """Verify scan_system() executes and returns valid specs on the current host."""
    specs = scan_system()
    assert specs.ram_total_gb > 0
    assert specs.cpu_logical_cores >= 1
    assert specs.disk_free_gb >= 0
    assert isinstance(specs.os_platform, str)
