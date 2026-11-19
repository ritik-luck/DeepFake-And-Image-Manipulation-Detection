"""
Diffusion Score Network Wrapper.
Implements the mathematical conversion between diffusion noise prediction epsilon_theta(z, sigma)
and the score function s_theta(z, sigma) = grad_z log p(z).

Roadmap Page 5 requirement:
"Define the exact score convention: whether the network predicts score, noise, velocity, or another
parameterization. Convert its output appropriately."
"""

import math
import torch
import torch.nn as nn
from typing import Optional, Tuple, Any, Dict
from ..utils.logger import check_tensor_health


class LightweightScoreUNet(nn.Module):
    """
    Self-contained lightweight U-Net for offline local debugging.
    Preserves spatial dimensions of latent maps [B, 4, h, w].
    """
    def __init__(self, in_channels: int = 4):
        super().__init__()
        self.time_embed = nn.Sequential(
            nn.Linear(1, 32),
            nn.SiLU(),
            nn.Linear(32, 32)
        )
        self.conv1 = nn.Conv2d(in_channels, 32, kernel_size=3, padding=1)
        self.act1 = nn.SiLU()
        self.conv2 = nn.Conv2d(32, 64, kernel_size=3, padding=1)
        self.act2 = nn.SiLU()
        self.conv3 = nn.Conv2d(64, 32, kernel_size=3, padding=1)
        self.act3 = nn.SiLU()
        self.out_conv = nn.Conv2d(32, in_channels, kernel_size=3, padding=1)

    def forward(self, z: torch.Tensor, timestep: torch.Tensor) -> torch.Tensor:
        # Time conditioning
        t_emb = self.time_embed(timestep.view(-1, 1).float())  # [B, 32]
        t_spatial = t_emb.view(-1, 32, 1, 1).expand(-1, 32, z.shape[2], z.shape[3])
        
        h = self.act1(self.conv1(z)) + t_spatial
        h = self.act2(self.conv2(h))
        h = self.act3(self.conv3(h))
        return self.out_conv(h)


class DiffusionScoreModel(nn.Module):
    """
    Unified Score Network Interface.
    Wraps pretrained UNet2DConditionModel from Diffusers or local fallback.
    Converts between predicted noise epsilon_theta and score function s_theta.
    """
    def __init__(
        self,
        pretrained_model_id: str = "runwayml/stable-diffusion-v1-5",
        subfolder: str = "unet",
        use_fallback: bool = False,
        device: torch.device = torch.device("cpu"),
        dtype: torch.dtype = torch.float32
    ):
        super().__init__()
        self.device = device
        self.dtype = dtype
        self.use_fallback = use_fallback
        self.unet = None

        if not use_fallback:
            try:
                from diffusers import UNet2DConditionModel
                self.unet = UNet2DConditionModel.from_pretrained(
                    pretrained_model_id,
                    subfolder=subfolder,
                    torch_dtype=dtype,
                    local_files_only=False
                )
                self.unet.eval().to(device)
            except Exception as e:
                print(f"[ScoreModel] Notice: Pretrained UNet could not be loaded ({e}). "
                      f"Activating deterministic LightweightScoreUNet fallback for local execution.")
                self.use_fallback = True

        if self.use_fallback or self.unet is None:
            self.unet = LightweightScoreUNet(in_channels=4)
            self.unet.eval().to(device=device, dtype=dtype)
            
        self.has_lora = False
        self.lora_adapters = {}

    def inject_facial_lora(self, rank: int = 8, alpha: float = 16.0) -> int:
        """Injects facial LoRA adapters into UNet attention projection layers."""
        from .lora_adapter import inject_lora_into_unet
        self.lora_adapters = inject_lora_into_unet(self.unet, rank=rank, alpha=alpha)
        self.has_lora = len(self.lora_adapters) > 0
        return len(self.lora_adapters)

    def set_lora_active(self, active: bool = True) -> None:
        """Activates or deactivates LoRA adapter weights."""
        from .lora_adapter import set_lora_active
        if self.has_lora:
            set_lora_active(self.unet, active=active)

    def load_facial_lora_weights(self, weights_path_or_dict: Any) -> int:
        """Loads specialized facial LoRA weights into UNet."""
        if not self.has_lora:
            self.inject_facial_lora()
        from .lora_adapter import load_lora_weights
        return load_lora_weights(self.unet, weights_path_or_dict)

    def sigma_to_timestep(self, sigma: float) -> torch.Tensor:
        """
        Maps continuous perturbation noise sigma to discrete diffusion timestep t in [0, 999].
        Empirical linear/cosine mapping for Stable Diffusion DDPM scheduler.
        """
        # Typically t = int(clamp(sigma * 1000, 1, 999))
        t_val = int(max(1, min(999, round(sigma * 1000))))
        return torch.tensor([t_val], device=self.device)

    @torch.no_grad()
    def predict_score(self, z_sigma: torch.Tensor, sigma: float) -> Tuple[torch.Tensor, torch.Tensor]:
        """
        Calculates:
        1. Score function: s_theta(z_sigma, sigma) = grad_z log p(z)
        2. Denoised update z_hat using Tweedie's formula:
           z_hat = z_sigma + sigma^2 * s_theta(z_sigma, sigma)
           
        Math derivation:
        Standard diffusion UNet predicts noise epsilon_theta.
        By definition: s_theta(z_sigma, sigma) = - epsilon_theta / sigma
        Substituting into the update:
           z_hat = z_sigma + sigma^2 * (- epsilon_theta / sigma) = z_sigma - sigma * epsilon_theta
        """
        z_sigma = z_sigma.to(device=self.device, dtype=self.dtype)
        batch_size = z_sigma.shape[0]
        t = self.sigma_to_timestep(sigma).expand(batch_size)

        if self.use_fallback:
            noise_pred = self.unet(z_sigma, t)
        else:
            # Stable Diffusion UNet expects encoder_hidden_states.
            # Passing unconditioned null prompt embeddings [B, 77, 768]
            dummy_context = torch.zeros(
                (batch_size, 77, self.unet.config.cross_attention_dim),
                device=self.device,
                dtype=self.dtype
            )
            model_output = self.unet(z_sigma, t, encoder_hidden_states=dummy_context)
            noise_pred = model_output.sample

        check_tensor_health(noise_pred, "unet_noise_pred")

        # Convert noise prediction to mathematical score: s_theta = - epsilon / sigma
        score = - (noise_pred / (sigma + 1e-8))
        check_tensor_health(score, "score_vector")

        # Tweedie's one-step posterior mean update
        z_hat = z_sigma + (sigma ** 2) * score
        check_tensor_health(z_hat, "latent_z_hat")

        return score, z_hat
