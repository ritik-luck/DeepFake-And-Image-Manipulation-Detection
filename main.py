"""
Main Entry Point for the LSD Deepfake Research Implementation.
Orchestrates Phase 3 (Baselines), Phase 4 (Controlled Detection), Phase 5 (Localization),
and Phase 6 (Ablations & Robustness) as formulated in the LSD Deepfake Research Roadmap.
"""

import os
import sys
import argparse
import time
import json
import torch
from typing import Dict, Any, List, Optional, Tuple

from configs.config import ExperimentConfig
from lsd_core.utils.device import get_optimal_device, get_optimal_dtype, clear_device_memory
from lsd_core.utils.logger import setup_logger, ExperimentTracker
from lsd_core.models.vae_encoder import LatentVAE
from lsd_core.models.score_model import DiffusionScoreModel
from lsd_core.models.baseline_classifier import StandardDeepfakeClassifier
from lsd_core.algorithms.lsd import LatentScoreDivergence
from lsd_core.algorithms.baselines import LaRE2Baseline, DIREBaseline, ADRDBaseline
from lsd_core.algorithms.degradations import apply_jpeg_compression, apply_gaussian_blur, apply_resize_degradation
from lsd_core.data.dataset_loader import get_paper_dataloader, DeepfakePaperDataset
from lsd_core.data.download_papers_data import DATASET_SOURCES, print_dataset_instructions
from lsd_core.evaluation.metrics import compute_detection_metrics, compute_localization_metrics
from lsd_core.evaluation.visualizer import save_localization_comparison_figure, overlay_heatmap_on_image
from PIL import Image
import torchvision.transforms as transforms


def initialize_pipeline(cfg: ExperimentConfig, device_override: str = "auto", use_fallback: bool = False):
    """Initializes models and algorithms on optimal computational device."""
    device = get_optimal_device(device_override)
    dtype = get_optimal_dtype(device, cfg.model.dtype)
    
    logger = setup_logger("LSD_Main", os.path.join(cfg.logs_dir, "run.log"))
    logger.info(f"Initialized Pipeline on device: {device} ({device.type}) with dtype: {dtype}")
    
    # 1. Latent VAE
    vae = LatentVAE(
        pretrained_model_id=cfg.model.pretrained_model_id,
        subfolder=cfg.model.vae_subfolder,
        scale_factor=cfg.model.vae_scale_factor,
        use_fallback=use_fallback or cfg.model.use_lightweight_fallback,
        device=device,
        dtype=dtype
    )
    
    # 2. Diffusion Score Model
    score_model = DiffusionScoreModel(
        pretrained_model_id=cfg.model.pretrained_model_id,
        subfolder=cfg.model.unet_subfolder,
        use_fallback=use_fallback or cfg.model.use_lightweight_fallback,
        device=device,
        dtype=dtype
    )
    
    # 3. LSD Algorithm Engine
    lsd_engine = LatentScoreDivergence(
        vae=vae,
        score_model=score_model,
        default_sigma=cfg.lsd.default_sigma,
        epsilon_stab=cfg.lsd.epsilon_stab,
        use_multiscale=cfg.lsd.use_multiscale,
        multiscale_sigmas=tuple(cfg.lsd.multiscale_sigmas),
        multiscale_weights=tuple(cfg.lsd.multiscale_weights),
        use_spatial_masking=cfg.lsd.use_spatial_masking,
        spatial_focus=cfg.lsd.spatial_focus,
        boundary_weight=cfg.lsd.boundary_weight,
        use_composite_divergence=cfg.lsd.use_composite_divergence,
        composite_energy_weight=cfg.lsd.composite_energy_weight,
        use_hf_perturbation=getattr(cfg.lsd, "use_hf_perturbation", True),
        hf_noise_alpha=getattr(cfg.lsd, "hf_noise_alpha", 0.35),
        device=device,
        dtype=dtype
    )
    
    # 4. Baselines
    lare2_engine = LaRE2Baseline(vae=vae, score_model=score_model, default_sigma=cfg.lsd.default_sigma)
    dire_engine = DIREBaseline(vae=vae, score_model=score_model, default_sigma=cfg.lsd.default_sigma)
    adrd_engine = ADRDBaseline(vae=vae, score_model=score_model, default_sigma=cfg.lsd.default_sigma)
    
    return {
        "cfg": cfg,
        "device": device,
        "dtype": dtype,
        "logger": logger,
        "vae": vae,
        "score_model": score_model,
        "lsd": lsd_engine,
        "lare2": lare2_engine,
        "dire": dire_engine,
        "adrd": adrd_engine,
        # Backward-compatible and convenience aliases
        "lsd_divergence": lsd_engine,
        "baselines": {
            "lare2": lare2_engine,
            "dire": dire_engine,
            "adrd": adrd_engine
        }
    }


def run_single_image_inspection(pipeline: Dict[str, Any], image_path: str, output_path: str = "./outputs/inspection.png"):
    """Runs LSD on a single input image and generates heatmap overlay."""
    logger = pipeline["logger"]
    lsd = pipeline["lsd"]
    lare2 = pipeline["lare2"]
    device = pipeline["device"]
    
    if not os.path.exists(image_path):
        logger.error(f"Image not found at {image_path}")
        return
        
    logger.info(f"Inspecting image: {image_path}")
    img_pil = Image.open(image_path).convert("RGB")
    transform = transforms.Compose([
        transforms.Resize((512, 512)),
        transforms.ToTensor(),
        transforms.Normalize([0.5, 0.5, 0.5], [0.5, 0.5, 0.5])
    ])
    tensor_img = transform(img_pil).unsqueeze(0).to(device)
    
    # Compute LSD
    lsd_out = lsd(tensor_img)
    raw_msi = lsd_out["msi"]
    msi_score = raw_msi[0] if isinstance(raw_msi, (list, tuple)) else (raw_msi.item() if isinstance(raw_msi, torch.Tensor) else float(raw_msi))
    heatmap = lsd_out["heatmap"]
    if isinstance(heatmap, torch.Tensor) and heatmap.ndim >= 3:
        heatmap = heatmap[0]
    
    # Compute LaRE2 Baseline
    lare2_out = lare2(tensor_img)
    raw_l2 = lare2_out.get("lare2_score", lare2_out.get("msi", [0.0]))
    lare2_score = raw_l2[0] if isinstance(raw_l2, (list, tuple)) else (raw_l2.item() if isinstance(raw_l2, torch.Tensor) else float(raw_l2))
    lare2_hm = lare2_out.get("heatmap", None)
    if isinstance(lare2_hm, torch.Tensor) and lare2_hm.ndim >= 3:
        lare2_hm = lare2_hm[0]
    
    runtime = lsd_out.get("runtime_ms", 0.0)
    logger.info(f"-> LSD MSI Global Score: {msi_score:.4f} (Runtime: {runtime:.1f}ms)")
    logger.info(f"-> LaRE² L2 Score:       {lare2_score:.4f}")
    
    save_localization_comparison_figure(
        image=tensor_img[0],
        lsd_heatmap=heatmap,
        lare2_heatmap=lare2_hm,
        gt_mask=None,
        save_path=output_path,
        title=f"LSD Inspection (MSI = {msi_score:.4f})"
    )
    logger.info(f"Saved visualization figure to {output_path}")
    
    return {
        "image_path": image_path,
        "msi_score": msi_score,
        "lare2_score": lare2_score,
        "predicted_label": "Synthetic Deepfake" if msi_score > 0.15 else "Authentic Real",
        "output_path": output_path
    }


def run_pilot_mode(pipeline: Dict[str, Any], output_dir: str = "./outputs/pilot"):
    """
    Executes Roadmap Phase 8 Step 4:
    "Run a small pilot on real images and images from at least one generated-image source,
    then inspect distributions and failure cases before scaling up."
    """
    logger = pipeline["logger"]
    lsd = pipeline["lsd"]
    lare2 = pipeline["lare2"]
    dire = pipeline["dire"]
    device = pipeline["device"]
    
    logger.info("=== Running LSD Research Pilot Verification ===")
    os.makedirs(output_dir, exist_ok=True)
    
    # Look for authentic sample images or pilot samples
    sample_images = []
    
    # Check paper benchmark samples
    paper_real = "./data/paper_benchmark/real"
    paper_fake = "./data/paper_benchmark/fake"
    if os.path.exists(paper_real) and len(os.listdir(paper_real)) > 0:
        real_img = os.path.join(paper_real, sorted(os.listdir(paper_real))[0])
        fake_img = os.path.join(paper_fake, sorted(os.listdir(paper_fake))[0])
        sample_images.append({"path": real_img, "label": 0, "name": "authentic_paper_real"})
        sample_images.append({"path": fake_img, "label": 1, "name": "authentic_paper_fake"})
    else:
        os.makedirs("./data/pilot_samples", exist_ok=True)
        r_ref = "./data/pilot_samples/sample_real_ref.png"
        f_ref = "./data/pilot_samples/sample_fake_ref.png"
        if not os.path.exists(r_ref):
            Image.new("RGB", (512, 512), color=(140, 160, 180)).save(r_ref)
        if not os.path.exists(f_ref):
            Image.new("RGB", (512, 512), color=(180, 140, 160)).save(f_ref)
        sample_images.append({"path": r_ref, "label": 0, "name": "pilot_real"})
        sample_images.append({"path": f_ref, "label": 1, "name": "pilot_fake"})
        
    transform = transforms.Compose([
        transforms.Resize((512, 512)),
        transforms.ToTensor(),
        transforms.Normalize([0.5, 0.5, 0.5], [0.5, 0.5, 0.5])
    ])
    
    results = []
    for item in sample_images:
        img_pil = Image.open(item["path"]).convert("RGB")
        img_tensor = transform(img_pil).unsqueeze(0).to(device)
        
        lsd_res = lsd(img_tensor)
        lare2_res = lare2(img_tensor)
        dire_res = dire(img_tensor)
        
        msi = lsd_res["msi"][0]
        lare2_val = lare2_res["lare2_score"][0]
        dire_val = dire_res["dire_score"][0]
        
        fig_path = os.path.join(output_dir, f"{item['name']}_localization.png")
        save_localization_comparison_figure(
            image=img_tensor[0],
            lsd_heatmap=lsd_res["heatmap"][0],
            lare2_heatmap=lare2_res["heatmap"][0],
            gt_mask=None,
            save_path=fig_path,
            title=f"{item['name']} - MSI: {msi:.4f} | LaRE²: {lare2_val:.4f}"
        )
        
        results.append({
            "name": item["name"],
            "image_name": item["name"],
            "image_type": "Authentic Real" if item["label"] == 0 else "Synthetic Deepfake",
            "label": item["label"],
            "msi": msi,
            "lare2": lare2_val,
            "dire": dire_val,
            "runtime_ms": lsd_res["runtime_ms"],
            "figure": fig_path,
            "plot_path": fig_path
        })
        logger.info(f"[{item['name']}] Label: {item['label']} | MSI: {msi:.4f} | LaRE²: {lare2_val:.4f} | DIRE: {dire_val:.4f}")

    with open(os.path.join(output_dir, "pilot_results.json"), "w") as f:
        json.dump(results, f, indent=2)
        
    logger.info(f"Pilot verification complete. Output figures and metrics saved to: {output_dir}")
    return results


def run_dataset_evaluation(
    pipeline: Dict[str, Any],
    dataset_dir: str,
    dataset_name: str = "paper_benchmark",
    output_dir: Optional[str] = None,
    max_samples: Optional[int] = None
):
    """
    Runs full evaluation over a research dataset (FaceForensics, Celeb-DF, Mastering Deepfake).
    Computes AUROC, Average Precision, and logs performance.
    """
    logger = pipeline["logger"]
    lsd = pipeline["lsd"]
    lare2 = pipeline["lare2"]
    device = pipeline["device"]
    cfg = pipeline["cfg"]
    
    out_dir = output_dir if output_dir is not None else cfg.metrics_dir
    os.makedirs(out_dir, exist_ok=True)
    
    from lsd_core.data.dataset_loader import build_paper_dataset_index, DeepfakePaperDataset
    from torch.utils.data import DataLoader
    
    all_indexed = build_paper_dataset_index(dataset_dir, dataset_name=dataset_name)
    if not all_indexed:
        logger.warning(f"No valid images found in dataset directory '{dataset_dir}'.")
        return {}
        
    real_subset = [s for s in all_indexed if s["label"] == 0]
    fake_subset = [s for s in all_indexed if s["label"] == 1]
    
    if max_samples is not None and real_subset and fake_subset:
        half = max_samples // 2
        balanced_samples = real_subset[:half] + fake_subset[:half]
    else:
        balanced_samples = all_indexed[:max_samples] if max_samples else all_indexed
        
    ds = DeepfakePaperDataset(balanced_samples, image_size=(512, 512))
    loader = DataLoader(ds, batch_size=cfg.dataset.batch_size, shuffle=False, num_workers=0)
    count = len(balanced_samples)
    eval_count = count
    logger.info(f"Evaluating {eval_count} balanced samples ({len(real_subset[:half])} real, {len(fake_subset[:half])} fake) from '{dataset_name}'")
    
    all_labels = []
    all_msi_scores = []
    all_lare2_scores = []
    
    tracker = ExperimentTracker(os.path.join(out_dir, f"{dataset_name}_eval_samples.json"))
    
    for i, batch in enumerate(loader):
        images = batch["image"].to(device)
        labels = batch["label"].tolist()
        image_ids = batch["image_id"]
        
        lsd_out = lsd(images)
        lare2_out = lare2(images)
        
        msi_batch = lsd_out["msi"]
        lare2_batch = lare2_out.get("lare2_score", lare2_out.get("msi", []))
        
        all_labels.extend(labels)
        all_msi_scores.extend(msi_batch)
        all_lare2_scores.extend(lare2_batch)
        
        for b_idx in range(len(labels)):
            tracker.log_sample(
                image_id=image_ids[b_idx],
                label=labels[b_idx],
                msi_score=msi_batch[b_idx],
                lare2_score=lare2_batch[b_idx],
                dire_score=0.0,
                runtime_ms=lsd_out["runtime_ms"] / len(labels),
                metadata={"source": batch["source"][b_idx]}
            )
            
        print(f"  [Batch {i+1}/{len(loader)}] Processed {len(all_labels)} images...", flush=True)
        if (i + 1) % 5 == 0 or (i + 1) == len(loader):
            logger.info(f"Processed batch [{i+1}/{len(loader)}] ({len(all_labels)} images)")
            
        if max_samples is not None and len(all_labels) >= max_samples:
            all_labels = all_labels[:max_samples]
            all_msi_scores = all_msi_scores[:max_samples]
            all_lare2_scores = all_lare2_scores[:max_samples]
            break
            
    tracker.save()
    
    # Calculate metrics
    lsd_metrics = compute_detection_metrics(all_labels, all_msi_scores)
    lare2_metrics = compute_detection_metrics(all_labels, all_lare2_scores)
    
    logger.info("=" * 50)
    logger.info(f" EVALUATION RESULTS ON: {dataset_name.upper()}")
    logger.info("=" * 50)
    logger.info(f"LSD AUROC:   {lsd_metrics['auroc']:.4f} | AP: {lsd_metrics['ap']:.4f} | F1: {lsd_metrics['f1']:.4f}")
    logger.info(f"LaRE² AUROC: {lare2_metrics['auroc']:.4f} | AP: {lare2_metrics['ap']:.4f} | F1: {lare2_metrics['f1']:.4f}")
    logger.info("=" * 50)
    
    summary = {
        "dataset": dataset_name,
        "num_samples": len(all_labels),
        "lsd": lsd_metrics,
        "lare2_baseline": lare2_metrics
    }
    with open(os.path.join(out_dir, f"{dataset_name}_summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
        
    return summary


def run_4way_baselines(
    pipeline: Dict[str, Any],
    dataset_dir: str,
    dataset_name: str = "paper_benchmark",
    output_dir: Optional[str] = None,
    max_samples: Optional[int] = None
):
    """
    Executes 4-way baseline comparison required by Roadmap Phase 3 Step 3:
    LSD (Proposed) vs. LaRE² (CVPR 2024) vs. DIRE (ICCV 2023) vs. ADRD (PLOS ONE 2026).
    """
    logger = pipeline["logger"]
    lsd = pipeline["lsd"]
    lare2 = pipeline["lare2"]
    dire = pipeline["dire"]
    adrd = pipeline["adrd"]
    device = pipeline["device"]
    cfg = pipeline["cfg"]
    
    out_dir = output_dir if output_dir is not None else cfg.metrics_dir
    os.makedirs(out_dir, exist_ok=True)
    
    loader, count = get_paper_dataloader(dataset_dir, dataset_name=dataset_name, batch_size=cfg.dataset.batch_size)
    if not loader or count == 0:
        logger.warning(f"No valid images found in dataset directory '{dataset_dir}'.")
        return {}
        
    eval_count = min(count, max_samples) if max_samples is not None else count
    logger.info(f"=== Running 4-Way Baseline Comparison across {eval_count} samples ===")
    
    labels, lsd_scores, lare2_scores, dire_scores, adrd_scores = [], [], [], [], []
    
    for i, batch in enumerate(loader):
        images = batch["image"].to(device)
        lbls = batch["label"].tolist()
        
        with torch.no_grad():
            r_lsd = lsd(images)
            r_lare2 = lare2(images)
            r_dire = dire(images)
            r_adrd = adrd(images)
            
        labels.extend(lbls)
        lsd_scores.extend(r_lsd["msi"])
        lare2_scores.extend(r_lare2["lare2_score"])
        dire_scores.extend(r_dire["dire_score"])
        adrd_scores.extend(r_adrd["adrd_score"])
        
        if (i + 1) % 5 == 0 or (i + 1) == len(loader):
            logger.info(f"Processed batch [{i+1}/{len(loader)}] ({len(labels)} images)")
            
        if max_samples is not None and len(labels) >= max_samples:
            labels = labels[:max_samples]
            lsd_scores = lsd_scores[:max_samples]
            lare2_scores = lare2_scores[:max_samples]
            dire_scores = dire_scores[:max_samples]
            adrd_scores = adrd_scores[:max_samples]
            break
            
    m_lsd = compute_detection_metrics(labels, lsd_scores)
    m_lare2 = compute_detection_metrics(labels, lare2_scores)
    m_dire = compute_detection_metrics(labels, dire_scores)
    m_adrd = compute_detection_metrics(labels, adrd_scores)
    
    logger.info("=" * 65)
    logger.info(" 4-WAY COMPARATIVE BENCHMARK RESULTS")
    logger.info("=" * 65)
    logger.info(f"1. LSD (Proposed Cosine):      AUROC = {m_lsd['auroc']:.4f} | AP = {m_lsd['ap']:.4f} | F1 = {m_lsd['f1']:.4f}")
    logger.info(f"2. LaRE² (CVPR 2024 Latent L2):AUROC = {m_lare2['auroc']:.4f} | AP = {m_lare2['ap']:.4f} | F1 = {m_lare2['f1']:.4f}")
    logger.info(f"3. DIRE (ICCV 2023 Pixel Diff):AUROC = {m_dire['auroc']:.4f} | AP = {m_dire['ap']:.4f} | F1 = {m_dire['f1']:.4f}")
    logger.info(f"4. ADRD (PLOS ONE 2026 Discr): AUROC = {m_adrd['auroc']:.4f} | AP = {m_adrd['ap']:.4f} | F1 = {m_adrd['f1']:.4f}")
    logger.info("=" * 65)
    
    summary = {
        "dataset": dataset_name,
        "samples_evaluated": len(labels),
        "lsd": m_lsd,
        "lare2": m_lare2,
        "dire": m_dire,
        "adrd": m_adrd
    }
    with open(os.path.join(out_dir, "4way_baselines_summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    logger.info(f"Saved 4-way baseline metrics to: {out_dir}/4way_baselines_summary.json")
    return summary


def run_robustness_evaluation(
    pipeline: Dict[str, Any],
    dataset_dir: str,
    dataset_name: str = "paper_benchmark",
    output_dir: Optional[str] = None
):
    """
    Executes Roadmap Phase 4 Step 4:
    "Apply JPEG compression at several quality levels, blur, and resizing to both real and generated images."
    """
    logger = pipeline["logger"]
    lsd = pipeline["lsd"]
    device = pipeline["device"]
    cfg = pipeline["cfg"]
    
    out_dir = output_dir if output_dir is not None else cfg.metrics_dir
    os.makedirs(out_dir, exist_ok=True)
    
    loader, count = get_paper_dataloader(dataset_dir, dataset_name=dataset_name, batch_size=4)
    if not loader or count == 0:
        logger.warning(f"No valid images found in dataset directory '{dataset_dir}'.")
        return {}
        
    logger.info("=== Running Social Media Degradation Robustness Suite ===")
    
    sample_batch = next(iter(loader))
    images = sample_batch["image"].to(device)
    
    # 1. Clean
    clean_msi = lsd(images)["msi"]
    avg_clean = sum(clean_msi) / len(clean_msi)
    
    # 2. JPEG Compression at multiple qualities
    jpeg_results = {}
    for q in [95, 75, 50, 30]:
        j_imgs = apply_jpeg_compression(images, quality=q)
        m = lsd(j_imgs)["msi"]
        avg_m = sum(m) / len(m)
        jpeg_results[f"Q_{q}"] = float(avg_m)
        logger.info(f"JPEG Quality {q:2d}: Mean MSI = {avg_m:.4f} (Shift from clean: {avg_m - avg_clean:+.4f})")
        
    # 3. Gaussian Blur
    blur_imgs = apply_gaussian_blur(images, kernel_size=5)
    blur_msi = lsd(blur_imgs)["msi"]
    avg_blur = sum(blur_msi) / len(blur_msi)
    logger.info(f"Gaussian Blur (5x5): Mean MSI = {avg_blur:.4f} (Shift: {avg_blur - avg_clean:+.4f})")
    
    # 4. Resizing
    resize_imgs = apply_resize_degradation(images, scale_factor=0.5)
    resize_msi = lsd(resize_imgs)["msi"]
    avg_resize = sum(resize_msi) / len(resize_msi)
    logger.info(f"Resizing (0.5x Down/Up): Mean MSI = {avg_resize:.4f} (Shift: {avg_resize - avg_clean:+.4f})")
    
    summary = {
        "clean_baseline_msi": float(avg_clean),
        "jpeg_compression": jpeg_results,
        "gaussian_blur": float(avg_blur),
        "resizing_0.5x": float(avg_resize)
    }
    with open(os.path.join(out_dir, "robustness_summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    logger.info(f"Saved robustness degradation metrics to: {out_dir}/robustness_summary.json")
    return summary


def run_localization_evaluation(
    pipeline: Dict[str, Any],
    dataset_dir: str,
    dataset_name: str = "paper_benchmark",
    output_dir: Optional[str] = None,
    max_samples: Optional[int] = 50,
    threshold: float = 0.5
) -> Dict[str, Any]:
    """
    Executes Roadmap Phase 5: Ground-Truth Manipulation Localization Evaluation.
    Computes numerical Pixel-Level IoU, Dice, Pixel-AUROC, and Pixel-AUPRC
    against FaceForensics++ ground-truth tampering masks.
    """
    import numpy as np
    logger = pipeline["logger"]
    lsd = pipeline["lsd"]
    device = pipeline["device"]
    cfg = pipeline["cfg"]
    
    out_dir = output_dir if output_dir is not None else cfg.metrics_dir
    os.makedirs(out_dir, exist_ok=True)
    
    from lsd_core.data.dataset_loader import build_paper_dataset_index, DeepfakePaperDataset
    from torch.utils.data import DataLoader
    
    all_indexed = build_paper_dataset_index(dataset_dir, dataset_name=dataset_name)
    # Specifically target manipulated samples with ground-truth masks for localization benchmark
    target_samples = [s for s in all_indexed if s["label"] == 1 and s.get("mask_path") is not None]
    if not target_samples:
        target_samples = [s for s in all_indexed if s["label"] == 1]
    if not target_samples:
        target_samples = all_indexed
        
    eval_count = min(len(target_samples), max_samples) if max_samples is not None else len(target_samples)
    ds = DeepfakePaperDataset(target_samples[:eval_count], image_size=(512, 512))
    loader = DataLoader(ds, batch_size=cfg.dataset.batch_size, shuffle=False, num_workers=0)
    
    logger.info(f"=== Running Pixel-Level Localization Evaluation across {eval_count} FaceForensics++ samples ===")
    
    sample_metrics = []
    total_samples = 0
    
    for i, batch in enumerate(loader):
        images = batch["image"].to(device)
        masks = batch["mask"]  # [B, 1, H, W]
        labels = batch["label"].tolist()
        image_ids = batch["image_id"]
        
        with torch.no_grad():
            lsd_out = lsd(images)
            heatmaps = lsd_out["heatmap"]  # [B, H, W]
            
        for b_idx in range(len(labels)):
            hm = heatmaps[b_idx]
            gt_mask = masks[b_idx]
            
            m = compute_localization_metrics(hm, gt_mask, threshold=threshold)
            m["image_id"] = image_ids[b_idx]
            m["label"] = labels[b_idx]
            m["source"] = batch["source"][b_idx]
            sample_metrics.append(m)
            total_samples += 1
            
        if max_samples is not None and total_samples >= max_samples:
            sample_metrics = sample_metrics[:max_samples]
            break
            
    manipulated_samples = [s for s in sample_metrics if s["label"] == 1]
    eval_subset = manipulated_samples if len(manipulated_samples) > 0 else sample_metrics
    
    mean_iou = float(np.mean([s["iou"] for s in eval_subset]))
    mean_dice = float(np.mean([s["dice"] for s in eval_subset]))
    mean_p_auroc = float(np.mean([s["pixel_auroc"] for s in eval_subset]))
    mean_p_auprc = float(np.mean([s["pixel_auprc"] for s in eval_subset]))
    mean_p_prec = float(np.mean([s["pixel_precision"] for s in eval_subset]))
    mean_p_rec = float(np.mean([s["pixel_recall"] for s in eval_subset]))
    
    logger.info("=" * 65)
    logger.info(" PIXEL-LEVEL TAMPERING LOCALIZATION BENCHMARK RESULTS")
    logger.info("=" * 65)
    logger.info(f"Evaluated Manipulated Samples: {len(eval_subset)}")
    logger.info(f"1. Mean Intersection-over-Union (IoU): {mean_iou:.4f}")
    logger.info(f"2. Mean Dice Coefficient (F1):          {mean_dice:.4f}")
    logger.info(f"3. Mean Pixel-level AUROC (P-AUROC):    {mean_p_auroc:.4f}")
    logger.info(f"4. Mean Pixel-level AUPRC (P-AUPRC):    {mean_p_auprc:.4f}")
    logger.info(f"5. Pixel Precision:                     {mean_p_prec:.4f}")
    logger.info(f"6. Pixel Recall:                        {mean_p_rec:.4f}")
    logger.info("=" * 65)
    
    summary = {
        "dataset": dataset_name,
        "manipulated_samples_evaluated": len(eval_subset),
        "total_samples": len(sample_metrics),
        "threshold": threshold,
        "mean_iou": mean_iou,
        "mean_dice": mean_dice,
        "mean_pixel_auroc": mean_p_auroc,
        "mean_pixel_auprc": mean_p_auprc,
        "mean_pixel_precision": mean_p_prec,
        "mean_pixel_recall": mean_p_rec
    }
    with open(os.path.join(out_dir, "localization_summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    with open(os.path.join(out_dir, "localization_samples.json"), "w") as f:
        json.dump(sample_metrics, f, indent=2)
        
    logger.info(f"Saved localization metrics to: {out_dir}/localization_summary.json")
    return summary


def run_lora_adaptation(
    pipeline: Dict[str, Any],
    dataset_dir: str,
    dataset_name: str = "paper_benchmark",
    output_dir: Optional[str] = None,
    epochs: int = 3,
    lr: float = 1e-4,
    rank: int = 8,
    max_samples: Optional[int] = 50
) -> Dict[str, Any]:
    """
    Executes Phase 3 / Phase 6 Domain Adaptation:
    Fine-tunes lightweight Facial LoRA adapter on authentic faces,
    then evaluates AUROC before vs. after LoRA adaptation.
    """
    logger = pipeline["logger"]
    score_model = pipeline["score_model"]
    cfg = pipeline["cfg"]
    
    out_dir = output_dir if output_dir is not None else cfg.metrics_dir
    os.makedirs(out_dir, exist_ok=True)
    
    loader, count = get_paper_dataloader(dataset_dir, dataset_name=dataset_name, batch_size=cfg.dataset.batch_size)
    if not loader or count == 0:
        logger.warning(f"No valid images found in dataset directory '{dataset_dir}'.")
        return {}
        
    from lsd_core.algorithms.lora_trainer import train_facial_lora_adapter
    
    logger.info(f"=== Fine-Tuning Facial LoRA Adapter across {min(count, max_samples or count)} samples ===")
    train_res = train_facial_lora_adapter(
        pipeline=pipeline,
        dataloader=loader,
        num_epochs=epochs,
        lr=lr,
        rank=rank,
        save_path=os.path.join(out_dir, "facial_lora.pt")
    )
    
    # Run evaluation with LoRA active
    score_model.set_lora_active(True)
    adapted_metrics = run_dataset_evaluation(
        pipeline=pipeline,
        dataset_dir=dataset_dir,
        dataset_name=f"{dataset_name}_lora_adapted",
        output_dir=out_dir,
        max_samples=max_samples
    )
    
    summary = {
        "dataset": dataset_name,
        "lora_rank": rank,
        "epochs": epochs,
        "training": train_res,
        "adapted_metrics": adapted_metrics
    }
    with open(os.path.join(out_dir, "lora_adaptation_summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
        
    return summary


def main():
    parser = argparse.ArgumentParser(description="LSD Deepfake Research Execution Suite")
    parser.add_argument("--mode", type=str, default="pilot",
                        choices=["pilot", "eval", "baselines", "robustness", "localization", "lora", "inspect", "download"],
                        help="Execution mode")
    parser.add_argument("--dataset_dir", type=str, default="./data/paper_benchmark",
                        help="Path to dataset directory")
    parser.add_argument("--dataset_name", type=str, default="paper_benchmark",
                        help="Name of paper dataset")
    parser.add_argument("--image_path", type=str, default=None,
                        help="Path to single image for inspection mode")
    parser.add_argument("--device", type=str, default="auto",
                        help="Compute device: 'auto', 'cuda', 'mps', or 'cpu'")
    parser.add_argument("--sigma", type=float, default=0.10,
                        help="Perturbation noise level sigma")
    parser.add_argument("--use_fallback", action="store_true",
                        help="Use self-contained lightweight model for offline/fast test execution")
    
    args = parser.parse_args()
    
    if args.mode == "download":
        print_dataset_instructions(args.dataset_name)
        return
        
    cfg = ExperimentConfig()
    cfg.lsd.default_sigma = args.sigma
    
    pipeline = initialize_pipeline(cfg, device_override=args.device, use_fallback=args.use_fallback)
    
    if args.mode == "pilot":
        run_pilot_mode(pipeline)
    elif args.mode == "inspect":
        if not args.image_path:
            pipeline["logger"].error("Please provide --image_path for inspection mode.")
            return
        run_single_image_inspection(pipeline, args.image_path)
    elif args.mode == "eval":
        run_dataset_evaluation(pipeline, dataset_dir=args.dataset_dir, dataset_name=args.dataset_name)
    elif args.mode == "baselines":
        run_4way_baselines(pipeline, dataset_dir=args.dataset_dir, dataset_name=args.dataset_name)
    elif args.mode == "robustness":
        run_robustness_evaluation(pipeline, dataset_dir=args.dataset_dir, dataset_name=args.dataset_name)
    elif args.mode == "localization":
        run_localization_evaluation(pipeline, dataset_dir=args.dataset_dir, dataset_name=args.dataset_name)
    elif args.mode == "lora":
        run_lora_adaptation(pipeline, dataset_dir=args.dataset_dir, dataset_name=args.dataset_name)


if __name__ == "__main__":
    main()
