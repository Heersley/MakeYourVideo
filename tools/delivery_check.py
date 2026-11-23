"""验证唯一成片及六项证据；由 episode.py verify 或 approve delivery 调用。"""
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

from bgm_common import locate_tools, sha256_file
import core_snapshot
from profile_loader import DEFAULT_PROFILE, load_profile
from episode import (ROOT, content_approval, manifest_digest, bindings, covers, film_name, read,
                     remove_tree, sample_plan, within)

# 1.2.0 起归档 review 批准；更早的交付归档 facts 批准，两种文件名都接受。
APPROVALS = ("content-approval.json", "facts-approval.json")


def require(ok, name):
    if not ok:
        raise ValueError("验收失败: " + name)


# Non-hard-cut seams: concurrent Chromium workers occasionally land one or two
# levels of antialiasing on two otherwise identical frames. A moved element, a
# leftover border or a camera offset changes thousands of pixels, so all three
# limits together stay closed on real jumps while isolated raster noise passes.
# Reading-window text boxes are verified elsewhere and keep absolute zero.
SEAM_LIMITS = {"seam_delta": 0.01, "max_pixel_delta": 2, "changed_pixel_ratio": 0.0001}


def seam_record(frames, before, after):
    diff = cv2.absdiff(before, after)
    per_pixel = diff.max(axis=2)
    changed = int(np.count_nonzero(per_pixel))
    return {"frames": list(frames), "seam_delta": float(diff.mean()),
            "max_pixel_delta": int(per_pixel.max()) if changed else 0,
            "changed_pixels": changed,
            "changed_pixel_ratio": changed / float(per_pixel.size)}


def seam_passes(row, pixels=None):
    if not isinstance(row, dict):
        return False
    delta, peak = row.get("seam_delta"), row.get("max_pixel_delta")
    changed, ratio = row.get("changed_pixels"), row.get("changed_pixel_ratio")
    if (type(delta) not in (int, float) or type(peak) is not int or type(changed) is not int
            or type(ratio) not in (int, float) or min(delta, peak, changed, ratio) < 0):
        return False
    if pixels and abs(changed / pixels - ratio) > 1e-9:
        return False
    return (delta <= SEAM_LIMITS["seam_delta"] and peak <= SEAM_LIMITS["max_pixel_delta"]
            and ratio <= SEAM_LIMITS["changed_pixel_ratio"])


def seam_row_ok(row, pair, pixels):
    """Accept a three-limit record, or a pre-1.2.0 report that proved exact zero."""
    if not isinstance(row, dict) or row.get("frames") != pair:
        return False
    legacy = (row.get("seam_delta") == 0 and "max_pixel_delta" not in row
              and "changed_pixels" not in row)
    return legacy or seam_passes(row, pixels)


def original_frames(work, score, boxes, profile=None, overrides=()):
    """boxes 由单期 DOM 检查器产生。每个抽样帧列出全部静态文字框 [x,y,right,bottom]。"""
    profile = profile or load_profile()
    visual, video = profile.hard["visual"], profile.hard["video"]
    left,top,right,bottom = visual["safeZone"]
    plan = sample_plan(score,profile,overrides)
    def load(frame):
        path = within(work, f"frame-{frame}.png")
        img = cv2.imdecode(np.fromfile(path, np.uint8), cv2.IMREAD_COLOR)
        require(img is not None and img.shape == (video["height"],video["width"],3), f"原生 PNG {frame}")
        return img
    reading = {}
    for beat, frames in plan["reading"].items():
        base = load(frames[0])
        rects = boxes[str(frames[0])]
        require(isinstance(rects,list) and rects, "文字框 " + beat)
        worst = 0
        for frame in frames:
            require(boxes[str(frame)] == rects, f"文字框移动 {frame}")
            img = load(frame)
            for x,y,r,b in rects:
                require(all(type(n) is int for n in (x,y,r,b)) and
                        left <= x < r <= right and top <= y < b <= bottom, "文字框安全区")
                worst = max(worst,int(cv2.absdiff(base[y:b,x:r],img[y:b,x:r]).max()))
        require(worst <= visual["maxTextDelta"], "阅读窗 " + beat)
        reading[beat] = {"frames":frames,"maxSampleDelta":worst}
    seams = []
    for a,b in plan["seams"]:
        row = seam_record([a,b], load(a), load(b))
        require(seam_passes(row), f"非硬切交界 {a}/{b}: " + json.dumps(
            {key:row[key] for key in ("seam_delta","max_pixel_delta","changed_pixels")}))
        seams.append(row)
    return {"reading":reading,"seams":seams,"frames":plan["frames"]}


def decoded_metrics(movie, score, profile=None, overrides=()):
    profile = profile or load_profile()
    visual,video = profile.hard["visual"],profile.hard["video"]
    total = sample_plan(score,profile,overrides)["count"]
    hz = visual["motionHz"]
    stride = video["fps"] // hz
    roi = slice(*visual["roiY"])
    dark = score["lighting"] == "studio_dark"
    require(dark or score["lighting"] == "keynote_light","光场模式")
    cap = cv2.VideoCapture(str(movie))
    total_share = longest = run = full_run = longest_full = 0
    prev = None
    try:
        for frame in range(total):
            ok,img = cap.read()
            require(ok and img.shape == (video["height"],video["width"],3),f"成片解码 {frame}")
            gray = cv2.cvtColor(img,cv2.COLOR_BGR2GRAY)
            total_share += np.mean(gray < visual["darkBelow"] if dark else gray > visual["lightAbove"])
            if frame % stride == 0 and frame < total - video["fps"] * visual["endMarginSec"]:
                if prev is not None:
                    diff = cv2.absdiff(gray,prev)
                    run = run + 1 if diff[roi].mean() < visual["roiDelta"] else 0
                    full_run = full_run + 1 if diff.mean() < visual["fullDelta"] else 0
                    longest = max(longest, run)
                    longest_full = max(longest_full,full_run)
                prev = gray
        require(not cap.read()[0],"多余帧")
    finally:
        cap.release()
    pct = float(total_share * 100 / total)
    lo,hi = visual["lighting"][score["lighting"]]
    require(lo <= pct <= hi,"光场占比")
    require(longest/hz <= visual["maxStaticSec"],"ROI 静止窗")
    return {"lightPct":pct,"roiLongestSec":longest/hz,"fullLongestSec":longest_full/hz}


def av_checks(dec, mix, count, profile=None):
    profile = profile or load_profile()
    video,audio,limits = (profile.hard[k] for k in ("video","audio","decoder"))
    stream = dec["stream"]
    for key,value in {"fps":video["fps"],"width":video["width"],"height":video["height"],
                      "level":round(float(video["level"])*10),"profile":video["profile"].title(),
                      "pixFmt":video["pixFmt"],"codec":video["codec"],"nbFrames":count,"audioCodec":audio["codec"],
                      "audioChannels":audio["channels"],"audioSampleRate":audio["sampleRate"],"colorSpace":video["colorSpace"]}.items():
        require(stream[key] == value, key)
    require(dec["strict"] is True and dec["verdict"] == "PASS" and dec["passed"] is True,"硬解")
    stride = limits["sampleEvery"]
    expected = (count+stride-1)//stride
    require(dec["sampling"]["every"] == stride and dec["sampling"]["expectedFrames"] ==
            dec["sampling"]["framesCompared"] == expected,"抽样完整")
    for key,limit in (("maxFrameMAE","maxMae"),("maxSampleDelta","maxPeak"),
                      ("grayLeftHalfMaxPct","maxGrayPct"),("grayFullFrameMaxPct","maxGrayPct")):
        require(0 <= dec["comparison"][key] <= limits[limit],key)
    audit = dec["encodingAudit"]
    require(audit["warnings"] == [] and audit["auditedPackets"] == count and
            audit["sliceAudit"]["framesAudited"] == count and audit["sliceAudit"]["slicesPerFrameMax"] == limits["slicesPerFrame"],
            "码流全覆盖")
    require(mix["delivery_mode"] == "single_film_with_bgm","正式终混")
    for key,lo,hi in (("integrated_lufs",*audio["lufs"]),("exported_sfx_peak_dbfs",*audio["sfxPeak"]),
                      ("true_peak_dbtp",-math.inf,audio["truePeakMax"]),("climax_error_sec",0,audio["climaxErrorSec"])):
        value = mix[key]
        require(type(value) in (int,float) and math.isfinite(value) and lo <= value <= hi,key)
    gap = mix["bgm_gap_check"]
    require(gap["pass"] is True, "BGM 断层")
    if "profile_id" in mix:
        duration = mix["video_duration_sec"]
        require(abs(duration - count / video["fps"]) <= 0.001, "终混画面时长")
        # The report records durations to milliseconds.
        require(abs(mix["audio_duration_sec"] - duration) <= audio["avDurationToleranceSec"] + 0.001,
                "终混音画时长")
        require(gap["maxAllowedGapSec"] == audio["gapMaxSec"] and gap["bedPresent"] is True
                and gap["gapCount"] == 0 and gap["gaps"] == []
                and 0 <= gap["longestGapSec"] <= audio["gapMaxSec"], "BGM 铺底与断层明细")
        start, end = gap["window"]
        require(abs(start - audio["gapStartSec"]) <= 0.001 and
                abs(end - (duration - audio["gapEndMarginSec"])) <= 0.001, "BGM 检测覆盖")


def verification_policy(ep, report):
    if "profile_id" not in report and "profileArchive" not in report:
        # Earlier protocol has no archived profile. Only accept its original defaults.
        manifest = ep/"src/manifest.json"
        if manifest.exists():
            old = read(manifest)
            require(not (old.get("profile") or old.get("overrides")), "缺少档案绑定")
        return load_profile(), []
    run = report["profileArchive"]
    require(isinstance(run,str) and re.fullmatch("[0-9a-f]{32}",run),"归档 run ID")
    folder = within(ep,"src/production/"+run)
    profile = load_profile(report["profile_id"],archive=within(folder,"profile.json"),
                           expected=report["profile_sha256"])
    name = report.get("approvalFile","facts-approval.json")
    require(name in APPROVALS,"归档批准文件名")
    approval_path = within(folder,name)
    digest = report.get("approvalSha256",report.get("factsApprovalSha256"))
    approval_id = report.get("approvalId",report.get("factsApprovalId"))
    require(sha256_file(approval_path) == digest, "归档批准记录摘要")
    approval = read(approval_path)
    gate = approval.get("gate")
    require(approval.get("kind") == "approval" and gate in ("review","facts"),"内容批准记录")
    require(report.get("approvalGate",gate) == gate,"批准卡点与归档一致")
    require(approval["id"] == approval_id and
            approval["bindings"]["beats.json"] == sha256_file(ep/"beats.json") and
            all(approval["bindings"].get(k) == v for k,v in profile.stamp.items()),"批准版本")
    if gate == "facts":
        require(approval["bindings"]["facts_and_sources.md"] == sha256_file(ep/"facts_and_sources.md"),
                "事实文件与批准版本")
    manifest_path = within(ep,"src/manifest.json")
    if manifest_path.is_file():
        manifest = read(manifest_path)
        require(manifest.get("overrides",[]) == approval.get("acceptedOverrides",[])
                and manifest.get("profile",DEFAULT_PROFILE) == profile.data["id"],"交付清单与批准版本")
        if "manifest_content_sha256" in approval["bindings"]:
            require(approval["bindings"]["manifest_content_sha256"] == manifest_digest(manifest),
                    "交付清单摘要")
    require(approval.get("acceptedOverrides",[]) == report["applied_overrides"],"批准例外清单")
    return profile, report["applied_overrides"]


def verify(ep: Path):
    movie = within(ep,film_name(ep))
    score = read(ep/"beats.json")
    final = read(within(ep,"src/final_qc.json"))
    if (ep/"src/manifest.json").is_file():
        require(read(ep/"src/manifest.json").get("coreSnapshot") == final.get("coreSnapshot"), "快照版本")
    core_snapshot.verify(ep, final.get("coreSnapshot"))
    profile,requests = verification_policy(ep,final)
    plan = sample_plan(score,profile,requests)
    dec = read(within(ep,"src/decoder_check.json"))
    mix = read(within(ep,"bgm_mix_report.json"))
    digest = sha256_file(movie)
    require(dec["input"]["sha256"] == digest == mix["media_sha256"],"报告对应同一成片")
    timeline = sha256_file(ep/"beats.json")
    require(timeline == mix["timeline_sha256"] and score["alignClimaxSec"] == mix["aligned_climax_sec"],
            "终混时间轴")
    require(sha256_file(within(ep,"src/sfx_only.wav")) == mix["sfx_sha256"],"母带摘要")
    if "profile_id" in final or "profile_id" in dec or "profile_id" in mix:
        for item in (final,dec,mix):
            require(all(item.get(k) == v for k,v in profile.stamp.items()),"各阶段档案摘要")
    av_checks(dec,mix,plan["count"],profile)
    reading = read(within(ep,"src/reading_qc.json"))
    require(reading["timeline_sha256"] == timeline and reading["media_sha256"] == digest,"无损证据版本")
    require(reading["frames"] == plan["frames"] and set(reading["reading"]) == set(plan["reading"]),
            "定点覆盖")
    for beat,frames in plan["reading"].items():
        row = reading["reading"][beat]
        require(row["frames"] == frames and 0 <= row["maxSampleDelta"] <= profile.hard["visual"]["maxTextDelta"],"阅读窗 "+beat)
    require(len(reading["seams"]) == len(plan["seams"]),"接缝覆盖")
    pixels = profile.hard["video"]["width"] * profile.hard["video"]["height"]
    for row,pair in zip(reading["seams"],plan["seams"]):
        # A zero full-frame delta implies zero changed pixels, so pre-1.2.0
        # reports that stored only that field remain an exact, unrelaxed proof.
        require(seam_row_ok(row,pair,pixels),"接缝记录 " + str(pair))
    require(final["media_sha256"] == digest and final["timeline_sha256"] == timeline,"六项报告版本")
    require(final["streamAudit"]["faststart"] is True and final["streamAudit"]["videoStreamHash"].startswith("SHA256="),"编码实测")
    metrics = final["metrics"]
    lo, hi = profile.hard["visual"]["lighting"][score["lighting"]]
    require(lo <= metrics["lightPct"] <= hi and 0 <= metrics["roiLongestSec"] <= profile.hard["visual"]["maxStaticSec"],
            "实测光场与 ROI")
    require(final["layout"]["passed"] is True and final["layout"]["issues"] == []
            and bool(final["visualReview"].strip()),"版面与人工目视证据")
    for name in ("specEncoding","lighting","motionReading","layoutContact","facts","decoder"):
        require(final["checks"][name] is True,name)
    for name in ("facts_and_sources.md","cover.png","contact_sheet.png","src/reading_qc.json",
                 "bgm_mix_report.json","src/decoder_check.json"):
        path = within(ep,name)
        require(path.stat().st_size > 0 and final["evidence"][name] == sha256_file(path),name)
    allowed = {film_name(ep),"beats.json","src","facts_and_sources.md","cover.png","contact_sheet.png",
               "bgm_mix_report.json",".work"}
    require(not ({p.name for p in ep.iterdir()} - allowed),"交付根目录白名单")
    return {"passed":True,"media_sha256":digest,"frames":plan["count"]}


def audit_video_stream(movie, picture, profile=None):
    video = (profile or load_profile()).hard["video"]
    ffmpeg, _, _ = locate_tools()
    def stream_hash(path):
        return subprocess.check_output([ffmpeg,"-v","error","-i",str(path),"-map","0:v:0",
                "-c:v","copy","-f","hash","-hash","sha256","-"],timeout=180,text=True).strip()
    digest = stream_hash(movie)
    require(digest.startswith("SHA256=") and digest == stream_hash(picture),"混音前后视频流一致")
    packet = subprocess.check_output([ffmpeg,"-v","error","-i",str(movie),"-map","0:v:0",
            "-frames:v","1","-c:v","copy","-f","h264","-"],timeout=60)
    marker = re.search(rb"x264 - core[^\x00]+",packet)
    require(marker is not None,"x264 设置 SEI")
    settings = marker.group()
    for token in [f"crf={video['crf']:.1f}", f"keyint={video['gop']}", *video["presetEvidence"]]:
        require(token.encode() in settings.split(),token)
    require(all(k not in settings for k in (b"slice_max_mbs=",b"slice-max-mbs=",b" slices=")),
            "禁止显式切片")
    with movie.open("rb") as f:
        while True:
            head = f.read(8)
            require(len(head) == 8,"faststart MP4")
            size = int.from_bytes(head[:4],"big")
            header = 8
            if size == 1:
                size = int.from_bytes(f.read(8),"big")
                header = 16
            require(size >= header and head[4:] != b"mdat","faststart")
            if head[4:] == b"moov":
                break
            f.seek(size-header,1)
    return {"videoStreamHash":digest,"faststart":True,"x264":settings.decode("ascii","replace")}


def finish(ep, work, visual_note):
    """核验已完成的渲染候选，目录内最后提交 final_qc，再复验。"""
    require(work.parent == within(ep,".work") and re.fullmatch("[0-9a-f]{32}", work.name), "工作目录")
    candidate = within(work, Path("delivery") / ep.name)
    movie = within(candidate,film_name(ep))
    receipt = read(within(work,"receipt.json"))
    require(covers(receipt["approved"], bindings(ep,"review")), "渲染审批摘要")
    require(receipt["media"] == sha256_file(movie), "候选成片摘要")
    score = read(ep/"beats.json")
    manifest = read(within(ep,"src/manifest.json"))
    profile = load_profile(manifest.get("profile",DEFAULT_PROFILE))
    requests = manifest.get("overrides",[])
    approval = content_approval(ep,requests)
    approval_name = "content-approval.json" if approval.get("gate") == "review" else "facts-approval.json"
    require(all(receipt.get(k) == v for k,v in profile.stamp.items()),"候选档案")
    plan = sample_plan(score,profile,requests)
    for frame in plan["frames"]:
        require(receipt["frames"][str(frame)] == sha256_file(within(work,f"frame-{frame}.png")),
                f"帧来源 {frame}")
    layout = read(within(work,"layout.json"))
    require(layout["passed"] is True and layout["issues"] == [] and
            layout["picture_sha256"] == receipt["picture"], "单期 DOM 布局实测")
    require(sha256_file(within(work,"picture.mp4")) == receipt["picture"], "画面母版")
    source = within(candidate,"src")
    source.mkdir(exist_ok=True)
    reading = original_frames(work,score,layout["boxes"],profile,requests)
    timeline = sha256_file(ep/"beats.json")
    reading.update(media_sha256=receipt["media"],timeline_sha256=timeline)
    (source/"reading_qc.json").write_text(json.dumps(reading,indent=2),"utf-8")
    metrics = decoded_metrics(movie,score,profile,requests)
    stream_audit = audit_video_stream(movie,work/"picture.mp4",profile)
    subprocess.run([sys.executable,"-B",str(ROOT/"tools/decoder_check.py"),"--strict","--quiet","--profile",profile.data["id"],
                    "--video",str(movie),"--output",str(source/"decoder_check.json")],check=True,
                   stdout=subprocess.DEVNULL)
    for name in ("facts_and_sources.md","beats.json"):
        shutil.copyfile(within(ep,name),within(candidate,name))
    for name in ("cover.png","contact_sheet.png"):
        src = within(work,name)
        require(cv2.imdecode(np.fromfile(src,np.uint8),cv2.IMREAD_COLOR) is not None,name)
        shutil.copyfile(src,within(candidate,name))
    # The durable reports refer to the retained files after the candidate directory retires.
    mix = read(candidate/"bgm_mix_report.json")
    mix.update(output_path=film_name(ep), sfx_only_wav="src/sfx_only.wav")
    for key in ("bgm_file","beats_file","sfx_source"):
        if mix.get(key) and Path(mix[key]).is_absolute():
            mix[key] = os.path.relpath(mix[key],ep)
    (candidate/"bgm_mix_report.json").write_text(json.dumps(mix,ensure_ascii=False,indent=2),"utf-8")
    decoder = read(source/"decoder_check.json")
    decoder["input"]["path"] = "../" + film_name(ep)
    (source/"decoder_check.json").write_text(json.dumps(decoder,ensure_ascii=False,indent=2),"utf-8")
    evidence_names = ["facts_and_sources.md","cover.png","contact_sheet.png","src/reading_qc.json",
                      "bgm_mix_report.json","src/decoder_check.json"]
    evidence = {name:sha256_file(within(candidate,name)) for name in evidence_names}
    archive_rel = "src/production/" + work.name
    staging = within(candidate,archive_rel)
    staging.mkdir(parents=True,exist_ok=True)
    (staging/"profile.json").write_bytes(profile.raw)
    (staging/approval_name).write_text(json.dumps(approval,ensure_ascii=False),"utf-8")
    report = {**profile.stamp,"profileArchive":work.name,"approvalId":approval["id"],
              "approvalGate":approval.get("gate","review"),"approvalFile":approval_name,
              "approvalSha256":sha256_file(staging/approval_name),
              "applied_overrides":requests,"media_sha256":receipt["media"],"timeline_sha256":timeline,"metrics":metrics,
              "layout":{k:v for k,v in layout.items() if k != "boxes"},"visualReview":visual_note,
              "streamAudit":stream_audit,"encoder":read(work/"encoder.json"),"evidence":evidence,
              "checks":dict.fromkeys(("specEncoding","lighting","motionReading","layoutContact","facts","decoder"),True)}
    if manifest.get("coreSnapshot"):
        core_snapshot.verify(ep, manifest["coreSnapshot"])
        shutil.copytree(core_snapshot.folder(ep), core_snapshot.folder(candidate), dirs_exist_ok=True)
        report["coreSnapshot"] = manifest["coreSnapshot"]
    (source/"final_qc.json").write_text(json.dumps(report,indent=2,ensure_ascii=False),"utf-8")
    verify(candidate)
    require(covers(receipt["approved"], bindings(ep,"review")),"核验期间输入发生变化")
    archive = within(ep,"src/production") / work.name
    archive.mkdir(parents=True,exist_ok=True)
    for filename in ("render-plan.json","receipt.json","encoder.json","layout.json"):
        shutil.copyfile(work/filename, archive/filename)
    for filename in ("episode.py","delivery_check.py","render_episode.cjs","check_entry.cjs","decoder_check.py",
                     "bgm_common.py","bgm_analyze.py","mix_bgm.py","profile_loader.py","core_snapshot.py",
                     "evidence_kit.py","collect_evidence.cjs","env.example.json"):
        shutil.copyfile(ROOT/"tools"/filename,archive/filename)
    shutil.copytree(ROOT/"tools/profiles",archive/"profiles",dirs_exist_ok=True)
    shutil.copytree(ROOT/"tools/contracts",archive/"contracts",dirs_exist_ok=True)
    for name in ("AGENTS.md","STYLE_B_SILENT_VIBE.md"):
        shutil.copyfile(ROOT/"docs"/name,archive/name)
    for name in ("README.md","package.json","package-lock.json"):
        if (ROOT/name).is_file():
            shutil.copyfile(ROOT/name,archive/name)
    # Each file is replaced atomically. The final report commits the set; verify
    # rejects any partial generation after interruption. Retry from retained work.
    for name in (archive_rel+"/profile.json",archive_rel+"/"+approval_name,film_name(ep),"cover.png","contact_sheet.png","bgm_mix_report.json","src/sfx_only.wav",
                 "src/decoder_check.json","src/reading_qc.json","src/final_qc.json"):
        dest = within(ep,name)
        with tempfile.NamedTemporaryFile(dir=dest.parent,delete=False) as out:
            with within(candidate,name).open("rb") as inp:
                shutil.copyfileobj(inp,out)
        os.replace(out.name,dest)
    result = verify(ep)
    # Only remove the verified run. Other concurrent or failed runs stay available.
    remove_tree(ep, work)
    preview_receipt = within(ep,"src/review/receipt.json")
    preview = read(preview_receipt) if preview_receipt.is_file() else {}
    if re.fullmatch("[0-9a-f]{32}", preview.get("run") or ""):
        previous = within(ep,".work/"+preview["run"])
        if previous.is_dir() and read(within(previous,"receipt.json")) == preview:
            remove_tree(ep, previous)
    if work.parent.is_dir() and not any(work.parent.iterdir()):
        work.parent.rmdir()
    return result
