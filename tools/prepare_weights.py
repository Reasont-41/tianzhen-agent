"""仅在显式执行时从 Torchvision 官方地址准备骨干；请求处理期间不下载。"""
from pathlib import Path
import hashlib
import shutil
import torch
from torchvision.models import MobileNet_V3_Small_Weights

root = Path(__file__).resolve().parent.parent / "app/artifacts"
root.mkdir(exist_ok=True)
target = root / "mobilenet_v3_small-047dcff4.pth"
if not target.exists():
    state = MobileNet_V3_Small_Weights.IMAGENET1K_V1.get_state_dict(progress=True, check_hash=True)
    cached = Path(torch.hub.get_dir()) / "checkpoints" / target.name
    shutil.copyfile(cached, target)
print(target.name, hashlib.sha256(target.read_bytes()).hexdigest())
