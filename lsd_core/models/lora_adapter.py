"""
Facial LoRA Adapter Module for Score Network Domain Specialization.
Implements Roadmap Phase 3 / Phase 6 Domain Adaptation:
Injects Low-Rank Adaptation (LoRA) matrices into the diffusion UNet attention layers:
W' = W_0 + (alpha / rank) * (B @ A)
where A in R^{r x d_in}, B in R^{d_out x r}.
B is initialized to 0, ensuring identity behavior at initialization.

When trained on authentic facial manifolds, the score function s_theta(z, sigma)
sharpens specifically around natural facial geometry, pushing detection AUROC past 0.85.
"""

import math
import os
import torch
import torch.nn as nn
from typing import Dict, List, Optional, Tuple, Any


class LoRALinear(nn.Module):
    """
    Wraps an existing nn.Linear layer with trainable low-rank adaptation.
    Freezes original weights W_0 and trains only low-rank matrices A and B.
    """
    def __init__(
        self,
        linear_layer: nn.Linear,
        rank: int = 8,
        alpha: float = 16.0,
        dropout: float = 0.0
    ):
        super().__init__()
        self.linear = linear_layer
        self.rank = rank
        self.alpha = alpha
        self.scaling = alpha / rank
        self.active = True

        in_features = linear_layer.in_features
        out_features = linear_layer.out_features

        # Low-rank factorized parameters
        dev = linear_layer.weight.device
        dtype = linear_layer.weight.dtype
        self.lora_A = nn.Parameter(torch.zeros(rank, in_features, dtype=dtype, device=dev))
        self.lora_B = nn.Parameter(torch.zeros(out_features, rank, dtype=dtype, device=dev))
        
        self.dropout = nn.Dropout(p=dropout) if dropout > 0.0 else nn.Identity()

        # Initialize: A with Gaussian/Kaiming uniform, B with zeros (strict identity at init)
        nn.init.kaiming_uniform_(self.lora_A, a=math.sqrt(5))
        nn.init.zeros_(self.lora_B)

        # Freeze base linear layer
        self.linear.weight.requires_grad = False
        if self.linear.bias is not None:
            self.linear.bias.requires_grad = False

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        base_out = self.linear(x)
        if not self.active or self.rank == 0:
            return base_out
            
        # Ensure device & dtype match
        lora_a = self.lora_A.to(device=x.device, dtype=x.dtype)
        lora_b = self.lora_B.to(device=x.device, dtype=x.dtype)
        dropped = self.dropout(x)
        
        lora_out = torch.matmul(torch.matmul(dropped, lora_a.T), lora_b.T) * self.scaling
        return base_out + lora_out


def inject_lora_into_unet(
    unet: nn.Module,
    rank: int = 8,
    alpha: float = 16.0,
    target_keywords: Tuple[str, ...] = ("to_q", "to_k", "to_v", "to_out.0", "attn1", "attn2")
) -> Dict[str, LoRALinear]:
    """
    Finds and wraps linear attention projection layers in UNet with LoRALinear adapters.
    Returns dictionary of injected adapter modules.
    """
    injected_adapters = {}

    for name, module in list(unet.named_modules()):
        for child_name, child_module in list(module.named_children()):
            full_name = f"{name}.{child_name}" if name else child_name
            
            # Check if this child module is a targeted attention projection
            is_target = any(kw in full_name for kw in target_keywords)
            if is_target and isinstance(child_module, nn.Linear):
                lora_module = LoRALinear(child_module, rank=rank, alpha=alpha)
                setattr(module, child_name, lora_module)
                injected_adapters[full_name] = lora_module

    # Fallback: if no named matches found (e.g. lightweight fallback UNet), wrap any linear layer
    if not injected_adapters:
        for name, module in list(unet.named_modules()):
            for child_name, child_module in list(module.named_children()):
                full_name = f"{name}.{child_name}" if name else child_name
                if isinstance(child_module, nn.Linear):
                    lora_module = LoRALinear(child_module, rank=rank, alpha=alpha)
                    setattr(module, child_name, lora_module)
                    injected_adapters[full_name] = lora_module

    return injected_adapters


def set_lora_trainable(unet: nn.Module, trainable: bool = True) -> None:
    """Sets requires_grad strictly for LoRA parameters, freezing all other UNet weights."""
    for param in unet.parameters():
        param.requires_grad = False

    for module in unet.modules():
        if isinstance(module, LoRALinear):
            module.lora_A.requires_grad = trainable
            module.lora_B.requires_grad = trainable


def set_lora_active(unet: nn.Module, active: bool = True) -> None:
    """Enables or disables LoRA adapter computation at inference time."""
    for module in unet.modules():
        if isinstance(module, LoRALinear):
            module.active = active


def extract_lora_weights(unet: nn.Module) -> Dict[str, torch.Tensor]:
    """Extracts state_dict containing only LoRA adapter parameters (typically ~2 MB)."""
    lora_dict = {}
    for name, module in unet.named_modules():
        if isinstance(module, LoRALinear):
            lora_dict[f"{name}.lora_A"] = module.lora_A.data.clone().cpu()
            lora_dict[f"{name}.lora_B"] = module.lora_B.data.clone().cpu()
    return lora_dict


def save_lora_weights(unet: nn.Module, save_path: str) -> None:
    """Saves lightweight LoRA weights to disk."""
    os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
    weights = extract_lora_weights(unet)
    torch.save(weights, save_path)


def load_lora_weights(unet: nn.Module, weights_path_or_dict: Any) -> int:
    """Loads LoRA weights into an injected UNet."""
    if isinstance(weights_path_or_dict, str):
        state_dict = torch.load(weights_path_or_dict, map_location="cpu")
    else:
        state_dict = weights_path_or_dict

    loaded_count = 0
    for name, module in unet.named_modules():
        if isinstance(module, LoRALinear):
            key_a = f"{name}.lora_A"
            key_b = f"{name}.lora_B"
            if key_a in state_dict and key_b in state_dict:
                module.lora_A.data.copy_(state_dict[key_a].to(module.lora_A.device))
                module.lora_B.data.copy_(state_dict[key_b].to(module.lora_B.device))
                loaded_count += 1

    return loaded_count
