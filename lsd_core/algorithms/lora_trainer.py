"""
Facial LoRA Fine-Tuning Pipeline for Latent Score Divergence.
Implements Roadmap Phase 3 & Phase 6 Domain Adaptation:
Trains lightweight LoRA adapters on authentic face manifolds to sharpen the diffusion score
function around natural facial geometry, widening the divergence gap against synthetic deepfakes
and pushing detection AUROC past 0.85.
"""

import os
import time
import torch
import torch.nn as nn
from typing import Dict, Any, Optional
from ..models.lora_adapter import (
    inject_lora_into_unet,
    set_lora_trainable,
    save_lora_weights,
    extract_lora_weights
)


def train_facial_lora_adapter(
    pipeline: Dict[str, Any],
    dataloader: Any,
    num_epochs: int = 3,
    lr: float = 1e-4,
    rank: int = 8,
    alpha: float = 16.0,
    save_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Fine-tunes lightweight LoRA weights on pristine face images.
    Optimizes joint Denoising Score Matching + Manifold Score Inconsistency minimization.
    """
    logger = pipeline.get("logger")
    device = pipeline["device"]
    vae = pipeline["vae"]
    score_model = pipeline["score_model"]
    unet = score_model.unet
    cfg = pipeline["cfg"]

    out_path = save_path or os.path.join(cfg.output_dir if hasattr(cfg, "output_dir") else "outputs", "models", "facial_lora.pt")
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)

    # 1. Inject LoRA adapters if not already present
    if not getattr(score_model, "has_lora", False):
        score_model.inject_facial_lora(rank=rank, alpha=alpha)

    # 2. Freeze base UNet, unfreeze strictly LoRA parameters
    set_lora_trainable(unet, trainable=True)
    unet.train()

    lora_params = [p for p in unet.parameters() if p.requires_grad]
    optimizer = torch.optim.AdamW(lora_params, lr=lr, weight_decay=1e-2)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=max(1, num_epochs * len(dataloader)))

    if logger:
        logger.info(f"=== Starting Facial LoRA Domain Fine-Tuning (Rank={rank}, Params={sum(p.numel() for p in lora_params)}) ===")

    history = []
    start_time = time.time()

    for epoch in range(num_epochs):
        epoch_loss = 0.0
        step_count = 0

        for batch_idx, batch in enumerate(dataloader):
            # Only train on authentic pristine faces (label == 0)
            images = batch["image"].to(device)
            labels = batch["label"].to(device)
            
            real_mask = (labels == 0)
            if not real_mask.any():
                continue
            
            real_images = images[real_mask]
            batch_size = real_images.shape[0]

            with torch.no_grad():
                z_0 = vae.encode_image(real_images)

            # Sample calibrated perturbation noise level sigma
            sig = float(torch.empty(1).uniform_(0.05, 0.20).item())
            t = score_model.sigma_to_timestep(sig).expand(batch_size)
            noise = torch.randn_like(z_0)
            z_sigma = z_0 + sig * noise

            # Forward pass through LoRA-injected UNet
            if score_model.use_fallback:
                noise_pred = unet(z_sigma, t)
            else:
                dummy_context = torch.zeros(
                    (batch_size, 77, unet.config.cross_attention_dim),
                    device=device,
                    dtype=z_0.dtype
                )
                noise_pred = unet(z_sigma, t, encoder_hidden_states=dummy_context).sample

            # 1. Standard Denoising Score Matching Loss
            loss_noise = nn.functional.mse_loss(noise_pred, noise)

            # 2. Closed-form Tweedie Denoised Reconstruction
            z_hat = z_sigma - sig * noise_pred

            # 3. Directional Cosine Alignment Loss (Pulls real faces to zero divergence)
            dot = torch.sum(z_0 * z_hat, dim=1)
            norm_z0 = torch.norm(z_0, p=2, dim=1)
            norm_zhat = torch.norm(z_hat, p=2, dim=1)
            cos_sim = dot / (norm_z0 * norm_zhat + 1e-6)
            loss_divergence = torch.mean(1.0 - cos_sim)

            total_loss = loss_noise + 0.5 * loss_divergence

            optimizer.zero_grad()
            total_loss.backward()
            torch.nn.utils.clip_grad_norm_(lora_params, max_norm=1.0)
            optimizer.step()
            scheduler.step()

            epoch_loss += total_loss.item()
            step_count += 1

        avg_loss = epoch_loss / max(1, step_count)
        history.append({"epoch": epoch + 1, "loss": avg_loss})
        if logger:
            logger.info(f"Epoch [{epoch+1}/{num_epochs}] - Mean Loss: {avg_loss:.4f}")

    # Set back to eval mode
    unet.eval()
    save_lora_weights(unet, out_path)
    total_time = time.time() - start_time

    if logger:
        logger.info(f"Facial LoRA fine-tuning complete in {total_time:.1f}s. Saved weights to: {out_path}")

    return {
        "status": "success",
        "output_path": out_path,
        "epochs": num_epochs,
        "runtime_s": total_time,
        "history": history
    }

