"""
Evaluation Metrics for Image-Level Detection and Pixel-Level Localization.
Implements Roadmap Phase 0 Step 4, Phase 2 Step 6, and Phase 5 Step 2:
1. Image-level: AUROC, Average Precision (AP), Optimal F1 / Threshold on Validation set.
2. Pixel-level Localization: IoU, Pixel Precision, Pixel Recall, Pixel AUPRC against ground-truth masks.
"""

import numpy as np
import torch
from typing import Dict, Any, List, Tuple, Optional
from sklearn.metrics import roc_auc_score, average_precision_score, precision_recall_curve, roc_curve


def compute_detection_metrics(
    labels: List[int],
    scores: List[float],
    val_labels: Optional[List[int]] = None,
    val_scores: Optional[List[float]] = None
) -> Dict[str, float]:
    """
    Computes AUROC, Average Precision (AP), and calibrated threshold metrics.
    Adheres strictly to Roadmap Phase 2 Step 6:
    Threshold is calibrated on validation data (if provided) and evaluated on test data.
    """
    labels = np.array(labels)
    scores = np.array(scores)
    
    if len(np.unique(labels)) < 2:
        return {
            "auroc": 0.5,
            "ap": 0.5,
            "average_precision": 0.5,
            "threshold": 0.0,
            "optimal_threshold": 0.0,
            "accuracy": 0.5,
            "f1": 0.0
        }
        
    auroc = float(roc_auc_score(labels, scores))
    ap = float(average_precision_score(labels, scores))
    
    # Calibrate threshold on validation data if available
    calib_labels = np.array(val_labels) if val_labels is not None else labels
    calib_scores = np.array(val_scores) if val_scores is not None else scores
    
    fpr, tpr, thresholds = roc_curve(calib_labels, calib_scores)
    # Youden's J statistic = TPR - FPR
    j_scores = tpr - fpr
    best_idx = np.argmax(j_scores)
    optimal_threshold = float(thresholds[best_idx])
    
    # Evaluate at optimal threshold
    predictions = (scores >= optimal_threshold).astype(int)
    tp = np.sum((predictions == 1) & (labels == 1))
    fp = np.sum((predictions == 1) & (labels == 0))
    fn = np.sum((predictions == 0) & (labels == 1))
    tn = np.sum((predictions == 0) & (labels == 0))
    
    accuracy = float((tp + tn) / max(1, len(labels)))
    precision = float(tp / max(1, tp + fp))
    recall = float(tp / max(1, tp + fn))
    f1 = float(2 * precision * recall / max(1e-8, precision + recall))
    
    return {
        "auroc": auroc,
        "ap": ap,
        "average_precision": ap,
        "optimal_threshold": optimal_threshold,
        "accuracy": accuracy,
        "precision": precision,
        "recall": recall,
        "f1": f1
    }


def compute_localization_metrics(
    heatmap: torch.Tensor,
    ground_truth_mask: torch.Tensor,
    threshold: float = 0.5
) -> Dict[str, float]:
    """
    Computes pixel-level localization metrics between candidate heatmap and ground truth mask:
    - IoU (Intersection-over-Union)
    - Dice / F1 Score
    - Pixel-level AUROC (P-AUROC)
    - Pixel-level AUPRC (P-AUPRC)
    - Pixel Precision & Pixel Recall
    """
    # Detach and convert to numpy [H, W]
    pred = heatmap.detach().cpu().float().numpy().squeeze()
    gt = ground_truth_mask.detach().cpu().float().numpy().squeeze()
    
    # Normalize prediction to [0, 1]
    p_min, p_max = float(pred.min()), float(pred.max())
    if p_max > p_min:
        pred_norm = (pred - p_min) / (p_max - p_min)
    else:
        pred_norm = np.zeros_like(pred)
        
    gt_bin = (gt > 0.5).astype(int)
    pred_bin = (pred_norm >= threshold).astype(int)
    
    intersection = np.sum((pred_bin == 1) & (gt_bin == 1))
    union = np.sum((pred_bin == 1) | (gt_bin == 1))
    iou = float(intersection / max(1, union))
    
    tp = np.sum((pred_bin == 1) & (gt_bin == 1))
    fp = np.sum((pred_bin == 1) & (gt_bin == 0))
    fn = np.sum((pred_bin == 0) & (gt_bin == 1))
    
    pixel_precision = float(tp / max(1, tp + fp))
    pixel_recall = float(tp / max(1, tp + fn))
    dice = float(2 * intersection / max(1, 2 * intersection + fp + fn))
    
    # Pixel AUPRC & Pixel AUROC
    try:
        pixel_auprc = float(average_precision_score(gt_bin.flatten(), pred_norm.flatten()))
    except Exception:
        pixel_auprc = 0.0
        
    try:
        if len(np.unique(gt_bin)) >= 2:
            pixel_auroc = float(roc_auc_score(gt_bin.flatten(), pred_norm.flatten()))
        else:
            pixel_auroc = 0.5
    except Exception:
        pixel_auroc = 0.5
        
    return {
        "iou": iou,
        "dice": dice,
        "pixel_auroc": pixel_auroc,
        "pixel_auprc": pixel_auprc,
        "pixel_precision": pixel_precision,
        "pixel_recall": pixel_recall
    }
