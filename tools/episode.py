"""单片状态、人工交接、定点取帧与可重放渲染入口。"""
import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

import core_snapshot
from profile_loader import DEFAULT_PROFILE, environment, load_profile
from bgm_common import DEFAULT_BGM_GAIN, locate_tools, resolve_default_bgm, sha256_file

ROOT = Path(__file__).resolve().parents[1]
TRACK = ROOT / "output/evergreen_vibe"
GATES = ("review", "delivery")


def read(path):
    return json.loads(path.read_text("utf-8-sig"))


def validate_contract(name, value):
    from jsonschema import Draft202012Validator
    schema = read(Path(__file__).parent / "contracts" / (name + ".schema.json"))
    issue = next(Draft202012Validator(schema).iter_errors(value), None)
    if issue:
        raise ValueError(f"{name}{list(issue.path)}: {issue.message}")


def within(root, relative):
    p = (root / relative).resolve()
    if not p.is_relative_to(root.resolve()):
        raise ValueError(f"路径越界: {relative}")
    return p


def sample_plan(score, profile=None, overrides=()):
    profile = profile or load_profile()
    timeline = profile.hard["timeline"]
    requests = {item["scope"]:item for item in overrides}
    if len(requests) != len(overrides):
        raise ValueError("同一幕重复登记")
    if any(item["rule"] not in profile.data["allowedOverrides"] for item in overrides):
        raise ValueError("制作档案禁止覆盖此规则")
    applied = []

    validate_contract("beats", score)
    fps = score["fps"]
    tier = score["duration_tier"]
    if fps != profile.hard["video"]["fps"] or score["track"] != "evergreen_vibe" or tier not in ("standard", "long"):
        raise ValueError("轨道、fps 或片长档位错误")
    low, high = timeline["duration"][tier]
    if not low <= score["totalSec"] <= high:
        raise ValueError("总时长超界")
    def boundary(seconds):
        frame = seconds * fps
        if abs(frame - round(frame)) > 1e-6:
            raise ValueError(f"分幕边界未落在整数帧: {seconds}")
        return round(frame)
    cuts = 0
    mode = score["cut_mode"]
    if mode not in ("cinema","rhythmic") or score["lighting"] not in ("studio_dark","keynote_light"):
        raise ValueError("切镜或光场模式错误")
    if mode == "cinema" and not timeline["cinemaCues"][0] <= len(score["effects"]) <= timeline["cinemaCues"][1]:
        raise ValueError("常规题材微音效数量超出制作档案范围")
    start = 0
    readings, seams = {}, []
    for beat in score["beats"]:
        key = str(beat["id"])
        end = boundary(beat["endSec"])
        if (key in readings or start != boundary(beat["startSec"]) or end <= start
                or end - start != boundary(beat["durationSec"]) or type(beat["hardCut"]) is not bool):
            raise ValueError(f"幕号、连续性或时长错误: {key}")
        duration = beat["durationSec"]
        if not any(lo <= duration <= hi for lo,hi in profile.data["defaults"]["beatDurationSec"]):
            request = requests.get(f"B{beat['id']:02d}")
            if not request or request["value"] != duration:
                raise ValueError(f"B{beat['id']:02d} 时长 {duration}s 超出 {profile.data['id']} 默认区间；"
                                 "请修订分幕，或用 vibe-3.4 登记单幕例外并在 review 确认")
            applied.append(request)
        text = "".join(beat["lines"]).replace("【","").replace("】","").strip()
        if not 1 <= len(text) <= timeline["maxTextChars"]:
            raise ValueError(f"主句字数错误: {key}")
        cuts += bool(start and beat["hardCut"])
        a, b = beat["readingStartSec"], beat["readingEndSec"]
        lo, hi = timeline["readingSec"]
        if not lo - 1e-8 <= b - a <= hi + 1e-8:
            raise ValueError(f"阅读窗长度错误: {key}")
        first, stop = math.ceil(a * fps - 1e-8), math.ceil(b * fps - 1e-8)
        if not start <= first < stop <= end:
            raise ValueError(f"阅读窗越界: {key}")
        readings[key] = [first, (first + stop - 1) // 2, stop - 1]
        if start and not beat["hardCut"]:
            seams.append([start - 1, start])
        start = end
    if len(applied) != len(overrides):
        raise ValueError("例外未命中实际超界的幕号与值")
    if cuts > timeline["maxCuts"][mode]:
        raise ValueError("硬切次数超界")
    if start != boundary(score["totalSec"]) or not 0 <= score["alignClimaxSec"] < score["totalSec"]:
        raise ValueError("末帧或高潮越界")
    for cue in score["effects"]:
        if not 0 <= cue["timeSec"] < score["totalSec"]:
            raise ValueError("音效越界")
    frames = sorted({f for row in [*readings.values(), *seams] for f in row})
    return {"frames": frames, "reading": readings, "seams": seams, "count": start, "applied_overrides":applied}


def journal(ep):
    folder = within(ep, "src/reviews")
    return [read(p) for p in sorted(folder.glob("*.json"))]


def record(ep, data):
    folder = within(ep, "src/reviews")
    folder.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    data.update(at=now.isoformat(), id=uuid.uuid4().hex)
    dest = folder / (now.strftime("%Y%m%dT%H%M%S%f") + "-" + data["id"] + ".json")
    with tempfile.NamedTemporaryFile(dir=folder, delete=False, mode="w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(f.name, dest)
    return data


def manifest_digest(manifest):
    # Legacy workstation concurrency never changes approved content.
    content = {k:v for k,v in manifest.items() if k != "concurrency"}
    raw = json.dumps(content,sort_keys=True,ensure_ascii=False,separators=(",",":")).encode()
    return hashlib.sha256(raw).hexdigest()


def bindings(ep, gate, *, legacy=False):
    """Bind the inputs that select and supply rendered content."""
    manifest = read(within(ep, "src/manifest.json"))
    validate_contract("manifest", manifest)
    score = read(ep/"beats.json")
    profile = load_profile(manifest.get("profile", DEFAULT_PROFILE))
    sample_plan(score, profile, manifest.get("overrides", []))
    root = within(ep, "src")
    generated = {"manifest.json", "final_qc.json", "reading_qc.json", "decoder_check.json",
                 "sfx_only.wav", "sfx_generation.json"}
    sources = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts", ".json",
               ".css", ".scss", ".sass", ".less", ".svg", ".wasm"}
    if legacy:
        sources = {".ts", ".tsx"}
    else:
        public = within(ep, manifest.get("publicDir", "src/assets"))
        entry = within(root, manifest["entry"])
        if not entry.is_file() or not public.is_dir():
            raise ValueError("缺少单期入口或素材目录")
        if not math.isfinite(manifest.get("bgmGainDb", DEFAULT_BGM_GAIN)):
            raise ValueError("BGM 增益必须有限")
    hashes = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        rel = path.relative_to(ep).as_posix()
        name = path.relative_to(root).as_posix()
        if rel.startswith(("src/review/", "src/reviews/", "src/production/", "src/evidence/")) or name in generated:
            continue
        if path.suffix.lower() in sources or name.startswith(("assets/","vendor/vibe/")):
            hashes[rel] = sha256_file(within(ep, rel))
    if not legacy:
        hashes[entry.relative_to(ep).as_posix()] = sha256_file(entry)
        for path in sorted(public.rglob("*")):
            rel = path.relative_to(ep).as_posix()
            if path.is_symlink() and path.is_dir():
                raise ValueError(f"素材目录不接受符号链接子目录: {rel}")
            if path.is_file() and rel not in hashes:
                hashes[rel] = sha256_file(within(ep, rel))
    sfx = within(ep, manifest["sfx"])
    hashes[sfx.relative_to(ep).as_posix()] = sha256_file(sfx)
    hashes["beats.json"] = sha256_file(within(ep, "beats.json"))
    try:
        bgm = within(ROOT, manifest["bgm"]) if manifest.get("bgm") else resolve_default_bgm()
    except SystemExit as exc:
        # 缺默认配乐的检出（如只解压了恢复包）不能让 status 直接退出。
        raise ValueError(f"配乐不可用: {exc}") from exc
    hashes["bgm"] = sha256_file(bgm)
    hashes.update(profile.stamp)
    if not legacy:
        beat_path = within(ROOT, bgm.with_suffix(".beats.json"))
        beat_bytes = beat_path.read_bytes()
        if json.loads(beat_bytes.decode("utf-8-sig")).get("source_sha256") != hashes["bgm"]:
            raise ValueError("BGM 节拍档案与音源不匹配，请先运行 bgm_analyze.py")
        hashes["bgm_beats_sha256"] = hashlib.sha256(beat_bytes).hexdigest()
        config = {key: manifest[key] for key in ("entry", "previewComposition", "fullComposition", "sfx")}
        config.update(
            publicDir=manifest.get("publicDir", "src/assets"),
            bgm=bgm.relative_to(ROOT.resolve()).as_posix() if bgm.is_relative_to(ROOT.resolve()) else str(bgm),
            bgmGainDb=manifest.get("bgmGainDb", DEFAULT_BGM_GAIN),
            overrides=manifest.get("overrides", []),
            profile=profile.data["id"],
        )
        hashes["content_config_sha256"] = manifest_digest(config)
    if gate == "delivery":
        for name in (film_name(ep), "cover.png", "contact_sheet.png", "src/final_qc.json",
                     "src/reading_qc.json", "src/decoder_check.json", "bgm_mix_report.json",
                     "src/sfx_only.wav"):
            hashes[name] = sha256_file(within(ep, name))
    return hashes


def film_name(ep):
    return ep.name.split("_", 1)[1] + ".mp4"


def covers(approved, current):
    return approved == current


def archived_approvals(ep, approvals):
    """Read completed pre-binding-v2 deliveries without reauthorizing production."""
    if any(not e or e.get("kind") != "approval" or
           "content_config_sha256" in e.get("bindings", {}) for e in approvals.values()):
        return {}
    try:
        for gate, event in approvals.items():
            old = event["bindings"]
            if any(old.get(key) != value for key, value in bindings(ep, gate, legacy=True).items()):
                return {}
        from delivery_check import verify
        verify(ep)
    except (OSError, ValueError, KeyError):
        return {}
    return {gate: event["id"] for gate, event in approvals.items()}


def state(ep):
    events = journal(ep)
    approvals = {gate: next((e for e in reversed(events) if e.get("gate") == gate), None)
                 for gate in GATES}
    result = {}
    for gate, current in approvals.items():
        if not current or current.get("kind") != "approval":
            break
        try:
            if not covers(current.get("bindings", {}), bindings(ep, gate)):
                break
        except (FileNotFoundError, ValueError):
            break
        result[gate] = current["id"]
    if not result:
        result = archived_approvals(ep, approvals)
    closed = {e["request"] for e in events if e["kind"] == "resolved"}
    pending = [e["id"] for e in events if e["kind"] == "handoff" and e["id"] not in closed]
    requests = read(ep/"src/manifest.json").get("overrides",[])
    return {"requested_overrides":requests,"applied_overrides":requests if "review" in result else [],
            "pending": pending, "approved": result,
            "nextGate": next((g for g in GATES if g not in result), "done"),
            "history": events}


def content_approval(ep, requests):
    event = next((e for e in reversed(journal(ep)) if e.get("gate") == "review"), None)
    if (not event or event.get("kind") != "approval" or event.get("acceptedOverrides", []) != requests
            or not covers(event.get("bindings", {}), bindings(ep, "review"))):
        raise ValueError("需要有效的 review 样片批准")
    return event


def review_evidence(ep, current):
    movie = within(ep, "src/review/preview.mp4")
    try:
        digest = sha256_file(movie)
        receipt = read(within(ep, "src/review/receipt.json"))
        qc = read(within(ep, "src/review/preview_qc.json"))
    except (OSError, ValueError) as exc:
        raise ValueError("review 缺少有效的快审视频、收据或 QC") from exc
    if (not movie.stat().st_size or not isinstance(qc, dict) or not isinstance(receipt, dict)
            or qc.get("passed") is not True or qc.get("media_sha256") != digest
            or receipt.get("media") != digest or not covers(receipt.get("approved"), current)):
        raise ValueError("review 的快审证据过期或与当前内容不匹配")
    return digest


def plan(ep, mode, concurrency=None):
    m = read(within(ep, "src/manifest.json"))
    validate_contract("manifest", m)
    core_snapshot.verify(ep, m.get("coreSnapshot"))
    if m.get("version") != 1:
        raise ValueError("manifest.version 必须为 1")
    entry = within(within(ep, "src"), m["entry"])
    if not entry.is_file():
        raise ValueError("单期入口不存在")
    score = read(ep / "beats.json")
    profile = load_profile(m.get("profile", DEFAULT_PROFILE))
    requests = m.get("overrides", [])
    timeline = sample_plan(score,profile,requests)
    cfg = environment(concurrency=concurrency,legacy=m.get("concurrency"))
    video = profile.hard["video"]
    preview = mode == "preview"
    count = m["previewFrames"] if preview else timeline["count"]
    lo,hi = video["previewSec"]
    if preview and not lo <= count / video["previewFps"] <= hi:
        raise ValueError("快审时长不符合绑定档案")
    public = within(ep, m.get("publicDir","src/assets"))
    if not public.is_dir():
        raise ValueError("单期资源目录不存在")
    return {"entry": str(entry), "publicDir":str(public), "composition": m[mode + "Composition"],
            **profile.stamp, "renderConfig":video, "applied_overrides":requests,
            "transport": cfg.get("renderTransport", "auto"),
            "width":video["width"],"height":video["height"],"fps":video["previewFps"] if preview else video["fps"],"frames":count,
            "scale":video["previewScale"] if preview else 1,"concurrency":cfg["concurrency"],"mode":mode,
            "timeline":timeline if not preview else None, "inputProps":{"profile":profile.data,"score":score,"samplePlan":timeline}}


def preflight(ep, mode, concurrency=None):
    spec = plan(ep,mode,concurrency)
    python_path = environment()["pythonPath"]
    if python_path and Path(python_path).resolve() != Path(sys.executable).resolve():
        raise ValueError(f"请使用配置的 Python 运行: {python_path}")
    if sys.version_info[:3] != (3,12,4):
        raise ValueError("需要项目 Python 3.12.4")
    sfx = within(ep,read(ep/"src/manifest.json")["sfx"])
    if not sfx.is_relative_to(ep/"src") or not sfx.is_file():
        raise ValueError("缺少 src/ 内的单期微音效母带")
    bindings(ep,"review")
    ffmpeg,_,_ = locate_tools()
    subprocess.run(["node",str(ROOT/"tools/check_entry.cjs"),spec["entry"]],cwd=ROOT,check=True)
    return spec, ffmpeg


JOB_ACTIONS = ("snapshot", "preview", "full", "remix", "finish", "verify", "ship")
_JOB = None


def job_path(ep):
    return within(ep, ".work/active_job.json")


def job_read(ep):
    path = job_path(ep)
    return read(path) if path.is_file() else None


def job_write(ep, data):
    path = job_path(ep)
    path.parent.mkdir(parents=True, exist_ok=True)
    data["updatedAt"] = datetime.now(timezone.utc).isoformat()
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False, mode="w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    os.replace(handle.name, path)


def job_touch(**changes):
    if not _JOB:
        return
    data = job_read(_JOB["ep"]) or {"jobId": _JOB["id"]}
    data.update(changes)
    job_write(_JOB["ep"], data)


def pid_alive(pid):
    if not pid:
        return False
    if os.name != "nt":
        try:
            os.kill(int(pid), 0)
            return True
        except OSError:
            return False
    import ctypes
    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))
    if not handle:
        return False
    ctypes.windll.kernel32.CloseHandle(handle)
    return True


def tail_lines(path, count):
    if not path.is_file() or count <= 0:
        return []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        return handle.read().splitlines()[-count:]


def job_command(ep, args):
    import time as _time
    deadline = _time.time() + max(0.0, float(args.wait or 0))
    while True:
        data = job_read(ep)
        if not data:
            return {"status": "none", "episode": str(ep)}
        # The supervisor outlives the action, so its pid is the race-free watchdog:
        # a dead action process may simply be between exit and the final write.
        watchdog = data.get("supervisorPid") or data.get("pid")
        if data.get("status") == "running" and watchdog and not pid_alive(watchdog):
            # 宿主 kill-on-close 作业对象可能在动作写入结果前带走整棵进程树。
            log = within(ep, data["logPath"]) if data.get("logPath") else None
            tail = tail_lines(log, 3)
            detail = ("；最后日志: " + " / ".join(tail)) if tail else ""
            data.update(status="failed", stage="failed",
                        error=data.get("error") or
                        f"进程已退出但未写入结果（stage={data.get('stage')}, pid={watchdog}）{detail}")
            job_write(ep, data)
        if data.get("status") != "running" or _time.time() >= deadline:
            break
        _time.sleep(0.5)
    log = within(ep, data["logPath"]) if data.get("logPath") else None
    data["logTail"] = tail_lines(log, args.tail or 20) if log else []
    return data


def detach(ep, args, parser):
    if os.name != "nt":
        parser.error("--detach 目前仅支持 Windows 独立进程组")
    job_id = uuid.uuid4().hex
    work = within(ep, ".work")
    work.mkdir(parents=True, exist_ok=True)
    log = work / (job_id + ".log")
    record = {"jobId": job_id, "pid": None, "action": args.action, "status": "running",
              "stage": "starting", "runDir": None, "logPath": ".work/" + job_id + ".log",
              "startedAt": datetime.now(timezone.utc).isoformat(), "exitCode": None, "error": None}
    # The record is durable before the child exists, so a launcher that never
    # reaches its own bookkeeping is still reported instead of leaving "running".
    job_write(ep, record)
    child_cmd = [sys.executable, "-B", str(Path(__file__).resolve()), args.action, str(ep)]
    for flag, value in (("--mode", args.mode), ("--work", args.work), ("--note", args.note),
                        ("--concurrency", args.concurrency), ("--bgm-gain", args.bgm_gain),
                        ("--transport", args.transport)):
        if value is not None:
            child_cmd += [flag, str(value)]
    if args.clean_abandoned:
        child_cmd += ["--clean-abandoned"]
    # A thin supervisor owns the job record: it keeps the pid alive for polling
    # and writes the real exit code back even when the child dies at startup.
    cmd = [sys.executable, "-B", str(Path(__file__).resolve()), "job-run", str(ep),
           "--job-id", job_id, "--job-command", json.dumps(child_cmd)]
    env = os.environ.copy()
    env["VIBE_JOB_ID"] = job_id
    flags = (subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
             | subprocess.CREATE_NO_WINDOW)
    try:
        with log.open("a", encoding="utf-8") as stream:
            options = dict(cwd=ROOT, env=env, stdin=subprocess.DEVNULL, stdout=stream,
                           stderr=subprocess.STDOUT, close_fds=True)
            try:
                child = subprocess.Popen(cmd, creationflags=flags | subprocess.CREATE_BREAKAWAY_FROM_JOB, **options)
            except OSError:
                # Job objects that forbid breakaway still accept a normal detached child.
                child = subprocess.Popen(cmd, creationflags=flags, **options)
    except BaseException as exc:
        record.update(status="failed", stage="failed", exitCode=1,
                      error=f"后台拉起失败: {type(exc).__name__}: {exc}")
        job_write(ep, record)
        raise
    record["pid"] = child.pid
    job_write(ep, record)
    return {"jobId": job_id, "pid": child.pid, "status": "running",
            "log": record["logPath"], "next": "episode.py job <ep> --wait 30"}


def supervise(ep, args):
    """Run one detached action as the child of a supervisor that owns the record."""
    job_id = args.job_id or os.environ.get("VIBE_JOB_ID")
    try:
        command = [str(item) for item in json.loads(args.job_command)]
    except (TypeError, ValueError) as exc:
        raise ValueError("job-run 需要合法的 --job-command") from exc
    if not job_id or not command:
        raise ValueError("job-run 需要 --job-id 与 --job-command")
    record = job_read(ep) or {"jobId": job_id, "logPath": ".work/" + job_id + ".log"}
    record.update(jobId=job_id, status="running", stage="starting", pid=os.getpid(),
                  supervisorPid=os.getpid(), exitCode=None, error=None)
    record.pop("finishedAt", None)
    job_write(ep, record)
    error = None
    try:
        code = subprocess.run(command, cwd=ROOT).returncode
    except BaseException as exc:
        # Interpreter missing, argument rejected, permission denied: still reported.
        code = 1
        error = f"{type(exc).__name__}: {exc}"
    latest = job_read(ep) or dict(record)
    if latest.get("jobId") != job_id:
        latest = dict(record)
    latest.update(jobId=job_id, exitCode=code, finishedAt=datetime.now(timezone.utc).isoformat())
    if code == 0:
        latest.update(status="succeeded", stage="done", error=None)
    else:
        latest.update(status="failed", stage="failed",
                      error=latest.get("error") or error or f"子进程退出码 {code}")
    job_write(ep, latest)
    return {"jobId": job_id, "exitCode": code, "error": latest.get("error")}


def job_attach(ep):
    global _JOB
    job_id = os.environ.get("VIBE_JOB_ID")
    if not job_id:
        return
    _JOB = {"ep": ep, "id": job_id}
    job_touch(pid=os.getpid(), status="running", stage="starting")


def job_finish(status, exit_code, error):
    if _JOB:
        job_touch(status=status, exitCode=exit_code, error=error,
                  stage="done" if status == "succeeded" else "failed")


class MixLevelError(ValueError):
    def __init__(self, work, diagnostic):
        self.work = work
        self.diagnostic = diagnostic
        super().__init__(f"响度闭环未通过: {diagnostic['integrated_lufs']:.2f} LUFS / "
                         f"{diagnostic['true_peak_dbtp']:.2f} dBTP，run={work}")


def produce(ep, mode, args, work=None, gain=None):
    current = state(ep)
    # 样片本身是 review 门禁的输入，只有全片必须先签 review。
    gate = "review" if mode == "full" else None
    if gate and gate not in current["approved"]:
        raise ValueError("需要有效的 review 样片批准")
    if current["pending"]:
        raise ValueError("仍有开放的导演意见: " + ", ".join(current["pending"]))
    manifest = read(ep/"src/manifest.json")
    approved_inputs = bindings(ep, "review")
    if gate:
        content_approval(ep, manifest.get("overrides", []))
    base_gain = manifest.get("bgmGainDb", DEFAULT_BGM_GAIN)
    if args.bgm_gain is not None and args.bgm_gain != base_gain:
        raise ValueError("请在清单登记 bgmGainDb，并使用该设置生成及确认快审")
    gain = base_gain if gain is None else gain
    if not math.isfinite(gain):
        raise ValueError("BGM 增益必须有限")
    if work is None:
        spec, ffmpeg = preflight(ep, mode, args.concurrency)
        work = within(ep, ".work/" + uuid.uuid4().hex)
        work.mkdir(parents=True)
        print(f"[episode] work={work}", file=sys.stderr, flush=True)
        job_touch(stage="render", runDir=str(work.relative_to(ep)))
        spec.update(ffmpeg=ffmpeg, work=str(work), approved=approved_inputs,
                    transport=args.transport or spec.get("transport", "auto"))
        path = work/"render-plan.json"
        path.write_text(json.dumps(spec, ensure_ascii=False), "utf-8")
        subprocess.run(["node", str(ROOT/"tools/render_episode.cjs"), str(path)], cwd=ROOT, check=True)
        if bindings(ep, "review") != approved_inputs:
            raise ValueError("渲染期间内容改变，候选作废")
        saved = {"mode": mode, "approved": approved_inputs,
                 "picture": sha256_file(work/"picture.mp4"),
                 "frames": {str(n): sha256_file(work/f"frame-{n}.png")
                            for n in (spec["timeline"] or {}).get("frames", [])}}
        (work/"picture-receipt.json").write_text(json.dumps(saved, ensure_ascii=False), "utf-8")
    else:
        spec = plan(ep, mode, args.concurrency)
        locate_tools()
        if not (work/"picture.mp4").is_file():
            raise ValueError("--work 目录缺少 picture.mp4")
        receipt_path = work/"picture-receipt.json"
        if not receipt_path.is_file():
            raise ValueError("--work 目录缺少原始 picture-receipt.json")
        saved = read(receipt_path)
        if (not covers(saved.get("approved"), approved_inputs)
                or saved.get("picture") != sha256_file(work/"picture.mp4") or saved.get("mode") != mode):
            raise ValueError("画面母版或内容版本不匹配")
    frames = {str(n): sha256_file(work/f"frame-{n}.png") for n in (spec["timeline"] or {}).get("frames", [])}
    if frames != saved.get("frames"):
        raise ValueError("断点抽样帧与原始 picture-receipt.json 不匹配")
    candidate = work/"delivery"/ep.name
    candidate.mkdir(parents=True, exist_ok=True)
    preview = mode == "preview"
    destination = within(ep, "src/review/preview.mp4") if preview else candidate/film_name(ep)
    mix = [sys.executable, "-B", str(ROOT/"tools/mix_bgm.py"), "--video", str(work/"picture.mp4"),
           "--profile", spec["profile_id"], "--beats", str(ep/"beats.json"),
           "--sfx", str(within(ep, manifest["sfx"])), "--out", str(destination)]
    if manifest.get("bgm"):
        mix += ["--bgm", str(within(ROOT, manifest["bgm"])), "--license-note", manifest["licenseNote"]]
    mix += ["--bgm-gain", str(gain)]
    if preview:
        mix += ["--preview-duration", str(spec["frames"]/spec["fps"])]
    else:
        mix += ["--sfx-out", str(candidate/"src/sfx_only.wav")]
    job_touch(stage="mix")
    diagnostic_path = candidate/"mix_diagnostic.json"
    if not preview:
        diagnostic_path.unlink(missing_ok=True)
    try:
        subprocess.run(mix, check=True)
    except subprocess.CalledProcessError as exc:
        if not preview and diagnostic_path.is_file():
            diagnostic = read(diagnostic_path)
            levels = [diagnostic.get(key) for key in ("integrated_lufs", "true_peak_dbtp")]
            reasons = set(diagnostic.get("reasons", []))
            if (diagnostic.get("bgm_gain_db") == gain and reasons
                    and reasons <= {"integrated_lufs", "true_peak_dbtp"} and all(
                    type(value) in (int, float) and math.isfinite(value) for value in levels)):
                raise MixLevelError(work, diagnostic) from exc
        raise
    if bindings(ep, "review") != approved_inputs:
        raise ValueError("制作中输入发生变化，请重新执行")
    receipt = {"profile_id": spec["profile_id"], "profile_sha256": spec["profile_sha256"],
               "applied_overrides": spec["applied_overrides"], "run": work.name, "mixCommand": mix,
               "inputs": approved_inputs, "picture": sha256_file(work/"picture.mp4"),
               "media": sha256_file(destination), "approved": approved_inputs,
               "frames": frames}
    (work/"receipt.json").write_text(json.dumps(receipt, ensure_ascii=False), "utf-8")
    if preview:
        dest = within(ep, "src/review/receipt.json")
        with tempfile.NamedTemporaryFile(dir=dest.parent, delete=False, mode="w", encoding="utf-8") as handle:
            json.dump(receipt, handle)
        os.replace(handle.name, dest)
    return {"work": work, "candidate": candidate, "destination": destination,
            "receipt": receipt, "spec": spec, "gain": gain}


def run_evidence(ep, mode, work, manifest):
    rel = manifest.get("evidenceScript")
    if not rel:
        return False
    script = within(ep, rel)
    if not script.is_file():
        raise ValueError("evidenceScript 不存在: " + rel)
    cmd = [sys.executable, "-B", str(script)] if script.suffix.lower() == ".py" else ["node", str(script)]
    job_touch(stage="evidence")
    subprocess.run(cmd + ["--mode", mode, "--episode", str(ep), "--work", str(work)],
                   cwd=ROOT, check=True)
    return True


def remove_tree(ep, path):
    """在 <episode>/.work/ 内安全删除一个 run 目录，只用 Python，不经过 Shell。

    外部 Shell 的批量删除在文件数多时会触发确认拦截，把已完成的 finish 拖成
    exit 1。这里先校验路径边界，再清只读位重试；仍失败就保留目录并留痕。
    """
    import shutil
    import stat
    target = Path(path)
    root = within(ep, ".work")
    if target.resolve().parent != root or not re.fullmatch(r"[0-9a-f]{32}", target.name):
        raise ValueError("清理边界")
    def clear(func, name, exc):
        try:
            os.chmod(name, stat.S_IWRITE)
            func(name)
        except FileNotFoundError:
            pass
    try:
        shutil.rmtree(target, onexc=clear)
    except OSError as exc:
        print(f"[clean] 保留未删除的 run {target.name}: {exc}", file=sys.stderr)
        return False
    return not target.exists()


def clean_abandoned(ep, keep):
    removed = []
    for path in sorted(within(ep, ".work").iterdir()):
        if not path.is_dir() or path == keep or not re.fullmatch(r"[0-9a-f]{32}", path.name):
            continue
        if (path/"receipt.json").is_file():
            continue
        if remove_tree(ep, path):
            removed.append(path.name)
    return removed


def ship(ep, args, parser):
    current = state(ep)
    if "review" not in current["approved"]:
        raise ValueError("需要有效的 review 批准")
    if current["pending"]:
        raise ValueError("仍有开放的导演意见: " + ", ".join(current["pending"]))
    work = None
    if args.work:
        work = within(within(ep, ".work"), args.work.resolve())
        if not work.is_dir():
            raise ValueError("--work 目录不存在")
    manifest = read(ep/"src/manifest.json")
    audio = load_profile(manifest.get("profile", DEFAULT_PROFILE)).hard["audio"]
    low, high = audio["lufs"]
    target, ceiling = (low + high) / 2, audio["truePeakMax"]
    gain, retries = None, []
    for attempt in range(3):
        try:
            result = produce(ep, "full", args, work=work, gain=gain)
            work = result["work"]
            break
        except MixLevelError as exc:
            if attempt == 2:
                raise
            work, diagnostic = exc.work, exc.diagnostic
            retries.append(diagnostic)
            correction = target - diagnostic["integrated_lufs"]
            peak = diagnostic["true_peak_dbtp"]
            if peak > ceiling:
                correction = min(correction, ceiling - peak - 0.1)
            gain = diagnostic["bgm_gain_db"] + correction
    if not run_evidence(ep, "full", work, manifest):
        for name in ("cover.png", "contact_sheet.png", "layout.json"):
            if not (work/name).is_file():
                raise ValueError("缺少视觉证据且未声明 evidenceScript: " + name)
    job_touch(stage="finish")
    from delivery_check import finish
    finish(ep, work, args.note or "ship 自动汇总：联系表、安全区与线宽待导演复核")
    job_touch(stage="verify")
    from delivery_check import verify
    final = verify(ep)
    removed = clean_abandoned(ep, work) if args.clean_abandoned else []
    movie = within(ep, film_name(ep))
    qc = read(within(ep, "src/final_qc.json"))
    mix = read(within(ep, "bgm_mix_report.json"))
    return {"passed": final["passed"], "media": str(movie), "bytes": movie.stat().st_size,
            "sha256": final["media_sha256"], "lufs": mix["integrated_lufs"],
            "truePeak": mix["true_peak_dbtp"], "mixRetries": retries,
            "nextGate": "delivery", "cleaned": removed,
            "cover": str(within(ep, "cover.png")), "contact": str(within(ep, "contact_sheet.png")),
            "hardware": qc["checks"].get("decoder")}


def run():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["status","snapshot","handoff","resolve","approve","plan",
                                           "preflight","preview","full","remix","finish","verify","ship",
                                           "job","job-run"])
    parser.add_argument("episode", type=Path)
    parser.add_argument("--work", type=Path)
    parser.add_argument("--request")
    parser.add_argument("--concurrency",type=int)
    parser.add_argument("--accept-overrides",action="store_true",help="兼容旧调用；review 签字会自动记录清单例外")
    parser.add_argument("--bgm-gain",type=float,help="显式确认清单基准增益；ship 可按响度实测自动校准")
    parser.add_argument("--gate", choices=GATES + ("topic","facts"),help="topic/facts 仅保留历史留痕，不再阻断")
    parser.add_argument("--mode", choices=["preview","full"], default="full")
    parser.add_argument("--detach",action="store_true",help="在独立进程组后台执行，父进程立即返回")
    parser.add_argument("--wait",type=float,default=0,help="job：等待秒数，结束即返回")
    parser.add_argument("--tail",type=int,default=20,help="job：日志尾部行数")
    parser.add_argument("--clean-abandoned",action="store_true",help="ship：verify 全绿后清理无 receipt 的坏 run")
    parser.add_argument("--transport",choices=["auto","remotion","cdp-pipe"],help="渲染通道；默认读 env 或 auto")
    parser.add_argument("--job-id",help=argparse.SUPPRESS)
    parser.add_argument("--job-command",help=argparse.SUPPRESS)
    for key in ("note","owner","scope","protect","evidence"):
        parser.add_argument("--"+key)
    args = parser.parse_args()
    ep = args.episode.resolve()
    if (not ep.is_dir() or not ep.is_relative_to(TRACK.resolve()) or
            len(ep.relative_to(TRACK.resolve()).parts) != 2 or not re.fullmatch(r"\d{2}_.+", ep.name)):
        parser.error("指定一个 output/evergreen_vibe/YYYY-MM-DD/NN_主题 目录")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}",ep.parent.name):
        parser.error("日期目录格式错误")
    if args.action == "job":
        return job_command(ep, args)
    if args.action == "job-run":
        # Handled before the manifest gate: a vanished manifest must still be
        # reported as a failed job instead of a silent "running" record.
        return supervise(ep, args)
    if not within(ep,"src/manifest.json").is_file():
        if args.action == "status":
            return {"state":"legacy_or_uninitialized","episode":str(ep)}
        raise ValueError("单期尚未采用新协议；不能写入历史交付")
    if args.detach:
        if args.action not in JOB_ACTIONS:
            parser.error("该动作不支持 --detach")
        return detach(ep, args, parser)
    job_attach(ep)
    if args.action in ("status","plan","preflight","verify"):
        return execute(args, ep, parser)
    # Windows releases this byte-range lock on process exit, including crashes.
    import msvcrt
    lockdir = within(ep, "src/reviews")
    lockdir.mkdir(parents=True,exist_ok=True)
    with within(ep,"src/reviews/episode.lock").open("a+b") as lock:
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        except OSError as exc:
            raise ValueError("本期已有写入任务正在运行") from exc
        return execute(args, ep, parser)


def execute(args, ep, parser):
    if args.action == "snapshot":
        validate_contract("manifest",read(within(ep,"src/manifest.json")))
        return core_snapshot.install(ep)
    if args.action == "plan":
        return plan(ep, args.mode,args.concurrency)
    if args.action == "preflight":
        return preflight(ep,args.mode,args.concurrency)[0]
    if args.action == "verify":
        from delivery_check import verify
        return verify(ep)
    current = state(ep)
    if args.action == "status":
        return current
    if args.action == "handoff":
        if not all((args.note,args.owner,args.scope,args.protect)):
            parser.error("交接需要 --note 原话、--owner 下一角色、--scope 范围、--protect 保护项")
        evidence = {}
        if args.evidence:
            evidence[args.evidence] = sha256_file(within(ep, args.evidence))
        return record(ep, {"kind":"handoff","note":args.note,"owner":args.owner,"scope":args.scope,
                           "protect":args.protect,"approved":current["approved"],"evidence":evidence})
    if args.action == "resolve":
        if args.request not in current["pending"] or not args.evidence or not args.note:
            parser.error("关闭一条开放意见需要 --request、--note、--evidence")
        return record(ep,{"kind":"resolved","request":args.request,"note":args.note,
                          "evidence":{args.evidence:sha256_file(within(ep,args.evidence))}})
    if current["pending"] and args.action != "preview" and not (args.action == "remix" and args.mode == "preview"):
        raise ValueError("仍有开放的导演意见: " + ", ".join(current["pending"]))
    if args.action == "approve":
        if args.gate in ("topic", "facts"):
            # 旧调用兼容：历史卡点只留痕，不再阻断任何动作。
            return record(ep, {"acceptedOverrides":[], "kind":"approval","gate":args.gate,
                               "note":args.note or "","bindings":{}})
        if not args.note or not args.gate or current["nextGate"] != args.gate:
            parser.error("需要当前卡点及导演实际确认原话；禁止代为批准")
        approved = bindings(ep, args.gate)
        evidence = {}
        if args.gate == "review":
            evidence["previewSha256"] = review_evidence(ep, approved)
        else:
            from delivery_check import verify
            verify(ep)
        requests = read(ep/"src/manifest.json").get("overrides",[])
        return record(ep, {"acceptedOverrides":requests,"kind":"approval","gate":args.gate,"note":args.note,
                           "bindings":approved, **evidence})
    if args.action == "ship":
        return ship(ep, args, parser)
    if args.action == "finish":
        if not args.work or not args.note:
            parser.error("finish 需要 --work 本次渲染目录、--note 联系表与安全区目视核查记录")
        if "review" not in current["approved"]:
            raise ValueError("需要有效的 review 批准")
        from delivery_check import finish
        return finish(ep, within(within(ep,".work"), args.work.resolve()), args.note)
    if args.action == "remix":
        if not args.work:
            parser.error("remix 需要 --work 既有候选目录")
        work = within(within(ep,".work"), args.work.resolve())
        result = produce(ep, args.mode, args, work=work)
        return {"candidate": str(result["destination"]), "work": str(result["work"]),
                "next": "导演快审" if args.mode == "preview" else "单期布局实测及 finish"}
    if args.action in ("preview", "full"):
        work = within(within(ep, ".work"), args.work.resolve()) if args.work else None
        result = produce(ep, args.action, args, work=work)
        if args.action == "preview":
            manifest = read(ep/"src/manifest.json")
            if run_evidence(ep, "preview", result["work"], manifest):
                qc = read(within(ep, "src/review/preview_qc.json"))
                if (qc.get("media_sha256") != sha256_file(result["destination"])
                        or qc.get("passed") is not True):
                    raise ValueError("快审证据未绑定本次成片")
        return {"candidate": str(result["destination"]), "work": str(result["work"]),
                "next": "导演快审" if args.action == "preview" else "单期布局实测及 finish"}



if __name__ == "__main__":
    try:
        result = run()
    except BaseException as exc:
        job_finish("failed", 1, str(exc))
        if isinstance(exc, SystemExit):
            raise
        sys.exit(f"[episode] {exc}")
    job_finish("succeeded", 0, None)
    print(json.dumps(result, ensure_ascii=False, indent=2))
