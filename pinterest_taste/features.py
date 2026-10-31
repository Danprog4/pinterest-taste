"""Image -> 3484-d vector: SigLIP 2 (1152) + DINOv2 (2304) + 10 zero-shot axes + 18 colour/light stats."""
import numpy as np
from PIL import Image

POS_PROMPTS = [
    "raw iphone mirror photo in dark gym, male physique compression shirt, authentic candid snapshot",
    "shirtless muscular back pump in gym mirror, dumbbell rack, real iphone camera grain",
    "authentic first person pov photo in gym, moody dim lighting, casual phone camera",
    "casual iphone photo of high protein meal eggs on plate on kitchen counter, natural indoor lighting",
    "candid masculine lifestyle photo taken on iphone, dark aesthetic, zero studio lighting",
]
NEG_PROMPTS = [
    "3d architectural render of luxury home gym with floor to ceiling windows and warm golden light",
    "professional studio photography with blurry background bokeh, commercial fitness stock photo",
    "black and white motion blur studio art photography on white background",
    "bright food blog photography with recipes, props, flowers, and studio softbox lighting",
    "graphic design, motivational quote poster, infographic, collage, watermark",
]


def _bokeh(im):
    arr = np.asarray(im.resize((240, 320), Image.BILINEAR), dtype=np.float32) / 255.0
    luma = 0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1] + 0.114 * arr[:, :, 2]
    lap = np.abs(4 * luma[1:-1, 1:-1] - luma[:-2, 1:-1] - luma[2:, 1:-1] - luma[1:-1, :-2] - luma[1:-1, 2:])
    ph, pw = lap.shape[0] // 4, lap.shape[1] // 4
    grid = np.array([[lap[r * ph:(r + 1) * ph, c * pw:(c + 1) * pw].mean() for c in range(4)] for r in range(4)])
    center = float(grid[1:3, 1:3].max())
    top = float(np.percentile(grid[0, :], 35))
    outer = float(np.percentile(np.concatenate([grid[0, :], grid[:, 0], grid[:, 3]]), 25))
    ratio = center / (min(top, outer) + 1e-4)
    blurry = 1.0 if (center > 0.022 and (top < 0.013 or outer < 0.011 or ratio > 2.6)) else 0.0
    r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    warm = float(((r - b > 0.14) & (r > g) & (luma > 0.15) & (luma < 0.70)).mean())
    glow = float((luma > 0.88).mean())
    return ratio, blurry, warm, glow


def color_light(im):
    try:
        arr = np.asarray(im.resize((160, 200), Image.BILINEAR), dtype=np.float32) / 255.0
        r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
        luma = 0.299 * r + 0.587 * g + 0.114 * b
        cmax, cmin = arr.max(axis=2), arr.min(axis=2)
        sat = np.where(cmax > 1e-4, (cmax - cmin) / (cmax + 1e-4), 0.0)
        gx = np.abs(luma[:, 1:] - luma[:, :-1]).mean()
        gy = np.abs(luma[1:, :] - luma[:-1, :]).mean()
        center = luma[40:160, 32:128].mean()
        border = np.concatenate([luma[:20, :].ravel(), luma[-20:, :].ravel()]).mean()
        ratio, blurry, warm, glow = _bokeh(im)
        return np.array([
            luma.mean(), luma.std(), np.percentile(luma, 10), np.percentile(luma, 50), np.percentile(luma, 90),
            float((luma < 0.20).mean()), float((luma > 0.82).mean()), sat.mean(), sat.std(), float((sat > 0.65).mean()),
            r.mean() - b.mean(), g.mean() - 0.5 * (r.mean() + b.mean()), gx + gy, center - border,
            min(ratio, 15.0) / 10.0, blurry * 3.0, warm * 3.0, glow * 3.0,
        ], dtype=np.float32)
    except Exception:
        return np.zeros(18, dtype=np.float32)


class Embedder:
    """Loads SigLIP 2 + DINOv2 once (~5 GB download on first run, cached by Hugging Face)."""

    def __init__(self, device=None):
        import timm, torch
        from transformers import AutoModel, AutoProcessor
        from torchvision import transforms
        self.torch = torch
        self.device = device or ("mps" if torch.backends.mps.is_available() else "cuda" if torch.cuda.is_available() else "cpu")
        dt = torch.float16 if self.device != "cpu" else torch.float32
        self.dt = dt
        mid = "google/siglip2-so400m-patch14-384"
        self.proc = AutoProcessor.from_pretrained(mid)
        self.sig = AutoModel.from_pretrained(mid, dtype=dt).eval().to(self.device)
        self.dino = timm.create_model("vit_base_patch14_dinov2.lvd142m", pretrained=True).eval().to(self.device)
        self.tf = transforms.Compose([
            transforms.Resize((518, 518), interpolation=transforms.InterpolationMode.BICUBIC),
            transforms.ToTensor(),
            transforms.Normalize((0.485, 0.456, 0.406), (0.229, 0.224, 0.225)),
        ])
        F = torch.nn.functional
        with torch.no_grad():
            def txt(p):
                o = self.sig.get_text_features(**self.proc(text=p, padding="max_length", return_tensors="pt").to(self.device))
                o = o.pooler_output if hasattr(o, "pooler_output") else o
                return F.normalize(o.float(), dim=-1)
            self.pos, self.neg = txt(POS_PROMPTS), txt(NEG_PROMPTS)

    def __call__(self, images, batch=16):
        torch, F = self.torch, self.torch.nn.functional
        out = []
        for i in range(0, len(images), batch):
            ims = images[i:i + batch]
            with torch.no_grad():
                s_in = self.proc(images=ims, return_tensors="pt").to(self.device, dtype=self.dt)
                s = self.sig.get_image_features(**s_in)
                s = s.pooler_output if hasattr(s, "pooler_output") else s
                s = F.normalize(s.float(), dim=-1)
                zs = torch.cat([s @ self.pos.T, s @ self.neg.T], dim=-1) * 10.0
                t = self.dino.forward_features(torch.stack([self.tf(im) for im in ims]).to(self.device))
                cls = F.normalize(t[:, 0, :], dim=-1)
                pm = F.normalize(t[:, 5:, :].mean(dim=1), dim=-1)
                ps = F.normalize(t[:, 5:, :].std(dim=1), dim=-1)
                d = F.normalize(torch.cat([cls * 0.65, pm * 0.45, ps * 0.40], dim=-1), dim=-1)
            s, zs, d = s.cpu().numpy(), zs.cpu().numpy(), d.cpu().numpy()
            for j, im in enumerate(ims):
                out.append(np.concatenate([s[j] * 0.72, d[j] * 0.69, zs[j] * 0.12, color_light(im) * 0.15]).astype(np.float32))
        return np.array(out, dtype=np.float32)
