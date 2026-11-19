"""
Logging and Numerical Health-Check Utilities.
Monitors intermediate tensors, checks for NaNs, infs, zero-norm vectors,
and invalid inputs as specified in Roadmap Phase 3, Step 4.
"""

import os
import sys
import time
import json
import logging
import torch
import numpy as np
from typing import Dict, Any, Optional


def setup_logger(name: str = "LSD_Research", log_file: Optional[str] = None, level=logging.INFO) -> logging.Logger:
    """Configures formatted console and file logger."""
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # Avoid duplicate handlers
    if not logger.handlers:
        formatter = logging.Formatter(
            fmt="[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        
        if log_file:
            os.makedirs(os.path.dirname(os.path.abspath(log_file)), exist_ok=True)
            file_handler = logging.FileHandler(log_file)
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
            
    return logger


def check_tensor_health(tensor: torch.Tensor, tensor_name: str, logger: Optional[logging.Logger] = None) -> bool:
    """
    Validates tensor numerical integrity:
    1. Checks for NaN (Not a Number)
    2. Checks for Inf (Infinity)
    3. Checks for abnormal zero-norm vectors
    """
    if not isinstance(tensor, torch.Tensor):
        return True
        
    has_nan = torch.isnan(tensor).any().item()
    has_inf = torch.isinf(tensor).any().item()
    
    if has_nan or has_inf:
        msg = f"CRITICAL: Tensor '{tensor_name}' contains NaN={has_nan}, Inf={has_inf}! Shape: {list(tensor.shape)}"
        if logger:
            logger.error(msg)
        else:
            print(msg)
        return False
        
    norm = torch.norm(tensor.detach().float()).item()
    if norm < 1e-12 and tensor.numel() > 0:
        msg = f"WARNING: Tensor '{tensor_name}' has near-zero norm ({norm:.2e}). Possible vanishing feature vector."
        if logger:
            logger.warning(msg)
            
    return True


class ExperimentTracker:
    """Logs sample metadata, runtimes, scores, and reproducibility details."""
    
    def __init__(self, output_path: str):
        self.output_path = output_path
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        self.records = []
        
    def log_sample(self, image_id: str, label: int, msi_score: float, lare2_score: float, dire_score: float, runtime_ms: float, metadata: Dict[str, Any]):
        record = {
            "image_id": str(image_id),
            "label": int(label),
            "msi_score": float(msi_score),
            "lare2_score": float(lare2_score),
            "dire_score": float(dire_score),
            "runtime_ms": float(runtime_ms),
            "metadata": metadata
        }
        self.records.append(record)
        
    def save(self):
        with open(self.output_path, "w") as f:
            json.dump(self.records, f, indent=2)
