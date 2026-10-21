"""离线验证模型、数据清单与当前代码，不访问外部服务。"""
from pathlib import Path
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.core.store import get_kb
from app.core.diagnosis import get_diagnosis_module

metrics=json.loads((ROOT/'app/artifacts/diagnosis_metrics.json').read_text(encoding='utf-8'))
manifest=json.loads((ROOT/'app/artifacts/dataset_manifest.json').read_text(encoding='utf-8'))
assert metrics['evaluation_protocol']=='stratified_train_validation_test_60_20_20'
assert hashlib.sha256((ROOT/'app/artifacts/diagnosis_clf.pkl').read_bytes()).hexdigest()==metrics['model_sha256']
assert hashlib.sha256((ROOT/'app/artifacts/mobilenet_v3_small-047dcff4.pth').read_bytes()).hexdigest().startswith('047dcff4')
groups={name:{r['sha256'] for r in manifest['rows'] if r['split']==name} for name in ['train','validation','test']}
assert not(groups['train']&groups['validation'] or groups['train']&groups['test'] or groups['validation']&groups['test'])
kb=get_kb()
assert sum(r.verification_status=='verified_by_standard' for r in kb.pesticides)==6
assert sum(r.verification_status=='seed_unverified' for r in kb.pesticides)==34
dm=get_diagnosis_module()
assert dm.available and dm._ensure_backbone(), dm._backbone_error
print('离线模型加载、模型哈希、数据划分不重叠和知识库状态检查通过。')
