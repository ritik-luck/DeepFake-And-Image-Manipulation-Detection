"""
Device detection, memory optimization, and hardware acceleration utilities.
Supports NVIDIA CUDA, Apple Silicon MPS (Metal Performance Shaders), and CPU.
"""

import torch
import os
import gc


def get_optimal_device(preference: str = "auto") -> torch.device:
    """
    Selects the best available computational device.
    Priority: CUDA > MPS (Apple Silicon) > CPU
    """
    if preference != "auto":
        return torch.device(preference)
        
    if torch.cuda.is_available():
        device = torch.device("cuda")
    elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        # Apple Silicon Mac
        device = torch.device("mps")
    else:
        device = torch.device("cpu")
        
    return device


def get_optimal_dtype(device: torch.device, requested_dtype: str = "float32") -> torch.dtype:
    """
    Returns appropriate torch dtype based on device capabilities.
    MPS and older CUDA GPUs benefit from float16 or float32.
    """
    if requested_dtype == "float16":
        return torch.float16
    elif requested_dtype == "bfloat16":
        if device.type == "cuda" and torch.cuda.is_bf16_supported():
            return torch.bfloat16
        return torch.float32
    return torch.float32


def clear_device_memory(device: torch.device):
    """
    Clears memory cache on CUDA or MPS to prevent Out-Of-Memory (OOM) during batch processing.
    """
    gc.collect()
    if device.type == "cuda":
        torch.cuda.empty_cache()
    elif device.type == "mps":
        if hasattr(torch.mps, "empty_cache"):
            torch.mps.empty_cache()
