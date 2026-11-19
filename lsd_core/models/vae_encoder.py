"""
Latent VAE Encoder & Decoder module.
Implements the mapping z_0 = E(I) and reconstruction I_hat = D(z_0)
Supports standard pretrained Stable Diffusion AutoencoderKL with VAE scaling factor (0.18215),
as well as a self-contained lightweight Conv-VAE for fast offline local testing.
"""

import torch
import torch.nn as nn
from typing import Optional, Tuple
from ..utils.logger import check_tensor_health


class LightweightAutoencoder(nn.Module):
    """
    Self-contained, fast 8x spatial downsampling autoencoder.
    Used for local testing, CI/CD, or environments without internet access to HuggingFace.
    Downsamples (B, 3, H, W) -> (B, 4, H/8, W/8).
    """
    def __init__(self, in_channels: int = 3, latent_channels: int = 4):
        super().__init__()
        # Encoder: 3 downsampling stages (factor of 8)
        self.encoder = nn.Sequential(
            nn.Conv2d(in_channels, 32, kernel_size=3, stride=2, padding=1),  # /2
            nn.BatchNorm2d(32),
            nn.SiLU(),
            nn.Conv2d(32, 64, kernel_size=3, stride=2, padding=1),  # /4
            nn.BatchNorm2d(64),
            nn.SiLU(),
            nn.Conv2d(64, latent_channels, kernel_size=3, stride=2, padding=1),  # /8
        )
        
        # Decoder: 3 upsampling stages (factor of 8)
        self.decoder = nn.Sequential(
            nn.ConvTranspose2d(latent_channels, 64, kernel_size=4, stride=2, padding=1),  # *2
            nn.BatchNorm2d(64),
            nn.SiLU(),
            nn.ConvTranspose2d(64, 32, kernel_size=4, stride=2, padding=1),  # *4
            nn.BatchNorm2d(32),
            nn.SiLU(),
            nn.ConvTranspose2d(32, in_channels, kernel_size=4, stride=2, padding=1),  # *8
            nn.Tanh()
        )

    def encode(self, x: torch.Tensor) -> torch.Tensor:
        return self.encoder(x)

    def decode(self, z: torch.Tensor) -> torch.Tensor:
        return self.decoder(z)


class LatentVAE(nn.Module):
    """
    Unified Latent VAE Wrapper.
    Handles device placement, scaling factor, and encoding/decoding.
    """
    def __init__(
        self,
        pretrained_model_id: str = "runwayml/stable-diffusion-v1-5",
        subfolder: str = "vae",
        scale_factor: float = 0.18215,
        use_fallback: bool = False,
        device: torch.device = torch.device("cpu"),
        dtype: torch.dtype = torch.float32
    ):
        super().__init__()
        self.scale_factor = scale_factor
        self.device = device
        self.dtype = dtype
        self.use_fallback = use_fallback
        self.model = None

        if not use_fallback:
            try:
                from diffusers import AutoencoderKL
                self.model = AutoencoderKL.from_pretrained(
                    pretrained_model_id,
                    subfolder=subfolder,
                    torch_dtype=dtype,
                    local_files_only=False
                )
                self.model.eval().to(device)
            except Exception as e:
                # Graceful fallback to lightweight autoencoder if offline / weights unavailable
                print(f"[LatentVAE] Notice: Pretrained AutoencoderKL could not be loaded ({e}). "
                      f"Activating deterministic LightweightAutoencoder fallback for local execution.")
                self.use_fallback = True

        if self.use_fallback or self.model is None:
            self.model = LightweightAutoencoder(in_channels=3, latent_channels=4)
            self.model.eval().to(device=device, dtype=dtype)

    @torch.no_grad()
    def encode_image(self, image: torch.Tensor) -> torch.Tensor:
        """
        Encodes normalized image tensor [B, 3, H, W] in [-1, 1] into latent space z_0.
        Returns scaled latent tensor [B, 4, H/8, W/8].
        """
        image = image.to(device=self.device, dtype=self.dtype)
        
        if self.use_fallback:
            z_raw = self.model.encode(image)
            z_0 = z_raw * self.scale_factor
        else:
            posterior = self.model.encode(image).latent_dist
            z_0 = posterior.sample() * self.scale_factor
            
        check_tensor_health(z_0, "latent_z0")
        return z_0

    @torch.no_grad()
    def decode_latent(self, z: torch.Tensor) -> torch.Tensor:
        """
        Decodes latent tensor z [B, 4, H/8, W/8] back into RGB image [B, 3, H, W] in [-1, 1].
        Used for pixel reconstruction error (DIRE baseline).
        """
        z = z.to(device=self.device, dtype=self.dtype)
        z_unscaled = z / self.scale_factor
        
        if self.use_fallback:
            reconstructed = self.model.decode(z_unscaled)
        else:
            reconstructed = self.model.decode(z_unscaled).sample
            
        check_tensor_health(reconstructed, "reconstructed_image")
        return reconstructed
