"""
Standard Classifier Baseline for Real vs AI-Generated Images.
Implements Phase 3 Step 2 of the research roadmap:
"Implement a simple real-versus-generated classifier baseline."
Uses standard deep CNN / ConvNeXt feature extraction to establish passive classification benchmark.
"""

import torch
import torch.nn as nn
from typing import Optional


class StandardDeepfakeClassifier(nn.Module):
    """
    Supervised image-level binary classifier baseline.
    Uses pretrained CNN backbone (ResNet/ConvNeXt style) with linear classification head.
    """
    def __init__(self, backbone: str = "resnet18", pretrained: bool = True, num_classes: int = 1):
        super().__init__()
        self.backbone_name = backbone
        self.feature_extractor = None
        
        try:
            import torchvision.models as models
            if backbone == "resnet18":
                base = models.resnet18(weights=models.ResNet18_Weights.DEFAULT if pretrained else None)
                self.feature_extractor = nn.Sequential(*list(base.children())[:-1])
                in_dim = base.fc.in_features
            elif backbone == "resnet50":
                base = models.resnet50(weights=models.ResNet50_Weights.DEFAULT if pretrained else None)
                self.feature_extractor = nn.Sequential(*list(base.children())[:-1])
                in_dim = base.fc.in_features
            else:
                raise ValueError(f"Unknown backbone: {backbone}")
        except Exception:
            # Fallback lightweight CNN if torchvision weights are unavailable offline
            self.feature_extractor = nn.Sequential(
                nn.Conv2d(3, 32, kernel_size=3, stride=2, padding=1),
                nn.BatchNorm2d(32),
                nn.SiLU(),
                nn.Conv2d(32, 64, kernel_size=3, stride=2, padding=1),
                nn.BatchNorm2d(64),
                nn.SiLU(),
                nn.Conv2d(64, 128, kernel_size=3, stride=2, padding=1),
                nn.BatchNorm2d(128),
                nn.SiLU(),
                nn.AdaptiveAvgPool2d((1, 1))
            )
            in_dim = 128
            
        self.head = nn.Sequential(
            nn.Flatten(),
            nn.Dropout(0.3),
            nn.Linear(in_dim, num_classes)
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """Outputs raw logits for binary classification (real=0, fake=1)."""
        feats = self.feature_extractor(x)
        logits = self.head(feats)
        return logits

    def predict_probability(self, x: torch.Tensor) -> torch.Tensor:
        """Outputs sigmoid probability P(fake | image)."""
        logits = self.forward(x)
        return torch.sigmoid(logits)
