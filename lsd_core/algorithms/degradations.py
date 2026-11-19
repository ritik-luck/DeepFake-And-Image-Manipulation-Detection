"""
Robustness Degradation Suite.
Implements Phase 4 Step 4 of the LSD Roadmap:
"Apply JPEG compression at several quality levels, blur, and resizing to both real and generated images
using the same transformations."
"""

import io
import torch
import torchvision.transforms.functional as TF
from PIL import Image
import numpy as np


def apply_jpeg_compression(image_tensor: torch.Tensor, quality: int = 75) -> torch.Tensor:
    """
    Applies authentic JPEG compression with discrete cosine transform quantization.
    Input: [B, 3, H, W] in [-1, 1]
    Output: [B, 3, H, W] in [-1, 1]
    """
    # Convert from [-1, 1] to uint8 [0, 255]
    img_uint8 = ((image_tensor.clone().detach().cpu() + 1.0) * 127.5).clamp(0, 255).to(torch.uint8)
    
    degraded_batch = []
    for b in range(img_uint8.shape[0]):
        pil_img = TF.to_pil_image(img_uint8[b])
        buffer = io.BytesIO()
        pil_img.save(buffer, format="JPEG", quality=quality)
        buffer.seek(0)
        reloaded = Image.open(buffer)
        t_reloaded = TF.to_tensor(reloaded)  # [3, H, W] in [0, 1]
        t_norm = (t_reloaded * 2.0) - 1.0     # in [-1, 1]
        degraded_batch.append(t_norm)
        
    out = torch.stack(degraded_batch, dim=0).to(device=image_tensor.device, dtype=image_tensor.dtype)
    return out


def apply_gaussian_blur(image_tensor: torch.Tensor, kernel_size: int = 5, sigma: float = 1.5) -> torch.Tensor:
    """
    Applies 2D Gaussian blur filter.
    Input: [B, 3, H, W] in [-1, 1]
    """
    return TF.gaussian_blur(image_tensor, kernel_size=[kernel_size, kernel_size], sigma=[sigma, sigma])


def apply_resize_degradation(image_tensor: torch.Tensor, scale_factor: float = 0.5) -> torch.Tensor:
    """
    Simulates downsampling and subsequent upsampling (common on social media platforms).
    Input: [B, 3, H, W] in [-1, 1]
    """
    B, C, H, W = image_tensor.shape
    down_h, down_w = max(16, int(H * scale_factor)), max(16, int(W * scale_factor))
    
    # Downsample
    downsampled = TF.resize(image_tensor, [down_h, down_w], interpolation=TF.InterpolationMode.BILINEAR)
    # Restore to original dimensions
    restored = TF.resize(downsampled, [H, W], interpolation=TF.InterpolationMode.BILINEAR)
    return restored
