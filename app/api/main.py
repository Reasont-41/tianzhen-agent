"""后端 API 服务。

对外提供四个能力：
  /api/meta          知识库元信息（覆盖范围、核验状态统计）
  /api/consult       核心接口：问诊 -> 诊断 -> 处方 -> 校验 -> 施药窗口
  /api/diagnose      单张图片的视觉诊断
  /api/prescription/validate   对**外部给出的处方**做独立校验

第四个接口是这个产品区别于普通"AI问答"的地方：它把校验层开放出来，
任何来源的用药建议（别的系统、大模型、农资店）都可以丢进来过一遍合规检查。
这让"校验"从产品内部实现变成一项可独立调用的能力。

运行： python -m app.api.main
     或 uvicorn app.api.main:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import base64
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.core import (  # noqa: E402
    ConstrainedGenerator,
    MockWeatherProvider,
    PrescriptionPipeline,
    SprayContext,
    UnconstrainedBaselineGenerator,
    compute_spray_window,
    get_kb,
)
from app.core.diagnosis import get_diagnosis_module  # noqa: E402
from app.core.models import Prescription, PrescriptionItem  # noqa: E402
from app.core.spray_window import china_now
from app.core.agent import get_agent_runtime  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT / "web"
ARTIFACT_DIR = ROOT / "artifacts"
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}

app = FastAPI(
    title="田诊卫士 API",
    description="从拍照问诊到规则校验与施药窗口提示的农业决策辅助服务",
    version="0.3.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """为页面和 API 增加不影响本地演示的基础安全响应头。"""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    elif str(response.headers.get("content-type", "")).startswith("text/html"):
        # 首页 HTML 必须每次向服务器确认，否则浏览器会按启发式规则长期缓存，
        # 导致服务端已更新、用户仍看到旧页面。这里用 no-cache + ETag 重新验证：
        # 内容没变时服务器返回 304，几乎无额外开销；内容变了立刻拿到新版。
        response.headers["Cache-Control"] = "no-cache"
    return response

kb = get_kb()
pipeline = PrescriptionPipeline(kb, ConstrainedGenerator(kb))
baseline_pipeline = PrescriptionPipeline(kb, UnconstrainedBaselineGenerator(kb))
weather_provider = MockWeatherProvider()
agent_runtime = get_agent_runtime()


# ---------------------------------------------------------------- 请求模型


class StrictRequest(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")


class ConsultRequest(StrictRequest):
    query: str = Field("", max_length=500, description="农户的口语化描述，如“叶子背面长白毛”")
    crop: str = Field(..., min_length=1, max_length=20, description="作物")
    disease: str | None = Field(None, max_length=50, description="已知病害名，可省略由系统检索")
    harvest_in_days: int | None = Field(None, ge=0, le=365, description="预计多少天后采收")
    history_applications: int | None = Field(None, ge=0, le=100, description="本季该药剂已用次数；未知时留空")
    history_by_record: dict[str, Annotated[int, Field(ge=0, le=100)]] = Field(default_factory=dict, max_length=100)
    healthy_observation: bool = False
    show_baseline: bool = Field(False, description="是否同时返回无校验对照结果")


class ValidateItem(StrictRequest):
    pesticide_name: str = Field(..., min_length=1, max_length=100)
    dosage_value: float | None = Field(None, ge=0)
    dosage_unit: str = Field("", max_length=30)
    safety_interval_days: int | None = Field(None, ge=0, le=3650)
    source_record_id: str | None = Field(None, max_length=100)
    formulation: str = Field("", max_length=100)
    active_ingredient: str = Field("", max_length=100)
    ai_content: str = Field("", max_length=50)
    reg_cert_no: str | None = Field(None, max_length=100)


class ValidateRequest(StrictRequest):
    crop: str = Field(..., min_length=1, max_length=20)
    disease: str = Field(..., min_length=1, max_length=50)
    items: list[ValidateItem] = Field(..., max_length=100)
    harvest_in_days: int | None = Field(None, ge=0, le=365)
    history_applications: int | None = Field(None, ge=0, le=100)
    history_by_record: dict[str, Annotated[int, Field(ge=0, le=100)]] = Field(default_factory=dict, max_length=100)


class AgentChatRequest(StrictRequest):
    session_id: str | None = Field(None, max_length=64)
    message: str = Field("", max_length=1000)
    crop: str = Field("番茄", min_length=1, max_length=20)
    image_base64: str | None = Field(None, max_length=15_000_000)
    harvest_in_days: int | None = Field(None, ge=0, le=365)
    history_applications: int | None = Field(None, ge=0, le=100)
    history_by_record: dict[str, Annotated[int, Field(ge=0, le=100)]] = Field(default_factory=dict, max_length=100)


# ---------------------------------------------------------------- 元信息


@app.get("/api/meta")
def meta():
    status_count: dict[str, int] = {}
    for r in kb.pesticides:
        status_count[r.verification_status] = status_count.get(r.verification_status, 0) + 1

    dm = get_diagnosis_module()
    return {
        "crops": kb.crops,
        "diseases": [
            {"crop": d.crop, "name": d.name, "aliases": d.aliases, "pathogen": d.pathogen}
            for d in kb.diseases
        ],
        "n_pesticide_records": len(kb.pesticides),
        "n_banned": len(kb.banned_names),
        "n_restricted": len(kb.restricted_map),
        "verification_status": status_count,
        "vision_model": {
            "available": dm.available,
            "supported_crops": list(dm.supported_crops),
            "metrics": dm.metrics or None,
        },
        "n_diseases": len(kb.diseases),
        "registration_verified_records": sum(r.registration_verified for r in kb.pesticides),
        "weather": {"is_simulated": True, "source": "确定性模拟天气", "timezone": "Asia/Shanghai"},
        "disclaimer": (
            "本系统所有用药建议均基于公开农药登记信息整理，仅供参考；"
            "实际用药请以农药标签和当地植保部门指导为准。"
        ),
    }


def _build_context(crop: str, disease: str, harvest_in_days: int | None,
                   history: int | None) -> SprayContext:
    today = china_now().date()
    return SprayContext(
        crop=crop,
        disease_name=disease,
        application_date=today,
        planned_harvest_date=(today + timedelta(days=harvest_in_days)
                              if harvest_in_days is not None else None),
        history_applications=history,
    )


def _attach_spray_window(result, crop: str, disease: str, harvest_in_days: int | None) -> dict:
    """给放行处方里的首选药剂配上施药窗口期。"""
    payload = result.to_dict()
    items = result.released_items + (result.review_items or [])
    if not items:
        payload["spray_window"] = None
        payload["spray_windows"] = []
        return payload

    weather = weather_provider.forecast()
    windows = []
    for item in items:
        rec = kb.resolve_record_for_item(item)
        window = compute_spray_window(weather, kb.spray_rules, kb.preferred_windows, record=rec,
            planned_harvest_date=(china_now().date() + timedelta(days=harvest_in_days)
                                 if harvest_in_days is not None else None))
        data = window.to_dict()
        data.update({"for_pesticide": item.pesticide_name, "record_id": item.source_record_id,
                     "review_required": item in (result.review_items or [])})
        windows.append(data)
    payload["spray_windows"] = windows
    payload["spray_window"] = windows[0]
    return payload


# ---------------------------------------------------------------- 核心接口


@app.post("/api/consult")
def consult(req: ConsultRequest):
    crop = req.crop.strip()
    query = req.query.strip()
    if crop not in kb.crops:
        raise HTTPException(400, f"暂不支持作物「{crop}」，当前覆盖：{'、'.join(kb.crops)}")

    if req.healthy_observation:
        return {"crop": crop, "disease_name": "待确认" if query else "健康观察",
                "diagnosis_status": "needs_clarification" if query else "healthy",
                "diagnosis": [], "prescription": {"items": [], "notes": []},
                "validation": {"results": [], "blocking": [], "warnings": [], "passed": False,
                               "decision": "not_applicable"},
                "released": False, "released_items": [], "rejected_items": [], "review_items": [],
                "item_verdicts": [], "traceability": [], "spray_window": None, "spray_windows": [],
                "review_required": False, "ready_for_field_use": False,
                "clarification": ["照片倾向健康，但文字描述了异常；请补拍病斑并确认症状，当前不生成用药建议。"
                                  if query else "当前照片未发现已支持类别的明显病斑；先观察并记录变化，无需据此生成用药建议。"]}

    disease_name = None
    if req.disease:
        disease = kb.find_disease(crop, req.disease)
        if disease is None:
            raise HTTPException(400, f"「{req.disease.strip()}」不在「{crop}」的当前病害覆盖范围内")
        disease_name = disease.name
    if not query and disease_name is None:
        raise HTTPException(400, "请提供症状描述或有效的图像识别结果")

    ctx = _build_context(crop, disease_name or "", req.harvest_in_days, req.history_applications)
    ctx.history_by_record = req.history_by_record
    result = pipeline.run(
        query=query, crop=crop, disease_name=disease_name, context=ctx
    )
    payload = _attach_spray_window(result, crop, result.disease_name, req.harvest_in_days)
    payload["review_required"] = bool(result.review_items)
    # 当前气象和禁限用资料尚属竞赛演示版本，不据此签发田间处方。
    payload["ready_for_field_use"] = False
    payload["product_mode"] = "competition_demo"

    if req.show_baseline:
        b = baseline_pipeline.run(
            query=query, crop=crop, disease_name=disease_name, context=ctx
        )
        # 注意：要按**条目**统计不合规数，而不是按规则触发次数。
        # 同一条建议可能同时违反多条规则（例如既用错作物又超剂量），
        # 按规则计数会让"不合规条目数"大于总条目数，指标失真。
        blocked_names = {
            r.evidence.get("pesticide")
            for r in b.report.blocking
            if r.evidence.get("pesticide")
        }
        total = len(b.prescription.items)
        noncompliant = len([i for i in b.prescription.items if i.pesticide_name in blocked_names])
        payload["baseline_without_validator"] = {
            "experiment_type": "synthetic_error_injection",
            "description": "代码按固定种子注入错误的演示，非真实大模型输出或独立合规评估。",
            "items": [i.to_dict() for i in b.prescription.items],
            "total_items": total,
            "noncompliant_count": noncompliant,
            "compliant_count": total - noncompliant,
            "compliance_rate": round((total - noncompliant) / max(total, 1), 4),
            "blocking_rule_hits": len(b.report.blocking),
            "blocking_details": [r.to_dict() for r in b.report.blocking],
        }
    return payload


@app.get("/api/agent/status")
def agent_status():
    """告诉前端当前使用大模型规划还是本地规划；不返回密钥。"""
    llm = agent_runtime.llm
    if llm.available:
        return {"mode": "llm", "model": llm.model, "reason": None}
    reason = "已通过 TIANZHEN_LLM_DISABLE 关闭大模型" if llm.disabled else "未配置大模型 API Key"
    return {"mode": "fallback", "model": None, "reason": reason}


@app.post("/api/agent/chat")
def agent_chat(req: AgentChatRequest):
    """对话式智能体入口：大模型规划工具，规则引擎负责否决。"""
    crop = req.crop.strip()
    if crop not in kb.crops:
        raise HTTPException(400, f"暂不支持作物「{crop}」，当前覆盖：{'、'.join(kb.crops)}")

    image_result = None
    if req.image_base64:
        raw = req.image_base64.strip()
        if raw.startswith("data:"):
            raw = raw.split(",", 1)[-1]
        try:
            content = base64.b64decode(raw, validate=True)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, "图片数据无法解析，请重新上传。") from exc
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "图片不能超过 10 MB，请压缩后重试。")
        image_result = get_diagnosis_module().predict(content, crop=crop).to_dict()

    if not req.message.strip() and image_result is None:
        raise HTTPException(400, "请先描述症状或上传叶片照片。")

    try:
        result = agent_runtime.run(
            message=req.message,
            crop=crop,
            session_id=req.session_id,
            image_result=image_result,
            harvest_in_days=req.harvest_in_days,
            history_applications=req.history_applications,
            history_by_record=req.history_by_record,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return result.to_dict()


@app.post("/api/diagnose")
async def diagnose(crop: str = Form(...), file: UploadFile = File(...)):
    crop = crop.strip()
    if crop not in kb.crops:
        raise HTTPException(400, f"暂不支持作物「{crop}」，当前覆盖：{'、'.join(kb.crops)}")
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(415, "仅支持 JPEG、PNG 或 WebP 图片")

    dm = get_diagnosis_module()
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if not content:
        raise HTTPException(400, "上传文件为空")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "图片不能超过 10 MB，请压缩后重试")
    result = dm.predict(content, crop=crop)
    return result.to_dict()


@app.post("/api/prescription/validate")
def validate_prescription(req: ValidateRequest):
    """对外部处方做独立合规校验 —— 校验能力的对外开放接口。"""
    crop = req.crop.strip()
    if crop not in kb.crops:
        raise HTTPException(400, f"暂不支持作物「{crop}」，当前覆盖：{'、'.join(kb.crops)}")
    disease = kb.find_disease(crop, req.disease)
    if disease is None:
        raise HTTPException(400, f"「{req.disease.strip()}」不在「{crop}」的当前病害覆盖范围内")

    ctx = _build_context(crop, disease.name, req.harvest_in_days, req.history_applications)
    ctx.history_by_record = req.history_by_record
    pres = Prescription(
        crop=crop,
        disease_name=disease.name,
        items=[
            PrescriptionItem(
                pesticide_name=i.pesticide_name,
                dosage_value=i.dosage_value,
                dosage_unit=i.dosage_unit,
                safety_interval_days=i.safety_interval_days,
                source_record_id=i.source_record_id,
                formulation=i.formulation,
                active_ingredient=i.active_ingredient,
                ai_content=i.ai_content,
                reg_cert_no=i.reg_cert_no,
            )
            for i in req.items
        ],
        generated_by="external",
    )
    report = pipeline.engine.validate(pres, ctx, kb.resolve_record_for_item)
    verdict = PrescriptionPipeline._per_item_verdict(pres, report)
    return {
        "passed": report.passed,
        "decision": report.decision,
        "ready_for_field_use": False,
        "review_required": bool(report.warnings),
        "report": report.to_dict(),
        "per_item": verdict,
    }


@app.get("/api/experiment/e2")
def experiment_e2():
    import json

    p = ARTIFACT_DIR / "experiment_e2.json"
    if not p.exists():
        raise HTTPException(404, "实验数据尚未生成，请先运行 python -m app.experiment_e2")
    return json.loads(p.read_text(encoding="utf-8"))


@app.get("/api/health")
def health():
    return {"status": "ok", "time": datetime.now().isoformat(timespec="seconds")}


# ---------------------------------------------------------------- 前端


@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


@app.get("/agent")
def agent_page():
    return FileResponse(WEB_DIR / "agent.html")


if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")
