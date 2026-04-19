"""Save PNG snapshots."""
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import scipy.ndimage
import os


def save_field_snapshot(S, P, M, config, step_count, output_dir='results'):
    os.makedirs(output_dir, exist_ok=True)
    fig, axes = plt.subplots(2, 2, figsize=(14, 12))

    im0 = axes[0, 0].imshow(S, cmap='Blues', vmin=0,
                              vmax=max(float(S.max()), 0.01))
    axes[0, 0].set_title(f'S mean={S.mean():.4f} max={S.max():.4f}')
    plt.colorbar(im0, ax=axes[0, 0], shrink=0.8)

    p_max = max(float(P.max()), 0.01)
    im1 = axes[0, 1].imshow(P, cmap='hot', vmin=0, vmax=p_max)
    axes[0, 1].set_title(f'P max={P.max():.4f} min={P.min():.4f}')
    plt.colorbar(im1, ax=axes[0, 1], shrink=0.8)

    im2 = axes[1, 0].imshow(M, cmap='viridis', vmin=0,
                              vmax=max(float(M.max()), 0.01))
    axes[1, 0].set_title(f'M sum={M.sum():.1f} max={M.max():.4f}')
    plt.colorbar(im2, ax=axes[1, 0], shrink=0.8)

    # Detected units overlay
    M_bin = (M > config.MEMBRANE_THRESHOLD).astype(np.int32)
    labeled, num = scipy.ndimage.label(M_bin)
    imap = np.zeros(M.shape)
    cidx = 1
    closed = 0
    info = []
    for k in range(1, num + 1):
        mask = (labeled == k)
        filled = scipy.ndimage.binary_fill_holes(mask)
        inside = filled & ~mask
        if inside.sum() > config.MIN_INTERIOR_PIXELS:
            imap[inside] = cidx
            imap[mask] = cidx + 0.5
            info.append(f"U{cidx}:{inside.sum()}px")
            cidx += 1
            closed += 1

    if closed > 0:
        axes[1, 1].imshow(imap, cmap='tab10', vmin=0, vmax=max(cidx, 2))
    else:
        axes[1, 1].imshow(labeled, cmap='gray', vmin=0, vmax=max(num, 1))

    axes[1, 1].set_title(f'Closed: {closed} [{", ".join(info) or "none"}]')
    fig.suptitle(f'Step {step_count}', fontsize=14, fontweight='bold')
    plt.tight_layout()
    path = os.path.join(output_dir, f'snapshot_{step_count:06d}.png')
    plt.savefig(path, dpi=100)
    plt.close(fig)
    print(f"  [VIZ] {path}")
    return path
