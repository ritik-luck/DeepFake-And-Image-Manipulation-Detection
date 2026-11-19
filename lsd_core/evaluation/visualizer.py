"""
Visualization Utilities for Heatmaps, Overlays, and Metric Curves.
Generates publication-quality figures for localization maps and ROC curves.
"""

import os
import torch
import numpy as np
import matplotlib
matplotlib.use("Agg")  # Headless rendering
import matplotlib.pyplot as plt
from typing import Optional, Tuple


def overlay_heatmap_on_image(
    image_tensor: torch.Tensor,
    heatmap_tensor: torch.Tensor,
    alpha: float = 0.5,
    colormap: str = "jet"
) -> np.ndarray:
    """
    Overlays 2D heatmap on RGB image.
    Robust to any tensor shape: [3, H, W], [1, 3, H, W], [H, W], [1, H, W], [1, 1, h, w], etc.
    Automatically squeezes extra dimensions and bilinearly resizes heatmap to match image resolution.
    Returns: RGB uint8 numpy image [H, W, 3]
    """
    # 1. Denormalize and format image to [H, W, 3] in [0, 1]
    img = image_tensor.detach().cpu().float()
    while img.ndim > 3:
        img = img.squeeze(0)
    if img.ndim == 3 and img.shape[0] in [1, 3]:  # [C, H, W] -> [H, W, C]
        if img.shape[0] == 1:
            img = img.repeat(3, 1, 1)
        if img.min() < 0:
            img = (img + 1.0) / 2.0
        img = img.clamp(0, 1).permute(1, 2, 0)
    elif img.ndim == 2:  # [H, W] -> [H, W, 3]
        if img.min() < 0:
            img = (img + 1.0) / 2.0
        img = img.clamp(0, 1).unsqueeze(-1).repeat(1, 1, 3)
    
    H, W = img.shape[0], img.shape[1]
    img_np = img.numpy()
    
    # 2. Squeeze heatmap to strictly 2D [h, w]
    hm = heatmap_tensor.detach().cpu().float()
    while hm.ndim > 2:
        hm = hm.squeeze(0)
        
    # Guard against 1D or scalar anomalies
    if hm.ndim < 2:
        hm = torch.zeros((H, W), dtype=torch.float32)
        
    # 3. Resize heatmap if dimensions differ from image [H, W]
    if hm.shape != (H, W):
        hm_4d = hm.unsqueeze(0).unsqueeze(0)  # [1, 1, h, w]
        hm_resized = torch.nn.functional.interpolate(
            hm_4d,
            size=(H, W),
            mode="bilinear",
            align_corners=False
        )
        hm = hm_resized.squeeze(0).squeeze(0)
        
    hm_np = hm.numpy()
    
    # 4. Normalize heatmap to [0, 1]
    h_min, h_max = hm_np.min(), hm_np.max()
    if h_max > h_min:
        hm_norm = (hm_np - h_min) / (h_max - h_min)
    else:
        hm_norm = np.zeros_like(hm_np)
        
    cmap = plt.get_cmap(colormap)
    colored_hm = cmap(hm_norm)[:, :, :3]  # Drop alpha channel -> [H, W, 3]
    
    # 5. Blend overlay: alpha * heatmap + (1 - alpha) * original_image
    overlay = (alpha * colored_hm) + ((1.0 - alpha) * img_np)
    overlay = np.clip(overlay * 255.0, 0, 255).astype(np.uint8)
    return overlay


def save_localization_comparison_figure(
    image: torch.Tensor,
    lsd_heatmap: torch.Tensor,
    lare2_heatmap: Optional[torch.Tensor],
    gt_mask: Optional[torch.Tensor],
    save_path: str,
    title: str = "LSD Localization Map"
):
    """
    Saves a 4-panel comparison figure:
    1. Input RGB Image
    2. LSD Heatmap Overlay
    3. LaRE² Reconstruction Error Overlay (Baseline)
    4. Ground-Truth Mask (if available)
    """
    os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
    fig, axes = plt.subplots(1, 4, figsize=(18, 4.5))
    
    # 1. RGB
    img = image.detach().cpu().float()
    if img.min() < 0:
        img = (img + 1.0) / 2.0
    axes[0].imshow(img.clamp(0, 1).permute(1, 2, 0).numpy())
    axes[0].set_title("Input RGB")
    axes[0].axis("off")
    
    # 2. LSD Heatmap Overlay
    lsd_ov = overlay_heatmap_on_image(image, lsd_heatmap)
    axes[1].imshow(lsd_ov)
    axes[1].set_title("LSD Divergence Map (Proposed)")
    axes[1].axis("off")
    
    # 3. LaRE2 Overlay
    if lare2_heatmap is not None:
        lare2_ov = overlay_heatmap_on_image(image, lare2_heatmap)
        axes[2].imshow(lare2_ov)
        axes[2].set_title("LaRE² Latent L2 (Baseline)")
    else:
        axes[2].text(0.5, 0.5, "N/A", ha="center", va="center")
        axes[2].set_title("Baseline")
    axes[2].axis("off")
    
    # 4. Ground Truth
    if gt_mask is not None:
        gt = gt_mask.detach().cpu().float().squeeze().numpy()
        axes[3].imshow(gt, cmap="gray")
        axes[3].set_title("Ground Truth Mask")
    else:
        axes[3].text(0.5, 0.5, "No Mask Available", ha="center", va="center")
        axes[3].set_title("Ground Truth")
    axes[3].axis("off")
    
    plt.suptitle(title, fontsize=14, fontweight="bold")
    plt.tight_layout()
    plt.savefig(save_path, dpi=200, bbox_inches="tight")
    plt.close()
