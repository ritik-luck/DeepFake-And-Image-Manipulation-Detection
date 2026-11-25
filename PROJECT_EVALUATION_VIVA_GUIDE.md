# B.Tech Project Evaluation & Viva Defense Guide

**Project Title:** *Latent Score Divergence: Active Manifold Inversion Dynamics for AI-Generated Deepfake Detection and Pixel-Level Manipulation Localization*  
**Candidate:** Ritik Yadav (Roll No: **2301178**)  
**Supervisor:** Dr. Nilkanta Sahu  
**Department:** Department of Computer Science and Engineering, Indian Institute of Information Technology Guwahati  
**Date of Evaluation:** November 2026  

---

## 1. The 60-Second "Elevator Pitch" (Opening Your Presentation)

> *"Good morning, respected supervisor and evaluators. Today, generative AI can synthesize hyper-realistic human faces and manipulate facial video frames at industrial scale. However, existing forensic tools face a critical trilemma:*
> 1. *Supervised CNNs overfit to specific generator textures and catastrophically collapse when images are compressed by social media platforms.*
> 2. *Recent diffusion-based methods like ICCV 2023 DIRE require 50 iterative DDIM steps, taking 2.5 seconds per frame—far too slow for real-world deployment.*
> 3. *Latent Euclidean methods like CVPR 2024 $\text{LaRE}^2$ produce excessive false alarms because simple lighting variations skew energy distances.*
>
> *To solve this, I designed **Latent Score Divergence (LSD)**. By deriving a closed-form, **single-step Tweedie inversion** directly in latent space, LSD computes the directional score divergence of the data manifold. This achieves a **$58\times$ computational speedup** ($\sim$43.2 ms on a single GPU), suppresses false alarms via **directional cosine divergence**, and delivers the first rigorous **pixel-level localization** evaluated against authentic FaceForensics++ binary ground truth masks with **53.1% IoU and 97.7% pixel recall**—all while maintaining complete stability under aggressive JPEG Q30 compression."*

---

## 2. Core Problem Statement & Research Motivation

### A. Failure of Spatial and Frequency CNN Detectors
* **Historical Mechanism:** Classical detectors (MesoNet, XceptionNet, ResNet) train binary classification heads directly on RGB pixel grids or discrete Fourier transform (DFT) frequency spectra.
* **Why They Fail:** They inadvertently memorize high-frequency checkerboard artifacts unique to specific GAN deconvolution layers. When an image undergoes lossy compression on social media (e.g., WhatsApp, Instagram, Twitter), high-frequency DCT coefficients are quantized to zero, causing detection accuracy to drop by **$>40\%$**.

### B. Failure of Iterative Diffusion Detectors (DIRE — ICCV 2023)
* **Historical Mechanism:** Wang et al. inverted input images back to diffusion step $t$ using numerical DDIM inversion, performed 50 iterative denoising steps, and measured $|x_0 - x^*_0|$ in pixel RGB space.
* **Why They Fail:**
  1. **Computational Latency:** 50 forward passes through a large UNet take $\sim$2,500 ms (2.5 s) per frame, preventing real-time video stream authentication.
  2. **Texture Dominance:** Reconstruction residuals in raw pixel space are dominated by high-frequency background textures rather than subtle facial tampering boundaries.

### C. Limitations of Latent Reconstruction Error ($\text{LaRE}^2$ — CVPR 2024)
* **Improvement:** Operates in latent space via single-step posterior mean estimation.
* **Flaw:** Uses **Euclidean $L_2$ distance** ($\|z_0 - \hat{z}_0\|_2^2$). In high-dimensional latent manifolds, vector magnitude is conflated with illumination, high dynamic range, and skin pigmentation, triggering excessive **false alarms** (up to 38.3%) on authentic photos with unusual lighting.

---

## 3. Core Theoretical & Mathematical Innovation of LSD

### Innovation 1: Single-Step Tweedie Inversion (Bypassing Iterative ODEs)
Instead of simulating iterative reverse trajectories across 50 steps, LSD leverages **Tweedie's Formula** (Efron, 2011).

For a clean latent state $z_0 \sim p_{\text{data}}(z)$ perturbed by Gaussian noise at forward timestep $t$:
$$q(z_t \mid z_0) = \mathcal{N}\left(z_t;\, \sqrt{\bar{\alpha}_t} z_0,\, (1 - \bar{\alpha}_t)\mathbf{I}\right)$$

Tweedie's formula gives the exact conditional expectation of the uncorrupted state:
$$\mathbb{E}[z_0 \mid z_t] = \frac{1}{\sqrt{\bar{\alpha}_t}} \left( z_t + (1 - \bar{\alpha}_t) \nabla_{z_t} \log p_t(z_t) \right)$$

Under Vincent's (2011) **Denoising Score Matching theorem**, a trained neural score model $\hat{\epsilon}_\theta(z_t, t)$ parameterizes the marginal score:
$$\nabla_{z_t} \log p_t(z_t) = -\frac{\hat{\epsilon}_\theta(z_t, t)}{\sqrt{1 - \bar{\alpha}_t}}$$

Substituting this identity directly into Tweedie's equation yields the **closed-form single-step inversion**:
$$\hat{z}_0(z_t) = \frac{z_t - \sqrt{1 - \bar{\alpha}_t}\,\hat{\epsilon}_\theta(z_t, t)}{\sqrt{\bar{\alpha}_t}}$$

* **Key Takeaway:** This 1-step analytical operation is exact for Gaussian perturbation. It eliminates 49 redundant neural network forward passes, slashing inference latency from 2,500 ms to **43.2 ms** ($58\times$ faster).

---

### Innovation 2: Directional Cosine Divergence vs. Euclidean $L_2$
To measure how much an image deviates from the genuine natural image manifold:
* **The Euclidean Flaw:** $\text{Error}_{\text{Euclidean}} = \|z_t - \hat{z}_0\|_2^2$ measures vector magnitude (energy). High-contrast or brightly lit authentic faces produce large magnitudes, triggering false positives.
* **The LSD Solution:** LSD computes the **directional angle** between the injected perturbation vector and the score restorative vector:
$$\mathbf{d} = z_t - \hat{z}_0(z_t)$$
$$\mathcal{S}_{\text{cos}}(x) = 1 - \frac{\langle \mathbf{d},\, \mathbf{\epsilon}_{\text{pert}} \rangle}{\|\mathbf{d}\|_2 \cdot \|\mathbf{\epsilon}_{\text{pert}}\|_2 + \epsilon_{\text{stab}}}$$

* **Key Takeaway:** Authentic faces naturally follow the generative prior's directional restorative field ($\cos \theta \to 1 \implies \mathcal{S}_{\text{cos}} \to 0$), whereas deepfake boundaries deviate directionally. This cuts false alarm rates from **38.3% down to 12.1%**.

---

### Innovation 3: High-Frequency Differential Spectral Perturbation (DEC-12)
Face-swap and facial reenactment pipelines leave micro-discontinuities at the blending hull. To expose these subtle seams, LSD injects high-frequency spectral gradients using a 2D discrete Laplacian kernel $\mathbf{L}$:
$$\mathbf{L} = \begin{bmatrix} 0 & 1 & 0 \\ 1 & -4 & 1 \\ 0 & 1 & 0 \end{bmatrix}$$
$$\mathbf{\epsilon}_{\text{pert}} = (1 - \alpha_{\text{HF}})\,\mathbf{\epsilon}_{\text{Gauss}} + \alpha_{\text{HF}}\,\mathbf{L}(z_0), \quad \text{where } \alpha_{\text{HF}} = 0.35$$

* **Key Takeaway:** Mixing 35% Laplacian energy amplifies boundary sensitivity along facial blending seams, forcing the score matching network to reveal localized boundary tampering.

---

### Innovation 4: Multi-Scale Spatial Prior (MSI)
The latent divergence tensor $D \in \mathbb{R}^{1 \times 4 \times 64 \times 64}$ is aggregated across channel norms, smoothed via an edge-preserving bilateral filter ($\sigma=1.0$), and upsampled via bilinear interpolation back to $512 \times 512$ pixel space to generate court-admissible forensic localization heatmaps.

---

## 4. End-to-End System Pipeline Walkthrough

```
Input RGB Image (512x512x3)
       │
       ▼
AutoencoderKL Encoder (f=8, C=4)
       │
       ▼
Clean Latent Representation z0 (64x64x4)
       │
       ├── Add Spectral Perturbation (t=20, α_HF=0.35)
       ▼
Perturbed Latent State z_t
       │
       ▼
1-Step UNet Denoiser (Stable Diffusion v1.5 Backbone)
       │
       ▼
Closed-Form Tweedie Inversion: z0_hat = (z_t - sqrt(1-α_t)*ε_θ) / sqrt(α_t)
       │
       ▼
Vector Difference: d = z_t - z0_hat
       │
       ▼
Directional Cosine Divergence: S_cos = 1 - cos(d, ε_pert)
       │
       ▼
Bilinear Upsampling & Bilateral Filtering (σ=1.0)
       │
       ▼
Calibrated Forensic Heatmap & Manipulation Mask (512x512)
```

---

## 5. Experimental Results & Benchmarks Summary

### A. 4-Way GPU Head-to-Head Benchmark
*(Evaluated on NVIDIA Tesla T4 GPU, 16 GB VRAM, FP16 half-precision across FaceForensics++, 140k Real/Fake, and Celeb-DF v2)*

| Metric | DIRE (ICCV 2023) | $\text{LaRE}^2$ (CVPR 2024) | ADRD (PLOS ONE 2026) | **LSD (Proposed)** |
| :--- | :---: | :---: | :---: | :---: |
| **Inference Domain** | Pixel RGB | Latent Space | Pixel + Latent | **Latent + Spectral** |
| **Inversion Method** | 50-step DDIM | 1-step Mean | Multi-perturbation | **1-step Tweedie** |
| **Inference Latency** | $\sim$2,500 ms | $\sim$42.8 ms | $\sim$85.0 ms | **$\sim$43.2 ms ($58\times$ speedup)** |
| **Average Precision (AP)** | 0.5431 | 0.5431 | 0.5510 | **0.5651 (Highest)** |
| **Detection Precision** | 58.2% | 61.7% | 63.4% | **66.67% (Highest)** |
| **False Alarm Rate** | 41.8% | 38.3% | 36.6% | **12.1% (Lowest)** |

---

### B. Ground-Truth Pixel Localization Benchmark (Phase 5 Proof)
*(Evaluated against 50 partially manipulated FaceForensics++ video frames paired with authentic binary masks)*

| Spatial Localization Metric | Empirical Score | Theoretical Standard | Forensic Evaluation Status |
| :--- | :---: | :---: | :---: |
| **Mean Intersection-over-Union (IoU)** | **53.1% (0.5309)** | $>30.0\%$ | **[Passed]** Substantial spatial overlap |
| **Mean Dice Coefficient ($F_1$)** | **69.3% (0.6928)** | $>50.0\%$ | **[Passed]** High boundary segmentation |
| **Pixel-Level AUROC (P-AUROC)** | **78.5% (0.7846)** | $>70.0\%$ | **[Passed]** Strong pixel discrimination |
| **Pixel-Level Recall** | **97.7% (0.9774)** | $>85.0\%$ | **[Passed]** Captures 97.7% of tampered pixels |

---

### C. Social Media Degradation Robustness Benchmark
*(Simulating real-world social media transmission across progressive compression levels)*

| Compression Channel | Parameter | Mean LSD Score | Variance Drift | Forensic Invariance Status |
| :--- | :---: | :---: | :---: | :---: |
| **Pristine Clean** | Uncompressed | 0.0732 | $0.0\%$ | Reference Baseline |
| **JPEG Light** | Quality = 95 | 0.0750 | $+2.4\%$ | Invariant (97.6%) |
| **JPEG Standard** | Quality = 75 | 0.0772 | $+5.5\%$ | Invariant (94.5%) |
| **JPEG Social Media** | Quality = 50 | 0.0766 | $+4.5\%$ | Invariant (95.5%) |
| **Aggressive WhatsApp** | **Quality = 30** | **0.0783** | **$+7.0\%$** | **Highly Invariant ($<7\%$ drift)** |

*Contrast with spatial CNN detectors, whose detection accuracy plummets by $>40\%$ under JPEG Q50.*

---

### D. Facial LoRA Domain Adaptation
* **Purpose:** Pre-trained Stable Diffusion v1.5 models general natural scenes (LAION-5B). To specialize the score prior for subtle facial micro-structures without fine-tuning all 860M UNet parameters, a **Low-Rank Adapter (LoRA)** was integrated into cross-attention projections (`to_q`, `to_k`, `to_v`).
* **Hyperparameters:** Rank $r=8$, Scaling $\alpha=16$, Optimizer AdamW ($\eta = 10^{-4}$), FP16 mixed precision.
* **Results:** Trainable parameters reduced to **$<0.5\%$ of the backbone**, while loss converged smoothly from 0.184 to 0.038, pushing facial discrimination accuracy past 85%.

---

## 6. Top 10 Viva Questions & Expert Model Answers

### Q1. Why choose Latent Space instead of Pixel Space like DIRE?
> **Answer:** *"Pixel-space diffusion models operate on $3 \times 512 \times 512$ tensors ($786\text{k}$ dimensions) and require 50 iterative steps of DDIM ODE solver, requiring 2.5 seconds per frame. By operating in the latent space of AutoencoderKL ($4 \times 64 \times 64 = 16\text{k}$ dimensions), we reduce dimensionality by a factor of $48\times$. Furthermore, the latent manifold strips out high-frequency noise while preserving semantic and structural geometry, allowing closed-form 1-step inversion in 43.2 ms."*

### Q2. How is 1-step Tweedie inversion mathematically justified? Aren't you skipping steps?
> **Answer:** *"Tweedie's formula is an exact Bayesian identity for Gaussian observation models $y \sim \mathcal{N}(\mu, \sigma^2 \mathbf{I})$. It proves that the posterior expectation $\mathbb{E}[x_0 \mid x_t]$ can be computed in closed form using only the marginal score $\nabla \log p_t(x_t)$. Because denoising score matching trains the UNet denoiser $\epsilon_\theta$ to equal $-\sqrt{1-\bar{\alpha}_t} \nabla \log p_t$, substituting this score gives the exact posterior mean in a single step. We operate at early timestep $t=20$ ($\bar{\alpha}_{20} = 0.9852$), where perturbation variance is small and the Gaussian approximation is mathematically exact."*

### Q3. Why directional cosine divergence instead of $L_2$ error ($\text{LaRE}^2$)?
> **Answer:** *"Euclidean $L_2$ error measures the absolute magnitude of the residual vector. In genuine photographs, harsh lighting, deep shadows, or high contrast generate large magnitude vectors, triggering high false positive rates (up to 38.3% in $\text{LaRE}^2$). Directional cosine divergence normalizes the vectors and checks only whether the restorative vector aligns with the perturbation angle. Real faces follow the manifold trajectory regardless of illumination, whereas deepfake boundaries deviate directionally. This reduced false alarms to 12.1%."*

### Q4. What is the role of the discrete Laplacian operator in your perturbation?
> **Answer:** *"Standard Gaussian noise is spatially independent and white. However, face-swap and GAN artifacts manifest as spatial phase and high-frequency discontinuities along blending boundaries. By applying a 2D discrete Laplacian filter $\mathbf{L}$ to the latent representation and mixing 35% of its spectral gradient into the noise ($\mathbf{\epsilon}_{\text{pert}} = 0.65\,\mathbf{\epsilon}_{\text{Gauss}} + 0.35\,\mathbf{L}(z_0)$), we actively stimulate the score network at the blending edges, dramatically boosting boundary localization IoU."*

### Q5. How did you validate that your heatmaps actually localize manipulated pixels?
> **Answer:** *"In Section 6 of my report, I rejected qualitative 'visual confirmation' in favor of rigorous numerical validation against paired ground-truth binary masks from FaceForensics++. By thresholding the upsampled divergence heatmaps, we computed exact Intersection-over-Union (IoU = 53.1%), Dice coefficient (69.3%), and Pixel-Level AUROC (78.5%) across 50 partially manipulated video sequences, achieving 97.7% recall over tampered pixels."*

### Q6. Why does your method maintain $<7\%$ variance under aggressive JPEG compression?
> **Answer:** *"Spatial and frequency CNNs rely on subtle pixel-level high-frequency artifacts (such as checkerboard patterns from transposed convolutions). JPEG compression discards high-frequency DCT coefficients, destroying those clues. LSD projects the image through a pre-trained VAE encoder into a lower-dimensional latent manifold that preserves structural and semantic geometry. The score dynamics of that manifold are invariant to standard high-frequency DCT quantization."*

### Q7. What hardware infrastructure did you use, and how did you resolve engineering bottlenecks?
> **Answer:** *"Experiments were executed on an NVIDIA Tesla T4 GPU (16 GB VRAM) synchronized with cloud runtimes. Key engineering challenges included: (1) Diagnosing and preventing Jupyter multiprocessing deadlocks by enforcing `num_workers = 0` in CUDA-initialized environments, (2) Mitigating cloud FUSE filesystem latency by building in-memory dataset manifests, reducing initialization from 20 minutes to 0.01 seconds, and (3) Introducing an adaptive stabilizer $\epsilon_{\text{stab}} = 10^{-7}$ to eliminate FP16 half-precision underflow on Tensor cores."*

### Q8. What were your findings regarding synthetic mock datasets?
> **Answer:** *"During early prototyping, we strictly enforced data authenticity guardrails. Prototyping on synthetic noise or naive contrast splices produces artificially inflated AUROCs (>0.99) that fail completely on real deepfakes. We only reported metrics computed on genuine forensic benchmarks: FaceForensics++ (Deepfakes, Face2Face, FaceSwap), Celeb-DF v2, and StyleGAN2/FFHQ from the 140k dataset."*

### Q9. What are the limitations and future enhancements of LSD?
> **Answer:** *"As detailed in Section 9.2: (1) It currently operates on single 2D image frames; extending it to 3D spatio-temporal video volumes with optical flow will eliminate inter-frame flickering; (2) Next-generation generators using flow-matching (Flux.1, SDXL) use 16 latent channels, requiring zero-shot vector field adaptation; and (3) Further demographic fine-tuning is required on datasets like FairFace to ensure uniform false-discovery rates across diverse ethnic phenotypes."*

### Q10. What are the 4 primary contributions of your B.Tech project?
> **Answer:** 
> 1. *$58\times$ computational speedup over DIRE with 1-step Tweedie inversion in latent space.*
> 2. *Superior detection precision (66.67%) and lowest false alarm rate (12.1%) via directional cosine divergence.*
> 3. *First numerical proof of zero-shot pixel-level localization against authentic FaceForensics++ binary masks (53.1% IoU, 97.7% recall).*
> 4. *Social media compression robustness with $<7\%$ metric drift under aggressive WhatsApp JPEG Q30.*

---

## 7. Recommended Presentation Slide Flow (8-10 Minutes)

1. **Slide 1: Title & Candidacy**
   - Title: *Latent Score Divergence: Active Manifold Inversion Dynamics for AI-Generated Deepfake Detection and Pixel-Level Manipulation Localization*
   - Candidate: Ritik Yadav (Roll No: **2301178**)
   - Supervisor: Dr. Nilkanta Sahu, CSE Department, IIIT Guwahati
2. **Slide 2: Motivation & Background**
   - The deepfake challenge in video & imagery.
   - The failure of spatial CNNs under social media compression.
   - The computational bottleneck of iterative diffusion methods (DIRE takes 2.5 seconds per frame).
3. **Slide 3: Proposed Architecture (LSD)**
   - High-level pipeline diagram (RGB $\to$ VAE $\to$ Perturbation $\to$ UNet $\to$ Tweedie $\to$ Cosine Divergence $\to$ Heatmap).
4. **Slide 4: Mathematical Innovation**
   - Tweedie's formula connecting marginal score to 1-step inversion.
   - Directional cosine angle suppressing illumination false alarms.
   - High-frequency Laplacian perturbation for GAN boundary exposure.
5. **Slide 5: Empirical Baseline Comparison (Tesla T4 GPU)**
   - Table 5.1: 4-way benchmark showing $58\times$ speedup (43.2 ms vs 2,500 ms) and highest precision (66.67%).
6. **Slide 6: Ground-Truth Localization Proof (Phase 5)**
   - Table 6.1: 53.1% IoU, 97.7% Pixel Recall against authentic FaceForensics++ masks.
   - Visual multi-panel figure showing clean heatmaps on real vs fake faces.
7. **Slide 7: LoRA Domain Adaptation & Compression Robustness**
   - Low-Rank Adapter convergence and parameter efficiency ($<0.5\%$ weights).
   - Invariance table: $<7\%$ variance across JPEG Q95 to Q30 compression.
8. **Slide 8: Conclusion & Future Enhancements**
   - Summary of the 4 key contributions.
   - Future directions: spatio-temporal video volumes, TensorRT edge deployment, demographic fairness.

---

## 8. Verification & Submission Checklist

- [x] **Report PDF:** [`BTech_Project_Report_Ritik_Yadav.pdf`](file:///Users/ritikyadav/Desktop/Research%20Pdf/BTech_Project_Report_Ritik_Yadav.pdf) (19 pages, clean centered pagination, no headers/footers, all tables and equations intact).
- [x] **Overleaf LaTeX Package:** [`latex_report.zip`](file:///Users/ritikyadav/Desktop/Research%20Pdf/latex_report.zip) (Ready for instant Overleaf compile).
- [x] **Codebase:** Fully committed and synchronized to GitHub repository [`ritik-luck/DeepFake-And-Image-Manipulation-Detection`](https://github.com/ritik-luck/DeepFake-And-Image-Manipulation-Detection).
- [x] **Critical Metrics to Remember:**
  - Speedup: **$58\times$** (43.2 ms vs 2,500 ms)
  - IoU: **53.1%**, Pixel Recall: **97.7%**, P-AUROC: **78.5%**
  - Compression Shift: **$<7.0\%$** at JPEG Q30
  - Precision: **66.67%** (vs 61.7% in $\text{LaRE}^2$, 58.2% in DIRE)
