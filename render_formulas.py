import matplotlib.pyplot as plt

plt.rcParams.update({
    'text.usetex': False,
    'mathtext.fontset': 'cm',
    'font.family': 'sans-serif',
})

def render_formula(text_lines, filename, figsize=(9.0, 1.4), bg_color='#F0F7FF', text_color='#003366'):
    fig = plt.figure(figsize=figsize, facecolor=bg_color)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_facecolor(bg_color)
    ax.axis('off')
    
    n = len(text_lines)
    for i, (line, size, weight) in enumerate(text_lines):
        y = 0.5 if n == 1 else (0.75 - i * 0.45)
        ax.text(0.5, y, line, fontsize=size, fontweight=weight, color=text_color,
                ha='center', va='center')
        
    plt.savefig(filename, dpi=300, bbox_inches='tight', pad_inches=0.08, facecolor=bg_color)
    plt.close()
    print(f'Rendered {filename}')

# Formula 1: Tweedie Inversion
render_formula([
    (r"$\mathbb{E}[z_0 \mid z_t] = \frac{1}{\sqrt{\bar{\alpha}_t}} \left( z_t + (1 - \bar{\alpha}_t) \nabla_{z_t} \log p_t(z_t) \right)$", 17, 'bold'),
    (r"$\nabla_{z_t} \log p_t(z_t) = -\frac{\epsilon_\theta(z_t, t)}{\sqrt{1 - \bar{\alpha}_t}} \quad \Longrightarrow \quad \hat{z}_0(z_t) = \frac{z_t - \sqrt{1 - \bar{\alpha}_t}\,\epsilon_\theta(z_t, t)}{\sqrt{\bar{\alpha}_t}}$", 16, 'normal')
], 'formula_tweedie.png', figsize=(9.5, 1.6))

# Formula 2: Directional Cosine Divergence
render_formula([
    (r"$\mathcal{S}_{\mathrm{cos}}(x) = 1 - \frac{\mathbf{d} \cdot \epsilon_{\mathrm{pert}}}{\|\mathbf{d}\|_2 \, \|\epsilon_{\mathrm{pert}}\|_2 + \epsilon_{\mathrm{stab}}}, \quad \mathbf{d} = z_t - \hat{z}_0(z_t)$", 17, 'bold'),
    (r"Differential Spectral Perturbation: $\epsilon_{\mathrm{pert}} = (1 - \alpha_{\mathrm{HF}})\,\epsilon_{\mathrm{Gauss}} + \alpha_{\mathrm{HF}}\,\mathbf{L}(z_0), \quad \alpha_{\mathrm{HF}} = 0.35$", 15, 'normal')
], 'formula_cosine.png', figsize=(9.5, 1.6))

# Formula 3: LoRA Adaptation
render_formula([
    (r"$W = W_0 + \Delta W = W_0 + \frac{\alpha}{r} B \cdot A, \quad B \in \mathbb{R}^{d \times r},\; A \in \mathbb{R}^{r \times k},\; r=8,\; \alpha=16$", 16, 'bold')
], 'formula_lora.png', figsize=(9.5, 0.9))

