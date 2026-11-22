#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本机零联网工具箱：浏览器打开 http://127.0.0.1:8765 即用（只依赖标准库）。

只绑定回环地址 127.0.0.1，局域网和公网访问不到；不调用模型、不联网、不落盘，脱敏映射表按页面会话
保存在本进程内存里，关闭即销毁。涉密检测、脱敏还原、八关机检、事实数字核对、字体自检、国标排版
（无 python-docx 时自动切换纯标准库轻量排版）、OFD 体检和内网提示词复制都由人逐步点击，
没有后台自动执行。

用法：python3 xinchuang/local_toolbox.py [--port 8765] [--auto-port]
退出：在终端按 Ctrl+C 或关闭启动窗口
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import sys
import tempfile
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
# 仓库和离线包里都有 skills/gongwen-review/scripts（共享脚本的同步副本），从那里取脚本
sys.path.insert(0, str(ROOT / "skills" / "gongwen-review" / "scripts"))
sys.path.append(str(ROOT / "skills" / "gongwen-format" / "scripts"))
sys.path.append(str(Path(__file__).resolve().parent))

import desensitize  # noqa: E402
import fact_diff  # noqa: E402
import gongwen_lint  # noqa: E402
import gw_fonts  # noqa: E402
import lite_docx  # noqa: E402
import ofd_check  # noqa: E402

HOST = "127.0.0.1"
MAX_BODY = 20 * 1024 * 1024  # 20 MB，容纳带嵌入字体的 .docx / .ofd
MAX_SESSIONS = 32
DEFAULT_SID = "__default__"
# 保留 STATE['map'] 兼容单测直接读写；浏览器多标签页按 sid 隔离，互不覆盖
STATE: Dict[str, object] = {"map": {}, "sessions": OrderedDict()}
NL = chr(10)

PROMPT_GROUPS: Tuple[Tuple[str, str, str], ...] = (
    ("bundles", "dist/prompts-bundles", "一站式单对话合集（推荐，内网不切对话）"),
    ("lite", "dist/prompts-lite", "单技能精简版（<=4000字，适合字数受限平台）"),
)

PAGE = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>公文写作本机工具箱（零联网）</title>
<style>
*{box-sizing:border-box}
body{font:15px/1.6 "Microsoft YaHei","Noto Sans CJK SC",sans-serif;max-width:1180px;margin:1em auto;padding:0 1em;color:#222;background:#fafafa}
h2{margin:.2em 0 .5em;font-size:20px}
.warn{background:#fff3cd;border-left:4px solid #d39e00;padding:.55em .8em;margin:.5em 0 1em;font-size:14px}
.card{background:#fff;border:1px solid #ddd;border-radius:4px;padding:.75em .9em;margin-bottom:.85em}
.card h3{margin:0 0 .5em;font-size:15px;color:#1b4f72}
.row{display:flex;gap:1em;flex-wrap:wrap}.row>div{flex:1;min-width:300px}
textarea{width:100%;height:230px;padding:.5em;font:14px/1.55 sans-serif;border:1px solid #ccc;border-radius:3px}
pre{background:#f4f4f4;border:1px solid #e2e2e2;padding:.7em;white-space:pre-wrap;word-break:break-word;min-height:4.5em;max-height:360px;overflow:auto;font:13.5px/1.55 monospace}
button{padding:.38em .75em;margin:.2em .25em .2em 0;cursor:pointer;border:1px solid #8aa4b8;background:#f0f6fa;color:#123;border-radius:3px;font-size:14px}
button:hover{background:#dfeef8}
button.primary{background:#1b4f72;color:#fff;border-color:#1b4f72}
button.primary:hover{background:#153e59}
button.danger{background:#fff5f5;color:#a00;border-color:#d8a}
input,select{padding:.3em .45em;border:1px solid #ccc;border-radius:3px;font-size:14px}
.bar{display:flex;flex-wrap:wrap;align-items:center;gap:.5em;margin:.35em 0}
.muted{color:#666;font-size:13px}
.bad{color:#b00020;background:#fff5f5;border-color:#e5b3b3}
.filebtn{display:inline-block;padding:.22em .6em;border:1px dashed #6a8fa8;border-radius:3px;background:#f7fbfe;cursor:pointer;font-size:13px}
.filebtn input{display:none}
</style></head><body>
<h2>公文写作本机工具箱 <span class="muted">（仅监听 127.0.0.1 · 零联网 · 非自主智能体）</span></h2>
<div class="warn"><strong>保密红线：</strong>本工具箱不联网、不调用大模型、不落盘保存正文，脱敏映射表只留在本页内存，关闭窗口即销毁。<strong>涉密材料严禁进入任何非涉密系统</strong>，脱敏不能使涉密材料合规外发。</div>

<div class="card">
  <h3>第一步：选用内网大模型提示词（一键复制，粘贴到单位内网模型系统提示词框）</h3>
  <div class="bar">
    <select id="promptSel" style="min-width:340px"><option value="">正在加载提示词清单...</option></select>
    <button id="cpPrompt" class="primary">复制所选提示词</button>
    <span id="promptInfo" class="muted"></span>
  </div>
</div>

<div class="card">
  <h3>第二步：导入或粘贴材料 → 涉密检查 / 脱敏 → 粘贴大模型改稿 → 还原与核稿</h3>
  <div class="row">
    <div>
      <div class="bar">
        <b>左框：原稿 / 素材</b>
        <label class="filebtn">导入 .docx/.txt/.md<input type="file" id="fileA" accept=".docx,.txt,.md"></label>
        <button id="clrA" type="button">清空</button>
      </div>
      <textarea id="a" placeholder="粘贴原稿或素材，或点上方导入 Word（.docx）文件..."></textarea>
      <div id="hfA" class="muted"></div>
    </div>
    <div>
      <div class="bar">
        <b>右框：模型改稿 / 待检成稿</b>
        <label class="filebtn">导入 .docx/.txt/.md<input type="file" id="fileB" accept=".docx,.txt,.md"></label>
        <button id="clrB" type="button">清空</button>
      </div>
      <textarea id="b" placeholder="把内网大模型返回的改稿粘贴到这里，或导入待核稿的 .docx..."></textarea>
      <div id="hfB" class="muted"></div>
    </div>
  </div>
  <div class="bar" style="margin-top:.55em">
    <label>额外脱敏词（人名/单位名，逗号或顿号分隔）：<input id="terms" size="30" placeholder="如：张三、某区财政局"></label>
    <label>文书类型（可空）：<input id="dt" size="8" placeholder="如：通知"></label>
    <label>单位字体预设：
      <select id="uf">
        <option value="">国标默认（仿宋_GB2312等）</option>
        <option value="preset:fangzheng-gbk">方正 GBK 字体族（单位制度规定时）</option>
        <option value="preset:fangzheng-gbk-stdsong">方正 GBK + 标准宋体页码</option>
      </select>
    </label>
  </div>
  <div class="bar">
    <button data-op="secret">① 涉密检测（左框）</button>
    <button data-op="mask" class="primary">② 脱敏（左框）</button>
    <button id="cp">复制结果（附保留占位符提示）</button>
    <button id="cpRaw">仅复制结果正文</button>
    <button data-op="restore" class="primary">③ 还原（右框写回）</button>
    <button data-op="show_map">查看本页映射表</button>
    <button data-op="clear_map" class="danger">清空本页映射表</button>
  </div>
  <div class="bar">
    <button data-op="lint">④ 八关机检（右框）</button>
    <button data-op="factdiff">⑤ 事实数字核对（左对右）</button>
    <button data-op="fonts">⑥ 本机字体自检</button>
    <button data-op="format" class="primary">⑦ 国标排版（右框下载 .docx）</button>
    <label class="filebtn">⑧ OFD 结构体检（选择 .ofd 文件）<input type="file" id="fileOfd" accept=".ofd"></label>
  </div>
</div>

<div class="card">
  <h3>运行结果</h3>
  <p id="note" class="muted" style="margin:.2em 0 .4em"></p>
  <pre id="out">就绪。所有操作仅在本机完成，可随时关闭此页面。</pre>
</div>

<script>
var $=function(i){return document.getElementById(i)};
var SID=(typeof crypto!=='undefined'&&crypto.randomUUID)?crypto.randomUUID():('s'+Date.now()+Math.random().toString(16).slice(2));
var HF={a:'',b:''};
var LAST_OP='';

function showResult(r){
  $('note').textContent=r.note||'';
  $('out').textContent=r.text||'';
  $('out').className=r.ok?'':'bad';
}
function postJson(url,payload){
  payload.sid=SID;
  return fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)})
    .then(function(r){return r.json();});
}
function readAsBase64(file,cb){
  var rd=new FileReader();
  rd.onload=function(){
    var u=new Uint8Array(rd.result),s='',chunk=0x8000;
    for(var i=0;i<u.length;i+=chunk){s+=String.fromCharCode.apply(null,u.subarray(i,i+chunk));}
    cb(btoa(s));
  };
  rd.readAsArrayBuffer(file);
}
function copyText(txt,okMsg){
  if(!txt){$('note').textContent='当前没有可复制的内容。';return;}
  if(navigator.clipboard&&navigator.clipboard.writeText){
    navigator.clipboard.writeText(txt).then(function(){$('note').textContent=okMsg;})
      .catch(function(){fallbackCopy(txt,okMsg);});
  }else{fallbackCopy(txt,okMsg);}
}
function fallbackCopy(txt,okMsg){
  var ta=document.createElement('textarea');ta.value=txt;document.body.appendChild(ta);ta.select();
  try{document.execCommand('copy');$('note').textContent=okMsg;}catch(e){$('note').textContent='浏览器阻止自动复制，请手动全选复制。';}
  ta.remove();
}

// 加载提示词清单
fetch('/api/prompts').then(function(r){return r.json();}).then(function(r){
  var sel=$('promptSel'); sel.innerHTML='';
  if(!r.ok||!r.items||!r.items.length){
    var o=document.createElement('option');o.value='';o.textContent='未找到 dist/prompts-lite 或 dist/prompts-bundles';sel.appendChild(o);return;
  }
  r.items.forEach(function(it){
    var o=document.createElement('option');
    o.value=it.id;
    o.textContent='['+it.group_label+'] '+it.title+'（'+it.chars+'字）';
    sel.appendChild(o);
  });
  $('promptInfo').textContent='共 '+r.items.length+' 份（不含 Agent 路径与脚本命令）';
}).catch(function(){$('promptInfo').textContent='提示词清单加载失败';});

$('cpPrompt').onclick=function(){
  var id=$('promptSel').value;
  if(!id){$('note').textContent='请先选择一份提示词。';return;}
  postJson('/api/prompt_text',{id:id}).then(function(r){
    if(!r.ok){showResult(r);return;}
    copyText(r.text,'已复制提示词：'+r.title+'（'+r.chars+' 字），可直接粘贴到内网大模型系统提示词框。');
  }).catch(function(e){showResult({ok:false,text:'读取失败：'+e});});
};

// 按钮操作
document.querySelectorAll('button[data-op]').forEach(function(btn){
  btn.onclick=function(){
    var op=btn.dataset.op; LAST_OP=op;
    postJson('/api/'+op,{
      a:$('a').value, b:$('b').value, hf_a:HF.a, hf_b:HF.b,
      terms:$('terms').value, doc_type:$('dt').value, unit_fonts:$('uf').value
    }).then(function(r){
      showResult(r);
      if(op==='restore'&&r.ok){$('b').value=r.text;}
      if(r.docx){
        var bin=atob(r.docx),u=new Uint8Array(bin.length);
        for(var i=0;i<bin.length;i++){u[i]=bin.charCodeAt(i);}
        var a=document.createElement('a');a.href=URL.createObjectURL(new Blob([u]));
        a.download='成稿.docx';document.body.appendChild(a);a.click();a.remove();
      }
    }).catch(function(e){showResult({ok:false,text:'请求失败：'+e});});
  };
});

$('cp').onclick=function(){
  var txt=$('out').textContent;
  if(LAST_OP==='mask'&&txt){
    txt+='\\n\\n【请按公文规范处理上述脱敏材料，文中【自定义词1】【手机号1】等方括号占位符请原样保留，不要改写、合并或删除。】';
    copyText(txt,'已复制脱敏稿并附带“原样保留占位符”提示，可直接粘贴给内网模型。');
  }else{
    copyText(txt,'已复制结果到剪贴板。');
  }
};
$('cpRaw').onclick=function(){copyText($('out').textContent,'已复制结果正文到剪贴板。');};
$('clrA').onclick=function(){$('a').value='';HF.a='';$('hfA').textContent='';};
$('clrB').onclick=function(){$('b').value='';HF.b='';$('hfB').textContent='';};

function bindImport(inputId,targetId,hfKey,hfLabelId){
  $(inputId).onchange=function(ev){
    var f=ev.target.files&&ev.target.files[0]; if(!f) return;
    ev.target.value='';
    if(/\\.docx$/i.test(f.name)){
      readAsBase64(f,function(b64){
        postJson('/api/extract_docx',{filename:f.name,data_b64:b64}).then(function(r){
          if(!r.ok){showResult(r);return;}
          $(targetId).value=r.text;
          HF[hfKey]=r.headers_footers||'';
          $(hfLabelId).textContent=r.hf_note||'已导入 '+f.name;
          showResult({ok:!r.secret_warn,text:r.summary,note:r.note});
        }).catch(function(e){showResult({ok:false,text:'导入失败：'+e});});
      });
    }else{
      var rd=new FileReader();
      rd.onload=function(){
        $(targetId).value=rd.result||'';
        HF[hfKey]='';
        $(hfLabelId).textContent='已导入纯文本：'+f.name;
      };
      rd.readAsText(f,'utf-8');
    }
  };
}
bindImport('fileA','a','a','hfA');
bindImport('fileB','b','b','hfB');

$('fileOfd').onchange=function(ev){
  var f=ev.target.files&&ev.target.files[0]; if(!f) return;
  ev.target.value='';
  readAsBase64(f,function(b64){
    postJson('/api/ofd',{filename:f.name,data_b64:b64}).then(function(r){
      showResult(r);
    }).catch(function(e){showResult({ok:false,text:'OFD 体检失败：'+e});});
  });
};
</script></body></html>
"""


def _sid(d: dict) -> str:
    raw = str(d.get("sid") or "").strip()
    return raw if raw else DEFAULT_SID


def _get_map(sid: str) -> Dict[str, str]:
    if sid == DEFAULT_SID:
        return STATE["map"]  # type: ignore[return-value]
    sessions: OrderedDict = STATE["sessions"]  # type: ignore[assignment]
    return sessions.get(sid, {})


def _set_map(sid: str, mapping: Dict[str, str]) -> None:
    if sid == DEFAULT_SID:
        STATE["map"] = mapping
        return
    sessions: OrderedDict = STATE["sessions"]  # type: ignore[assignment]
    sessions[sid] = mapping
    sessions.move_to_end(sid)
    while len(sessions) > MAX_SESSIONS:
        sessions.popitem(last=False)


def op_secret(d: dict) -> dict:
    parts = [d.get("a", "")]
    if d.get("hf_a"):
        parts.insert(0, str(d["hf_a"]))
    hits = desensitize.check_secret_text(NL.join(p for p in parts if p))
    if not hits:
        return {"ok": True, "text": "未发现保密标识（含已导入文件的页眉页脚）。机检只认标识字样，材料是否涉密仍由你判断。"}
    lines = ["[%s] %s：%s" % hit for hit in hits[:20]]
    return {"ok": False, "text": "发现保密标识，请立即停止处理：" + NL + NL.join(lines)}


def op_mask(d: dict) -> dict:
    sid = _sid(d)
    if d.get("hf_a"):
        hf_hits = desensitize.check_secret_text(str(d["hf_a"]))
        if hf_hits:
            return {"ok": False, "text": "[强拦截] 导入文件的页眉/页脚命中保密标识，已禁止脱敏外发。"}
    try:
        res = desensitize.mask_text(d.get("a", ""), desensitize.parse_custom_terms(d.get("terms", "")))
    except desensitize.SecretBlockedError as exc:
        return {"ok": False, "text": "[强拦截] %s" % exc}
    _set_map(sid, res.mapping)
    return {
        "ok": True,
        "text": res.masked_text,
        "note": "已替换 %d 项；映射表只在本页内存里（多窗口隔离），关闭窗口即销毁。" % len(res.mapping),
    }


def op_restore(d: dict) -> dict:
    mapping = _get_map(_sid(d))
    if not mapping:
        return {"ok": False, "text": "本页面还没有映射表：请先在同一页面里执行脱敏。"}
    res = desensitize.restore_text(d.get("b", ""), mapping)
    note = "已还原 %d 处" % res.restored_count
    if res.missing_tokens:
        note += "；改稿里找不到这些占位符（可能被模型改写或删除）：" + "、".join(res.missing_tokens)
    return {"ok": True, "text": res.restored_text, "note": note}


def op_show_map(d: dict) -> dict:
    mapping = _get_map(_sid(d))
    if not mapping:
        return {"ok": True, "text": "本页面当前没有脱敏映射记录。", "note": "映射表为空"}
    lines = [f"{k}  ->  {v}" for k, v in mapping.items()]
    return {"ok": True, "text": NL.join(lines), "note": f"当前本页内存共有 {len(mapping)} 条映射（切勿截图外传）"}


def op_clear_map(d: dict) -> dict:
    _set_map(_sid(d), {})
    return {"ok": True, "text": "已清空本页面的脱敏映射表。", "note": "映射表已清空"}


def op_lint(d: dict) -> dict:
    result = gongwen_lint.lint_text(d.get("b", ""), doc_type=d.get("doc_type") or None)
    return {"ok": True, "text": gongwen_lint.render_text(result)}


def op_factdiff(d: dict) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        a, b = Path(tmp) / "原稿.txt", Path(tmp) / "改稿.txt"
        a.write_text(d.get("a", ""), encoding="utf-8")
        b.write_text(d.get("b", ""), encoding="utf-8")
        report = fact_diff.build_report(a, b, ledger=False, refs=[])
    return {"ok": report["consistent"], "text": fact_diff.render_text(report)}


def op_fonts(d: dict) -> dict:
    params = gw_fonts.load_params()
    uf = str(d.get("unit_fonts") or "").strip()
    if uf:
        try:
            params = gw_fonts.apply_unit_fonts(params, gw_fonts.parse_unit_fonts(uf, params))
        except ValueError as exc:
            return {"ok": False, "text": f"字体预设无效：{exc}"}
    installed, method = gw_fonts.installed_fonts()
    _fonts, check = gw_fonts.resolve_fonts(params, installed, method)
    lines = [gw_fonts.status_line(check, "下方")]
    notice = gw_fonts.render_notice(check)
    if notice:
        lines += ["", notice]
    return {"ok": check["font_status"] == "complete", "text": NL.join(lines)}


def body_lines(text: str) -> List[str]:
    """右框正文按行切开，遇到【起草说明】分界行停止，口径与排版脚本读文件一致。"""
    from gw_layout import is_draft_note_line

    lines: List[str] = []
    for line in text.splitlines():
        if is_draft_note_line(line):
            break
        lines.append(line)
    return lines


def _format_via_lite(lines: List[str], unit_fonts: str, reason: str) -> dict:
    try:
        raw, report = lite_docx.build_lite_docx(lines, unit_fonts=unit_fonts or None)
    except ValueError as exc:
        return {"ok": False, "text": f"轻量排版失败：{exc}"}
    note = f"{reason}，已自动改用工具箱内置零依赖轻量排版（不依赖 python-docx/lxml）。定稿前请打印核对。"
    return {
        "ok": True,
        "mode": "lite",
        "text": lite_docx.render_lite_report(report),
        "note": note,
        "docx": base64.b64encode(raw).decode("ascii"),
    }


def op_format(d: dict) -> dict:
    lines = body_lines(d.get("b", ""))
    if not any(x.strip() for x in lines):
        return {"ok": False, "text": "右框没有正文。"}
    unit_fonts = str(d.get("unit_fonts") or "").strip()
    if d.get("lite_only"):
        return _format_via_lite(lines, unit_fonts, "已按选择使用轻量排版")
    try:
        import docx  # noqa: F401
        import build_docx
    except ImportError:
        return _format_via_lite(lines, unit_fonts, "本机未安装 python-docx / lxml")
    meta = {"unit_fonts": unit_fonts} if unit_fonts else {}
    try:
        doc, report = build_docx.build(lines, meta)
    except build_docx.BuildError as exc:
        return {"ok": False, "text": "排版失败：%s" % exc}
    report["input"] = "右框正文"
    report["output"] = "成稿.docx（浏览器下载）"
    buf = io.BytesIO()
    doc.save(buf)
    note = "已按完整模式排版，版式按文种自动判断；字体缺失时看下方报告，定稿前请打印核对。"
    return {
        "ok": True,
        "mode": "full",
        "text": build_docx.render_text(report),
        "note": note,
        "docx": base64.b64encode(buf.getvalue()).decode("ascii"),
    }


def op_extract_docx(d: dict) -> dict:
    b64 = d.get("data_b64") or ""
    fname = Path(str(d.get("filename") or "上传文件.docx")).name
    try:
        raw = base64.b64decode(b64, validate=True)
        extracted = lite_docx.read_docx_text(raw)
    except Exception as exc:
        return {"ok": False, "text": f"读取 {fname} 失败：{exc}"}
    hf = str(extracted["headers_footers"] or "")
    hits = desensitize.check_secret_text(str(extracted["full"]))
    summary_lines = [
        f"已纯标准库读取 {fname}：正文 {extracted['paragraphs']} 段，表格 {extracted['tables']} 张。",
    ]
    if hf:
        summary_lines.append("已一并读取页眉/页脚文字（涉密检测时同步扫描）。")
    secret_warn = bool(hits)
    if secret_warn:
        summary_lines.append("【警告】检测到保密标识，请立即停止处理，切勿发送给非涉密模型：")
        summary_lines.extend("[%s] %s：%s" % h for h in hits[:10])
    return {
        "ok": True,
        "text": str(extracted["body"]),
        "headers_footers": hf,
        "hf_note": f"已导入 {fname}" + ("（含页眉页脚，已纳入保密检查）" if hf else ""),
        "secret_warn": secret_warn,
        "summary": NL.join(summary_lines),
        "note": "导入完成，检测到保密标识！" if secret_warn else f"已导入 {fname}",
    }


def op_ofd(d: dict) -> dict:
    b64 = d.get("data_b64") or ""
    fname = Path(str(d.get("filename") or "成稿.ofd")).name
    try:
        raw = base64.b64decode(b64, validate=True)
    except Exception as exc:
        return {"ok": False, "text": f"OFD 数据解码失败：{exc}"}
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / fname
        target.write_bytes(raw)
        try:
            result = ofd_check.check(target)
        except Exception as exc:
            return {"ok": False, "text": f"OFD 体检失败（{fname}）：{exc}"}
    s = result["summary"]
    ok = (s["P0"] == 0 and s["P1"] == 0)
    note = f"OFD 体检完成：{fname}（P0 {s['P0']}｜P1 {s['P1']}｜P2 {s['P2']}）"
    return {"ok": ok, "text": ofd_check.render_text(result), "note": note}


def _list_prompts() -> List[Dict[str, object]]:
    items: List[Dict[str, object]] = []
    for key, rel_dir, label in PROMPT_GROUPS:
        base = ROOT / rel_dir
        if not base.is_dir():
            continue
        for p in sorted(base.glob("*.md")):
            if p.name == "README.md":
                continue
            text = p.read_text(encoding="utf-8-sig")
            first_line = next((ln.lstrip("#").strip() for ln in text.splitlines() if ln.strip()), p.stem)
            items.append({
                "id": f"{key}/{p.name}",
                "group": key,
                "group_label": "一站式合集" if key == "bundles" else "单技能精简",
                "title": first_line,
                "chars": len(text),
                "path": p,
            })
    return items


def op_prompts(_d: dict) -> dict:
    items = [{k: v for k, v in it.items() if k != "path"} for it in _list_prompts()]
    return {"ok": True, "items": items}


def op_prompt_text(d: dict) -> dict:
    wanted = str(d.get("id") or "").strip()
    for it in _list_prompts():
        if it["id"] == wanted:
            text = Path(it["path"]).read_text(encoding="utf-8-sig")  # type: ignore[arg-type]
            return {"ok": True, "id": wanted, "title": it["title"], "chars": len(text), "text": text}
    return {"ok": False, "text": f"未找到指定提示词：{wanted}"}


OPS = {
    "secret": op_secret,
    "mask": op_mask,
    "restore": op_restore,
    "show_map": op_show_map,
    "clear_map": op_clear_map,
    "lint": op_lint,
    "factdiff": op_factdiff,
    "fonts": op_fonts,
    "format": op_format,
    "extract_docx": op_extract_docx,
    "ofd": op_ofd,
    "prompts": op_prompts,
    "prompt_text": op_prompt_text,
}


class Handler(BaseHTTPRequestHandler):
    server_version = "GongwenToolbox"

    def log_message(self, *args):
        # 不把请求写进终端日志，避免材料相关内容留在屏幕上
        pass

    def _allowed(self) -> bool:
        # 只认回环地址的 Host 和 Origin，挡住别的网页借浏览器来调本机接口（DNS 重绑定）
        port = self.server.server_address[1]
        hosts = {f"{HOST}:{port}", f"localhost:{port}"}
        origin = self.headers.get("Origin")
        return self.headers.get("Host", "") in hosts and (origin is None or origin.split("//", 1)[-1] in hosts)

    def _send(self, code: int, body: str, ctype: str) -> None:
        raw = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        if not self._allowed():
            self._send(403, "拒绝访问", "text/plain; charset=utf-8")
        elif self.path == "/":
            self._send(200, PAGE, "text/html; charset=utf-8")
        elif self.path == "/api/prompts":
            self._send(200, json.dumps(op_prompts({}), ensure_ascii=False), "application/json; charset=utf-8")
        else:
            self._send(404, "不存在", "text/plain; charset=utf-8")

    def do_POST(self) -> None:
        op = OPS.get(self.path[5:]) if self.path.startswith("/api/") else None
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = MAX_BODY + 1
        if not self._allowed() or op is None or length > MAX_BODY:
            if 0 < length <= 65536:
                try:
                    self.rfile.read(length)
                except OSError:
                    pass
            self._send(403, "拒绝访问", "text/plain; charset=utf-8")
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8")) if length > 0 else {}
            if not isinstance(payload, dict):
                payload = {}
            out = op(payload)
        except Exception as exc:  # 边界：任何一步出错都回给页面显示，不让进程崩
            out = {"ok": False, "text": "处理失败：%s" % exc}
        self._send(200, json.dumps(out, ensure_ascii=False), "application/json; charset=utf-8")


def _bind_server(start_port: int, auto_port: bool) -> HTTPServer:
    ports = range(start_port, start_port + 11) if auto_port else (start_port,)
    last_exc: Optional[OSError] = None
    for port in ports:
        try:
            return HTTPServer((HOST, port), Handler)
        except OSError as exc:
            last_exc = exc
    raise last_exc or OSError("无法绑定端口")


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="公文写作本机零联网工具箱（只监听 127.0.0.1）。")
    ap.add_argument("--port", type=int, default=8765, help="监听端口，默认 8765")
    ap.add_argument("--auto-port", action="store_true", help="端口被占用时顺延尝试后续 10 个端口")
    ap.add_argument("--port-file", type=Path, help="将实际监听端口号写入该文件（供双击启动器读取）")
    args = ap.parse_args(argv)
    try:
        server = _bind_server(args.port, args.auto_port)
    except OSError as exc:
        print("无法监听 %s:%d：%s（端口被占用时加 --auto-port 或 --port 换一个）" % (HOST, args.port, exc))
        return 2
    bound_port = server.server_address[1]
    if args.port_file:
        try:
            args.port_file.write_text(str(bound_port), encoding="utf-8")
        except OSError:
            pass
    print("已启动：用浏览器打开 http://%s:%d 。退出请按 Ctrl+C。" % (HOST, bound_port), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("已退出，脱敏映射表随进程销毁。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
