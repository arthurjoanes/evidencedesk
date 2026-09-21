"""Validate real CUDA computation without loading a model or contacting a provider."""

from __future__ import annotations

import importlib.metadata
import json
import platform
import resource
from pathlib import Path

import psutil
import torch


def hardware() -> dict:
    return {
        "platform": platform.platform(),
        "torch": torch.__version__,
        "cuda_runtime": torch.version.cuda,
        "cuda_available": torch.cuda.is_available(),
        "ram_available_gib": round(psutil.virtual_memory().available / 2**30, 2),
        "process_peak_rss_mib": round(
            resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 2
        ),
        "cgroup_memory_max": Path("/sys/fs/cgroup/memory.max").read_text().strip(),
        "cgroup_memory_current": int(Path("/sys/fs/cgroup/memory.current").read_text()),
        "packages": {
            name: importlib.metadata.version(name)
            for name in (
                "sentence-transformers",
                "transformers",
                "datasets",
                "mlflow-skinny",
            )
        },
    }


def main() -> None:
    report = hardware()
    if not torch.cuda.is_available():
        raise RuntimeError(
            "GPU CUDA indisponível; não iniciar treino por fallback implícito."
        )
    a = torch.ones((64, 64), device="cuda")
    b = a @ a
    torch.cuda.synchronize()
    if b[0, 0].item() != 64:
        raise RuntimeError("Smoke de multiplicação CUDA falhou.")
    free, total = torch.cuda.mem_get_info()
    report.update(
        gpu=torch.cuda.get_device_name(),
        capability=list(torch.cuda.get_device_capability()),
        cuda_arches=torch.cuda.get_arch_list(),
        vram_free_gib=round(free / 2**30, 2),
        vram_total_gib=round(total / 2**30, 2),
        status="cuda_computation_passed",
    )
    destination = Path("/runs/preflight.json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
