"""
Latent Score Divergence (LSD) Algorithm.
Implements the core mathematical formulation defined in the LSD Deepfake Research Roadmap (Pages 2-4):

1. Latent Encoding: z_0 = E(I)
2. Gaussian Perturbation: z_sigma = z_0 + sigma * epsilon, epsilon ~ N(0, I)
3. Proposed Score Update: z_hat = z_sigma + sigma^2 * s_theta(z_sigma, sigma)
4. Local Cosine Divergence: Delta_LSD(u, v) = 1 - cos(z_0(u, v), z_hat(u, v))
5. Global Score (MSI): Mean of Delta_LSD over all spatial coordinates (u, v)
6. Candidate Localization Heatmap: Bilinear upsampling of Delta_LSD to input image resolution (H, W)
"""

import time
import torch
import torch.nn as nn
import torch.nn.functional as F
from typing import Dict, Any, Tuple, Optional

from ..models.vae_encoder import LatentVAE
from ..models.score_model import DiffusionScoreModel
from ..utils.logger import check_tensor_health


class LatentScoreDivergence(nn.Module):
    """
    Active Manifold Inversion Dynamics via Latent Score Divergence (LSD).
    Includes Phase 2 Performance Enhancements:
    - Multi-Scale Noise Ensembling (micro-texture + blend-seam + macro-structure)
    - Boundary-Aware & Facial Region Spatial Prior Masking
    - Directional Cosine + Relative Energy Composite Divergence
    """
    def __init__(
        self,
        vae: LatentVAE,
        score_model: DiffusionScoreModel,
        default_sigma: float = 0.10,
        epsilon_stab: float = 1e-8,
        use_multiscale: bool = True,
        multiscale_sigmas: Tuple[float, ...] = (0.05, 0.10, 0.20),
        multiscale_weights: Tuple[float, ...] = (0.25, 0.50, 0.25),
        use_spatial_masking: bool = True,
        spatial_focus: str = "face_prior",
        boundary_weight: float = 0.50,
        use_composite_divergence: bool = True,
        composite_energy_weight: float = 0.45,
        use_hf_perturbation: bool = True,
        hf_noise_alpha: float = 0.35,
        device: torch.device = torch.device("cpu"),
        dtype: torch.dtype = torch.float32
    ):
        super().__init__()
        self.vae = vae
        self.score_model = score_model
        self.default_sigma = default_sigma
        self.epsilon_stab = epsilon_stab
        self.use_multiscale = use_multiscale
        self.multiscale_sigmas = multiscale_sigmas
        self.multiscale_weights = multiscale_weights
        self.use_spatial_masking = use_spatial_masking
        self.spatial_focus = spatial_focus
        self.boundary_weight = boundary_weight
        self.use_composite_divergence = use_composite_divergence
        self.composite_energy_weight = composite_energy_weight
        self.use_hf_perturbation = use_hf_perturbation
        self.hf_noise_alpha = hf_noise_alpha
        self.device = device
        self.dtype = dtype

    def perturb_latent(
        self,
        z_0: torch.Tensor,
        sigma: float,
        seed: Optional[int] = None
    ) -> Tuple[torch.Tensor, torch.Tensor]:
        """
        Perturbation step with High-Frequency Spectral Gradient Injection:
        z_sigma = z_0 + sigma * epsilon_hybrid
        where epsilon_hybrid = (1 - alpha) * epsilon + alpha * Laplacian(epsilon)
        Sensitizes diffusion inversion dynamics to microscopic blending seams and GAN frequency discrepancies.
        """
        generator = None
        if seed is not None:
            generator = torch.Generator(device=z_0.device).manual_seed(seed)
            
        noise = torch.randn(
            z_0.shape,
            generator=generator,
            device=z_0.device,
            dtype=z_0.dtype
        )
        
        if self.use_hf_perturbation and self.hf_noise_alpha > 0.0:
            # 2D discrete spatial differential (Laplacian gradient)
            dx = torch.zeros_like(noise)
            dy = torch.zeros_like(noise)
            dx[:, :, :, 1:] = noise[:, :, :, 1:] - noise[:, :, :, :-1]
            dy[:, :, 1:, :] = noise[:, :, 1:, :] - noise[:, :, :-1, :]
            noise_hf = 0.5 * (dx + dy)
            std_hf = torch.std(noise_hf, dim=(1, 2, 3), keepdim=True) + self.epsilon_stab
            noise_hf = noise_hf / std_hf
            effective_noise = (1.0 - self.hf_noise_alpha) * noise + (self.hf_noise_alpha * noise_hf)
        else:
            effective_noise = noise

        z_sigma = z_0 + sigma * effective_noise
        check_tensor_health(z_sigma, "z_perturbed")
        return z_sigma, effective_noise

    def compute_local_cosine_divergence(
        self,
        z_0: torch.Tensor,
        z_hat: torch.Tensor
    ) -> torch.Tensor:
        """
        Calculates local cosine divergence at every spatial position (u, v):
        Delta_LSD(u, v) = 1 - cos(z_0(u, v), z_hat(u, v))
        Input shape: [B, C, h, w]
        Output shape: [B, h, w]
        """
        dot_product = torch.sum(z_0 * z_hat, dim=1)  # [B, h, w]
        norm_z0 = torch.norm(z_0, p=2, dim=1)      # [B, h, w]
        norm_zhat = torch.norm(z_hat, p=2, dim=1)  # [B, h, w]
        
        denominator = (norm_z0 * norm_zhat) + self.epsilon_stab
        cosine_sim = dot_product / denominator
        cosine_sim = torch.clamp(cosine_sim, -1.0, 1.0)
        
        delta_cos = 1.0 - cosine_sim  # [B, h, w], values in [0, 2]
        
        if self.use_composite_divergence:
            # Relative Latent Energy Divergence: ||z_0 - z_hat|| / (||z_0|| + eps)
            diff_norm = torch.norm(z_0 - z_hat, p=2, dim=1)
            delta_energy = diff_norm / (norm_z0 + self.epsilon_stab)
            delta_lsd = delta_cos + (self.composite_energy_weight * delta_energy)
        else:
            delta_lsd = delta_cos

        check_tensor_health(delta_lsd, "delta_lsd")
        return delta_lsd

    def compute_spatial_weights(
        self,
        z_0: torch.Tensor
    ) -> torch.Tensor:
        """
        Computes spatial attention weights [B, h, w] to focus divergence scoring
        on facial regions and manipulation boundaries, filtering out static backgrounds.
        """
        B, C, h, w = z_0.shape
        device = z_0.device
        
        # 1. Elliptical Gaussian Facial Region Prior
        v_coords = torch.linspace(-1.0, 1.0, h, device=device)
        u_coords = torch.linspace(-1.0, 1.0, w, device=device)
        grid_v, grid_u = torch.meshgrid(v_coords, u_coords, indexing="ij")
        
        # Centered ellipse covering facial landmarks (sigma_u=0.45, sigma_v=0.55)
        face_prior = torch.exp(-(grid_u**2 / (2 * 0.45**2) + grid_v**2 / (2 * 0.55**2)))  # [h, w]
        weights = face_prior.unsqueeze(0).expand(B, -1, -1).clone()  # [B, h, w]
        
        # 2. Boundary Gradient Attention (Boosts sensitivity along face-swap blend seams)
        if self.boundary_weight > 0.0:
            # Compute spatial gradients in latent space
            grad_v = torch.abs(z_0[:, :, 1:, :] - z_0[:, :, :-1, :])
            grad_u = torch.abs(z_0[:, :, :, 1:] - z_0[:, :, :, :-1])
            
            # Pad back to [B, C, h, w]
            grad_v = F.pad(grad_v, (0, 0, 0, 1), mode="replicate")
            grad_u = F.pad(grad_u, (0, 1, 0, 0), mode="replicate")
            
            latent_edges = torch.mean(grad_v + grad_u, dim=1)  # [B, h, w]
            edge_norm = latent_edges / (torch.amax(latent_edges, dim=(1, 2), keepdim=True) + self.epsilon_stab)
            
            weights = weights * (1.0 + (self.boundary_weight * edge_norm))
            
        return weights

    def generate_candidate_heatmap(
        self,
        delta_lsd: torch.Tensor,
        target_size: Tuple[int, int]
    ) -> torch.Tensor:
        """
        Upsamples latent divergence map [B, h, w] to original image resolution [B, H, W]
        using smooth bilinear interpolation.
        """
        delta_4d = delta_lsd.unsqueeze(1)
        heatmap_4d = F.interpolate(
            delta_4d,
            size=target_size,
            mode="bilinear",
            align_corners=False
        )
        heatmap = heatmap_4d.squeeze(1)  # [B, H, W]
        return heatmap

    @torch.no_grad()
    def compute_divergence(
        self,
        image: torch.Tensor,
        sigma: Optional[float] = None
    ) -> Dict[str, Any]:
        """Convenience wrapper consistent with baseline APIs."""
        return self.forward(image, sigma=sigma)

    @torch.no_grad()
    def forward(
        self,
        image: torch.Tensor,
        sigma: Optional[float] = None,
        seed: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Executes end-to-end LSD pipeline on input image tensor [B, 3, H, W] in [-1, 1].
        Supports Multi-Scale Noise Ensembling and Boundary-Aware Spatial Prior Masking.
        """
        start_time = time.time()
        B, C, H, W = image.shape
        
        # Step 1: Latent Encoding
        z_0 = self.vae.encode_image(image)
        
        # Step 2: Multi-Scale or Single-Scale Latent Score Divergence
        if sigma is not None or not self.use_multiscale:
            # Single-scale evaluation
            sig = sigma if sigma is not None else self.default_sigma
            z_sigma, _ = self.perturb_latent(z_0, sigma=sig, seed=seed)
            score, z_hat = self.score_model.predict_score(z_sigma, sigma=sig)
            delta_map = self.compute_local_cosine_divergence(z_0, z_hat)
            used_sigma = sig
        else:
            # Multi-scale ensembling across microscopic, intermediate, and structural regimes
            accum_delta = torch.zeros(B, z_0.shape[2], z_0.shape[3], device=z_0.device, dtype=z_0.dtype)
            total_w = sum(self.multiscale_weights)
            norm_weights = [w / total_w for w in self.multiscale_weights]
            
            last_score, last_z_hat = None, None
            for sig, w in zip(self.multiscale_sigmas, norm_weights):
                z_sig, _ = self.perturb_latent(z_0, sigma=sig, seed=seed)
                score, z_hat = self.score_model.predict_score(z_sig, sigma=sig)
                scale_delta = self.compute_local_cosine_divergence(z_0, z_hat)
                accum_delta = accum_delta + (w * scale_delta)
                last_score, last_z_hat = score, z_hat
                
            delta_map = accum_delta
            score, z_hat = last_score, last_z_hat
            used_sigma = list(self.multiscale_sigmas)
        
        # Step 3: Spatial Masking & Global Score Computation
        if self.use_spatial_masking and self.spatial_focus != "none":
            weights = self.compute_spatial_weights(z_0)
            weighted_delta = delta_map * weights
            msi = torch.sum(weighted_delta, dim=(1, 2)) / (torch.sum(weights, dim=(1, 2)) + self.epsilon_stab)
        else:
            msi = torch.mean(delta_map, dim=(1, 2))
        
        # Step 4: Upsampled Candidate Localization Map
        heatmap = self.generate_candidate_heatmap(delta_map, target_size=(H, W))
        
        runtime_ms = (time.time() - start_time) * 1000.0
        
        return {
            "msi": msi.cpu().tolist(),
            "msi_tensor": msi,
            "delta_map": delta_map,
            "heatmap": heatmap,
            "z_0": z_0,
            "z_hat": z_hat,
            "score": score,
            "sigma": used_sigma,
            "runtime_ms": runtime_ms
        }
