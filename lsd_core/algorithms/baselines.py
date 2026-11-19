"""
Benchmark Baselines for AI-Generated and Deepfake Detection.
Implements the required comparative baselines specified in the Roadmap (Pages 4, 7):

1. DIRE (ICCV 2023): Diffusion Reconstruction Error in pixel space: || I - D(z_hat) ||_1
2. LaRE² (CVPR 2024): Latent Reconstruction Error in latent space: || z_0 - z_hat ||_2^2
3. ADRD (PLOS ONE 2026): Adversarial/Perturbation Reconstruction Discrepancy
"""

import time
import torch
import torch.nn as nn
import torch.nn.functional as F
from typing import Dict, Any, Optional

from ..models.vae_encoder import LatentVAE
from ..models.score_model import DiffusionScoreModel
from ..utils.logger import check_tensor_health


class LaRE2Baseline(nn.Module):
    """
    LaRE² Baseline (CVPR 2024).
    Computes latent reconstruction error (squared L2 distance)
    between original latent z_0 and denoised latent z_hat.
    """
    def __init__(self, vae: LatentVAE, score_model: DiffusionScoreModel, default_sigma: float = 0.10):
        super().__init__()
        self.vae = vae
        self.score_model = score_model
        self.default_sigma = default_sigma

    @torch.no_grad()
    def forward(self, image: torch.Tensor, sigma: Optional[float] = None) -> Dict[str, Any]:
        start_time = time.time()
        sigma = sigma if sigma is not None else self.default_sigma
        
        # Latent encoding
        z_0 = self.vae.encode_image(image)
        
        # Perturbation
        noise = torch.randn_like(z_0)
        z_sigma = z_0 + sigma * noise
        
        # Denoised update
        _, z_hat = self.score_model.predict_score(z_sigma, sigma=sigma)
        
        # Squared L2 reconstruction error per spatial position (u, v):
        # sum((z_0 - z_hat)^2, dim=channel)
        squared_error_map = torch.sum((z_0 - z_hat) ** 2, dim=1)  # [B, h, w]
        
        # Global score: mean squared latent error
        global_score = torch.mean(squared_error_map, dim=(1, 2))  # [B]
        
        # Upsample to image size for localization comparison
        B, C, H, W = image.shape
        heatmap = F.interpolate(
            squared_error_map.unsqueeze(1),
            size=(H, W),
            mode="bilinear",
            align_corners=False
        ).squeeze(1)
        
        runtime_ms = (time.time() - start_time) * 1000.0
        
        return {
            "lare2_score": global_score.cpu().tolist(),
            "lare2_tensor": global_score,
            "msi": global_score.cpu().tolist(),
            "msi_tensor": global_score,
            "error_map": squared_error_map,
            "heatmap": heatmap,
            "runtime_ms": runtime_ms
        }

    compute_divergence = forward


class DIREBaseline(nn.Module):
    """
    DIRE Baseline (ICCV 2023).
    Reconstructs the image in pixel space: I_hat = D(z_hat)
    Computes absolute pixel reconstruction error: | I - I_hat |
    """
    def __init__(self, vae: LatentVAE, score_model: DiffusionScoreModel, default_sigma: float = 0.10):
        super().__init__()
        self.vae = vae
        self.score_model = score_model
        self.default_sigma = default_sigma

    @torch.no_grad()
    def forward(self, image: torch.Tensor, sigma: Optional[float] = None) -> Dict[str, Any]:
        start_time = time.time()
        sigma = sigma if sigma is not None else self.default_sigma
        
        # Latent encoding
        z_0 = self.vae.encode_image(image)
        
        # Perturbation & Denoising
        noise = torch.randn_like(z_0)
        z_sigma = z_0 + sigma * noise
        _, z_hat = self.score_model.predict_score(z_sigma, sigma=sigma)
        
        # Decode back to pixel space
        reconstructed_image = self.vae.decode_latent(z_hat)
        
        # Pixel-space error: Mean absolute difference across RGB channels
        diff = torch.abs(image - reconstructed_image)  # [B, 3, H, W]
        dire_heatmap = torch.mean(diff, dim=1)         # [B, H, W]
        global_score = torch.mean(dire_heatmap, dim=(1, 2))  # [B]
        
        runtime_ms = (time.time() - start_time) * 1000.0
        
        return {
            "dire_score": global_score.cpu().tolist(),
            "dire_tensor": global_score,
            "msi": global_score.cpu().tolist(),
            "msi_tensor": global_score,
            "reconstructed_image": reconstructed_image,
            "heatmap": dire_heatmap,
            "runtime_ms": runtime_ms
        }

    compute_divergence = forward


class ADRDBaseline(nn.Module):
    """
    ADRD Baseline (PLOS ONE 2026).
    Adversarial/gradient-perturbed reconstruction discrepancy.
    Measures sensitivity under targeted high-frequency latent shifts.
    """
    def __init__(self, vae: LatentVAE, score_model: DiffusionScoreModel, default_sigma: float = 0.10):
        super().__init__()
        self.vae = vae
        self.score_model = score_model
        self.default_sigma = default_sigma

    @torch.no_grad()
    def forward(self, image: torch.Tensor, sigma: Optional[float] = None) -> Dict[str, Any]:
        start_time = time.time()
        sigma = sigma if sigma is not None else self.default_sigma
        
        z_0 = self.vae.encode_image(image)
        
        # High-frequency perturbation (Laplacian-filtered noise)
        noise = torch.randn_like(z_0)
        # Spatial differential filter simulating adversarial high frequency
        dx = noise[:, :, :, 1:] - noise[:, :, :, :-1]
        noise_hf = torch.zeros_like(noise)
        noise_hf[:, :, :, 1:] = dx
        
        z_perturbed = z_0 + sigma * noise_hf
        _, z_hat = self.score_model.predict_score(z_perturbed, sigma=sigma)
        
        # Relative discrepancy
        discrepancy = torch.norm(z_0 - z_hat, p=2, dim=1) / (torch.norm(z_0, p=2, dim=1) + 1e-8)
        global_score = torch.mean(discrepancy, dim=(1, 2))
        
        B, C, H, W = image.shape
        heatmap = F.interpolate(
            discrepancy.unsqueeze(1),
            size=(H, W),
            mode="bilinear",
            align_corners=False
        ).squeeze(1)
        
        runtime_ms = (time.time() - start_time) * 1000.0
        
        return {
            "adrd_score": global_score.cpu().tolist(),
            "adrd_tensor": global_score,
            "msi": global_score.cpu().tolist(),
            "msi_tensor": global_score,
            "heatmap": heatmap,
            "runtime_ms": runtime_ms
        }

    compute_divergence = forward
