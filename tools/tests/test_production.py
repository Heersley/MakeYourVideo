"""Regression fixtures are created in a temporary directory. No video is rendered."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import episode
import delivery_check as qc
import decoder_check as decoder
import mix_bgm


def score():
    return {"track":"evergreen_vibe","cut_mode":"cinema","duration_tier":"standard","lighting":"studio_dark",
            "asset_layers":["vector"],"fps":60,"totalSec":75,"alignClimaxSec":55,
            "beats":[{"id":i+1,"startSec":5*i,"endSec":5*i+5,"durationSec":5,
                      "readingStartSec":5*i+2,"readingEndSec":5*i+3,"lines":["阅读窗测试"],
                      "hardCut":False} for i in range(15)],
            "effects":[{"type":"tick","timeSec":i*5} for i in range(10)]}


def av_reports(count=120):
    dec = {"stream":{"fps":60,"width":1440,"height":2560,"level":51,"profile":"High",
           "pixFmt":"yuv420p","codec":"h264","nbFrames":count,"audioCodec":"aac",
           "audioChannels":2,"audioSampleRate":48000,"colorSpace":"bt709"},
           "strict":True,"verdict":"PASS","passed":True,
           "sampling":{"every":6,"expectedFrames":(count+5)//6,"framesCompared":(count+5)//6},
           "comparison":dict.fromkeys(["maxFrameMAE","maxSampleDelta","grayLeftHalfMaxPct",
                                       "grayFullFrameMaxPct"],0),
           "encodingAudit":{"warnings":[],"auditedPackets":count,
                            "sliceAudit":{"framesAudited":count,"slicesPerFrameMax":1}}}
    mix = {"delivery_mode":"single_film_with_bgm","integrated_lufs":-16,"exported_sfx_peak_dbfs":-13,
           "true_peak_dbtp":-1.1,"climax_error_sec":.01,"bgm_gap_check":{"pass":True}}
    return dec, mix


class ProductionTests(unittest.TestCase):
    def test_sampling_and_bad_inputs(self):
        data = score()
        plan = episode.sample_plan(data)
        self.assertEqual(plan["reading"]["1"],[120,149,179])
        self.assertIn([299,300],plan["seams"])
        self.assertEqual(len(plan["frames"]),73)
        for key,value in (("readingEndSec",7),("durationSec",4.9),("startSec",.01),("hardCut","false")):
            with self.subTest(key=key), self.assertRaises(ValueError):
                bad = copy.deepcopy(data)
                bad["beats"][0][key] = value
                episode.sample_plan(bad)

    def test_codec_profile(self):
        for fps,profile,level,expected in ((60,"High",51,True),(59.94,"High",51,False),
                                           (60,"High 10",51,False),(60,"High",42,False)):
            actual = decoder.codec_conformance({"level":level,"profile":profile},1440,2560,fps)
            self.assertEqual(actual["compliant"],expected)

    def test_fail_closed_av(self):
        dec, mix = av_reports()
        qc.av_checks(dec,mix,120)
        for key,value in (("integrated_lufs",-22.8),("exported_sfx_peak_dbfs",-240),
                          ("true_peak_dbtp",-.99),("climax_error_sec",None),("bgm_gap_check",{})):
            with self.subTest(key=key), self.assertRaises((ValueError,KeyError)):
                qc.av_checks(dec,{**mix,key:value},120)
        dec["comparison"]["maxSampleDelta"] = 1
        with self.assertRaises(ValueError):
            qc.av_checks(dec,mix,120)

    def test_original_png_missing_and_changed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            img = np.zeros((2560,1440,3),np.uint8)
            enc = cv2.imencode(".png",img)[1].tobytes()
            plan = {"reading":{"B1":[1,2,3]},"seams":[[3,4]],"frames":[1,2,3,4]}
            boxes = {str(n):[[120,240,220,290]] for n in (1,2,3)}
            with patch.object(qc,"sample_plan",return_value=plan):
                for n in range(1,4):
                    (root/f"frame-{n}.png").write_bytes(enc)
                with self.assertRaises(FileNotFoundError):
                    qc.original_frames(root,{},boxes)
                (root/"frame-4.png").write_bytes(enc)
                qc.original_frames(root,{},boxes)
                img[250,150] = 1
                (root/"frame-2.png").write_bytes(cv2.imencode(".png",img)[1].tobytes())
                with self.assertRaises(ValueError):
                    qc.original_frames(root,{},boxes)

    def test_handoff_process_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            ep = Path(tmp)/"2026-11-22/04_fixture"
            (ep/"src").mkdir(parents=True)
            (ep/"src/manifest.json").write_text("{}")
            # Only substitute the test track. Execute the real CLI in fresh processes.
            boot = ("import sys;from pathlib import Path;sys.path.insert(0,sys.argv.pop(1));"
                    "import episode;episode.TRACK=Path(sys.argv.pop(1));"
                    "import json;print(json.dumps(episode.run()))")
            def invoke(*args):
                cmd = [sys.executable,"-B","-c",boot,str(TOOLS),tmp,args[0],str(ep),*args[1:]]
                return json.loads(subprocess.check_output(cmd,text=True))
            item = invoke("handoff","--owner","Render","--note","Slow the exit","--scope","B12",
                          "--protect","SFX and B11/B13")
            status = invoke("status")
            self.assertEqual(status["pending"],[item["id"]])
            self.assertEqual(status["history"][0]["scope"],"B12")
            (ep/"evidence.txt").write_text("fixture")
            invoke("resolve","--request",item["id"],"--evidence","evidence.txt","--note","checked")
            self.assertEqual(invoke("status")["pending"],[])

    def test_legacy_topic_facts_history_is_inert(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ep = root/"04_fixture"
            (ep/"src/assets").mkdir(parents=True)
            (ep/"src/entry.tsx").write_text("// fixture")
            (ep/"src/sfx.wav").write_bytes(b"RIFF")
            (ep/"beats.json").write_text(json.dumps(score()))
            (ep/"src/manifest.json").write_text(json.dumps({"version":1,"topic":"card.md",
                "entry":"entry.tsx","previewComposition":"Review","fullComposition":"Full",
                "previewFrames":900,"sfx":"src/sfx.wav"}))
            # 旧单期写入的 topic/facts 审批只作为历史保留：既不阻断，也不再被要求。
            episode.record(ep,{"kind":"approval","gate":"topic","bindings":{}})
            episode.record(ep,{"kind":"approval","gate":"facts","acceptedOverrides":[],"bindings":{}})
            self.assertEqual(episode.state(ep)["nextGate"],"review")
            self.assertEqual(episode.state(ep)["approved"],{})
            self.assertFalse((root/"inbox/evergreen_vibe/card.md").exists())
            self.assertEqual(episode.plan(ep,"full")["applied_overrides"],[])

    def test_failed_mix_preserves_previous_files(self):
        # Replace the media I/O only. Run the normal CLI through mixing, loudness
        # measurement, PCM export and publication paths without producing a movie.
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            root = Path(tmp)
            video = root/"input.mp4"
            audio = root/"track.wav"
            master = root/"sfx.wav"
            beats = root/"beats.json"
            for item in (video,audio,master):
                item.write_bytes(b"mock input")
            beats.write_text(json.dumps({"alignClimaxSec":2,"beats":[]}))
            dest = root/"final.mp4"
            stem = root/"sfx_only.wav"
            report = root/"bgm_mix_report.json"
            for item in (dest,stem,report):
                item.write_bytes(b"previous generation")
            wave = np.full((5*mix_bgm.SR,2),.2,dtype=np.float32)
            for name,value in (("locate_tools",("ff","probe","9.0.2")),
                               ("ensure_beats",({"source_sha256":"fixture","bpm":120,
                                                "bar_sec":2,"drops":[{"t":2}]},audio.with_suffix(".json"))),
                               ("decode_f32",wave),("probe_duration",5.0)):
                stack.enter_context(patch.object(mix_bgm,name,return_value=value))
            stack.enter_context(patch.object(mix_bgm,"mux",side_effect=lambda f,v,raw,out,*args:
                                             out.write_bytes(b"mock candidate")))
            measure = stack.enter_context(patch.object(mix_bgm,"measure_loudness",
                                                      return_value=(-22.8,-2,"fixture")))
            args = ["--video",str(video),"--bgm",str(audio),"--license-note","fixture",
                    "--beats",str(beats),"--sfx",str(master),"--sfx-out",str(stem),"--sfx-channels","2",
                    "--out",str(dest)]
            with self.assertRaisesRegex(SystemExit,"integrated_lufs"):
                mix_bgm.main(args)
            for item in (dest,stem,report):
                self.assertEqual(item.read_bytes(),b"previous generation")
            measure.return_value = (-16,-2,"fixture")
            self.assertEqual(mix_bgm.main(args),0)
            actual = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(actual["media_sha256"],episode.sha256_file(dest))
            self.assertEqual(actual["sfx_sha256"],episode.sha256_file(stem))

    def test_plan_excludes_legacy_and_supplies_same_score(self):
        with tempfile.TemporaryDirectory() as tmp:
            ep = Path(tmp)
            (ep/"src/assets").mkdir(parents=True)
            (ep/"src/entry.tsx").write_text("// fixture")
            data = score()
            (ep/"beats.json").write_text(json.dumps(data))
            manifest = {"version":1,"topic":"card.md","entry":"entry.tsx","fullComposition":"Full",
                        "previewComposition":"Review","previewFrames":900,"sfx":"src/stem.wav"}
            path = ep/"src/manifest.json"
            path.write_text(json.dumps(manifest))
            plan = episode.plan(ep,"full")
            self.assertEqual(plan["timeline"],plan["inputProps"]["samplePlan"])
            self.assertEqual((plan["width"],plan["height"],plan["fps"],plan["frames"]),(1440,2560,60,4500))
            for key,value in (("sequence",True),("width",1080),("concurrency",0),("entry","../../escape")):
                path.write_text(json.dumps({**manifest,key:value}))
                with self.assertRaises(ValueError):
                    episode.plan(ep,"full")

    def test_actual_mono_master_peak(self):
        with tempfile.TemporaryDirectory() as tmp:
            stereo = np.tile(np.float32([.2,-.2]),(4800,1))
            value = mix_bgm.write_wav_16(Path(tmp)/"stem.wav",stereo,32000,1)
            self.assertLess(value,-100)

    def test_negative_offset_and_preview_preroll(self):
        loop = np.tile(np.linspace(.05,.2,4*mix_bgm.SR,dtype=np.float32)[:,None],(1,2))
        track = mix_bgm.build_bgm_track(loop,100,-13)
        np.testing.assert_array_equal(track,loop[13:113])
        track = mix_bgm.build_bgm_track(loop,3*mix_bgm.SR,9*mix_bgm.SR)
        info = mix_bgm.fill_preroll(track,loop,9*mix_bgm.SR,mix_bgm.SR,-15)
        self.assertTrue(info["enabled"])
        self.assertTrue(np.all(track[mix_bgm.SR:2*mix_bgm.SR] != 0))


if __name__ == "__main__":
    unittest.main()
