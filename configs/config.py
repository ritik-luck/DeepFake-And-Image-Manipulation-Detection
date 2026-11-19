"""
Configuration module for Latent Score Divergence (LSD) Deepfake Research Suite.
Implements parameter definitions mandated by the LSD Research Roadmap:
- Noise perturbation strengths sigma
- Score model parameterization and conversions
- Dataset splits, degradation levels, and evaluation metrics
"""

from dataclasses import dataclass, field
from typing import List, Tuple, Optional


@dataclass
class ModelConfig:
    """Diffusion Backbone and Encoder Configuration."""
    # Pretrained model identifier (HuggingFace Hub or local directory)
    pretrained_model_id: str = "runwayml/stable-diffusion-v1-5"
    vae_subfolder: str = "vae"
    unet_subfolder: str = "unet"
    
    # Latent dimension specifics for Stable Diffusion VAE
    latent_channels: int = 4
    vae_scale_factor: float = 0.18215  # VAE latent standard deviation scaling
    
    # Input image resolution expected by model (H, W)
    image_size: Tuple[int, int] = (512, 512)
    
    # Precision: float32, float16, or bfloat16
    dtype: str = "float32"
    
    # Standalone lightweight fallback model if running locally without downloading 4GB SD weights
    use_lightweight_fallback: bool = False


@dataclass
class LSDAlgorithmConfig:
    """Mathematical Hyperparameters for LSD and Score Update."""
    # Perturbation noise level sigma in: z_sigma = z_0 + sigma * epsilon
    default_sigma: float = 0.10
    
    # Ablation noise levels for Phase 6 experiments
    ablation_sigmas: List[float] = field(default_factory=lambda: [0.02, 0.05, 0.10, 0.15, 0.20, 0.25])
    
    # Multi-Scale Noise Ensembling (Roadmap Phase 2 Enhancement)
    use_multiscale: bool = True
    multiscale_sigmas: List[float] = field(default_factory=lambda: [0.05, 0.10, 0.20])
    multiscale_weights: List[float] = field(default_factory=lambda: [0.25, 0.50, 0.25])
    
    # Boundary-Aware & Facial Region Spatial Prior Masking
    use_spatial_masking: bool = True
    spatial_focus: str = "face_prior"  # "none", "face_prior", "boundary_gradient"
    boundary_weight: float = 0.50
    
    # Directional + Energy Composite Divergence (Angular Cosine + Relative L2 Energy)
    use_composite_divergence: bool = True
    composite_energy_weight: float = 0.45  # Tuned for optimal balance between angular and energy divergence
    
    # High-Frequency Differential Spectral Perturbation (Optimized against ADRD / artifacts)
    use_hf_perturbation: bool = True
    hf_noise_alpha: float = 0.35  # Blending weight between isotropic Gaussian noise and 2D spatial gradient noise
    
    # Number of Monte Carlo perturbation samples per image
    num_noise_samples: int = 1
    
    # Numerical stability epsilon for denominator in cosine divergence
    epsilon_stab: float = 1e-8
    
    # Inversion/denoising rule:
    # "tweedie_score": z_hat = z_sigma + sigma^2 * score = z_sigma - sigma * epsilon_theta
    # "raw_score": direct z_sigma + sigma^2 * s_theta
    score_update_mode: str = "tweedie_score"
    
    # Random seed for perturbation reproducibility
    seed: int = 42


@dataclass
class DegradationConfig:
    """Degradation levels for Phase 4 Robustness Testing."""
    jpeg_qualities: List[int] = field(default_factory=lambda: [95, 75, 50, 30])
    blur_kernel_sizes: List[int] = field(default_factory=lambda: [3, 5, 7])
    resize_factors: List[float] = field(default_factory=lambda: [0.75, 0.50])


@dataclass
class DatasetConfig:
    """Dataset paths and protocols for the research papers."""
    # Supported datasets from papers: 'faceforensics', 'celeb_df', 'mastering_deepfake', 'celeba_hq'
    dataset_name: str = "faceforensics"
    
    # Base directory where datasets are extracted
    data_root: str = "./data"
    
    # Validation split ratio (used strictly for threshold calibration, never test set)
    val_split: float = 0.20
    test_split: float = 0.40
    
    # Batch size for evaluation
    batch_size: int = 4
    num_workers: int = 0


@dataclass
class ExperimentConfig:
    """Master Experiment Configuration."""
    model: ModelConfig = field(default_factory=ModelConfig)
    lsd: LSDAlgorithmConfig = field(default_factory=LSDAlgorithmConfig)
    degradation: DegradationConfig = field(default_factory=DegradationConfig)
    dataset: DatasetConfig = field(default_factory=DatasetConfig)
    
    # Output directories
    output_dir: str = "./outputs"
    checkpoint_dir: str = "./outputs/checkpoints"
    visualization_dir: str = "./outputs/heatmaps"
    metrics_dir: str = "./outputs/metrics"
    logs_dir: str = "./outputs/logs"
