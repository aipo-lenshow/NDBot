"""NDBot - Web UI"""

import json
import mimetypes
import os
import shutil
from pathlib import Path

import redis
from flask import (
    Flask, abort, jsonify, render_template_string,
    request, send_file, session, Response,
)

app = Flask(__name__)
app.secret_key = os.urandom(24)


@app.route("/static/app.js")
def static_js():
    from flask import Response
    return Response(APP_JS, mimetype="application/javascript; charset=utf-8")


REDIS_URL    = os.environ.get("REDIS_URL", "redis://redis:6379/0")
DOWNLOAD_DIR = Path(os.environ.get("DOWNLOAD_DIR", "/downloads"))
WEB_SECRET   = os.environ.get("WEB_SECRET", "")
RCLONE_CFG   = "/config/rclone/rclone.conf"

r = redis.from_url(REDIS_URL, decode_responses=True)
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

EXTRA_MIME = {
    ".mkv": "video/x-matroska", ".webm": "video/webm",
    ".ts":  "video/mp2t",       ".m4v":  "video/mp4",
    ".m4a": "audio/mp4",        ".opus": "audio/ogg",
    ".flac":"audio/flac",       ".weba": "audio/webm",
}


def auth_ok():
    return not WEB_SECRET or session.get("ws") == WEB_SECRET


def fmt_bytes(b):
    for u in ["B","KB","MB","GB","TB"]:
        if b < 1024: return f"{b:.1f} {u}"
        b //= 1024
    return f"{b:.1f} TB"


def disk_info():
    try:
        u = shutil.disk_usage(str(DOWNLOAD_DIR))
        return {"total": fmt_bytes(u.total), "used": fmt_bytes(u.used),
                "free": fmt_bytes(u.free), "pct": round(u.used/u.total*100, 1)}
    except Exception:
        return {"total":"—","used":"—","free":"—","pct":0}


def rclone_remotes():
    try:
        p = Path(RCLONE_CFG)
        if not p.exists(): return []
        return [l.strip()[1:-1] for l in p.read_text().splitlines()
                if l.strip().startswith("[") and l.strip().endswith("]")]
    except Exception:
        return []


def safe_path(rel):
    try:
        t = (DOWNLOAD_DIR / rel).resolve()
        t.relative_to(DOWNLOAD_DIR.resolve())
        return t
    except Exception:
        abort(403)


# ── Auth ─────────────────────────────────────────────────────


@app.route("/static/ndbot_logo.jpg")
def logo_ndbot():
    from flask import Response
    import os, pathlib
    logo_path = pathlib.Path(__file__).parent / "ndbot_logo.jpg"
    if logo_path.exists():
        return Response(logo_path.read_bytes(), mimetype="image/jpeg")
    return "", 404


@app.route("/static/aipo_logo.jpg")
def logo_aipo():
    from flask import Response
    import pathlib
    logo_path = pathlib.Path(__file__).parent / "aipo_logo.jpg"
    if logo_path.exists():
        return Response(logo_path.read_bytes(), mimetype="image/jpeg")
    return "", 404

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        if request.form.get("pw") == WEB_SECRET:
            session["ws"] = WEB_SECRET
            return "", 200
        return "密码错误", 401
    return render_template_string(LOGIN_HTML)


@app.route("/logout")
def logout():
    session.clear()
    return "", 200


@app.route("/")
def index():
    if WEB_SECRET and not auth_ok():
        return render_template_string(LOGIN_HTML)
    return render_template_string(MAIN_HTML)


# ── API ──────────────────────────────────────────────────────
@app.route("/api/stats")
def api_stats():
    if not auth_ok(): abort(401)
    tasks = [json.loads(v) for v in r.hgetall("dl:tasks").values()]
    files = [f for f in DOWNLOAD_DIR.rglob("*") if f.is_file()]
    total_sz = sum(f.stat().st_size for f in files)
    return jsonify({
        "queue":      r.llen("dl:queue"),
        "running":    sum(1 for t in tasks if t.get("status")=="running"),
        "done":       sum(1 for t in tasks if t.get("status")=="done"),
        "failed":     sum(1 for t in tasks if t.get("status")=="failed"),
        "files":      len(files),
        "total_size": fmt_bytes(total_sz),
        "disk":       disk_info(),
        "save_dir":   str(DOWNLOAD_DIR),
    })


@app.route("/api/tasks")
def api_tasks():
    if not auth_ok(): abort(401)
    tasks = [json.loads(v) for v in r.hgetall("dl:tasks").values()]
    sf = request.args.get("status","")
    if sf: tasks = [t for t in tasks if t.get("status")==sf]
    sb = request.args.get("sort","ts")
    rv = request.args.get("order","desc")=="desc"
    tasks.sort(key=lambda t: t.get(sb,""), reverse=rv)
    return jsonify(tasks)


@app.route("/api/tasks/clean", methods=["POST"])
def api_tasks_clean():
    if not auth_ok(): abort(401)
    body = request.json or {}
    mode = body.get("mode","all")
    tid  = body.get("id","")
    raw  = r.hgetall("dl:tasks")
    removed = 0
    if mode=="id" and tid:
        if r.hdel("dl:tasks", tid): removed=1
    else:
        for k,v in raw.items():
            t = json.loads(v)
            st = t.get("status","")
            if mode=="all" or (mode=="done" and st=="done") or (mode=="failed" and st=="failed"):
                r.hdel("dl:tasks", k); removed+=1
    return jsonify({"removed": removed})


@app.route("/api/files")
def api_files():
    if not auth_ok(): abort(401)
    subdir   = request.args.get("dir","")
    sort_by  = request.args.get("sort","mtime")
    order    = request.args.get("order","desc")
    page     = max(1, int(request.args.get("page",1)))
    per_page = int(request.args.get("per",30))
    target = safe_path(subdir) if subdir else DOWNLOAD_DIR
    if not target.exists():
        return jsonify({"files":[],"total":0})
    files = [f for f in target.rglob("*") if f.is_file()]
    if sort_by=="name":
        files.sort(key=lambda f: f.name.lower(), reverse=(order=="desc"))
    elif sort_by=="size":
        files.sort(key=lambda f: f.stat().st_size, reverse=(order=="desc"))
    else:
        files.sort(key=lambda f: f.stat().st_mtime, reverse=(order=="desc"))
    total  = len(files)
    paged  = files[(page-1)*per_page : page*per_page]
    result = []
    for f in paged:
        st   = f.stat()
        mime = mimetypes.guess_type(f.name)[0] or ""
        rel  = str(f.relative_to(DOWNLOAD_DIR))
        ftype = ("video" if mime.startswith("video") else
                 "audio" if mime.startswith("audio") else
                 "image" if mime.startswith("image") else
                 "text"  if mime.startswith("text")  else "other")
        result.append({"name":f.name,"rel":rel,"size":fmt_bytes(st.st_size),
                        "bytes":st.st_size,"mtime":st.st_mtime,"mime":mime,"type":ftype})
    return jsonify({"files":result,"total":total})


@app.route("/api/files/delete", methods=["POST"])
def api_files_delete():
    if not auth_ok(): abort(401)
    rel = (request.json or {}).get("rel","")
    if not rel:
        return jsonify({"ok":False,"error":"未指定文件"}), 400
    target = safe_path(rel)
    if not target.is_file():
        return jsonify({"ok":False,"error":"文件不存在"}), 404
    import uuid as _u, datetime as _dt
    task = {"id":_u.uuid4().hex[:8],
            "ts":_dt.datetime.now(_dt.timezone.utc).isoformat(),
            "status":"queued","type":"delete","rel":rel,
            "reply_chat":None,"reply_msg":None}
    r.lpush("dl:queue", json.dumps(task))
    r.hset("dl:tasks", task["id"], json.dumps(task))
    return jsonify({"ok":True,"task_id":task["id"]})


@app.route("/api/files/download")
def api_files_download():
    if not auth_ok(): abort(401)
    rel = request.args.get("rel","")
    if not rel: abort(400)
    target = safe_path(rel)
    if not target.is_file(): abort(404)
    return send_file(str(target), as_attachment=True, download_name=target.name)


@app.route("/api/files/stream")
def api_files_stream():
    if not auth_ok(): abort(401)
    rel = request.args.get("rel","")
    if not rel: abort(400)
    target = safe_path(rel)
    if not target.is_file(): abort(404)
    ext  = target.suffix.lower()
    mime = EXTRA_MIME.get(ext) or mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    size = target.stat().st_size
    rng  = request.headers.get("Range","")
    if rng and rng.startswith("bytes="):
        try:
            parts = rng[6:].split("-")
            s = int(parts[0]) if parts[0] else 0
            e = int(parts[1]) if len(parts)>1 and parts[1] else size-1
            e = min(e, size-1)
            length = e-s+1
            with open(target,"rb") as f:
                f.seek(s); data=f.read(length)
            return Response(data, 206, mimetype=mime, headers={
                "Content-Range":f"bytes {s}-{e}/{size}",
                "Accept-Ranges":"bytes","Content-Length":str(length),"Cache-Control":"no-cache"})
        except Exception:
            pass
    def gen():
        with open(target,"rb") as f:
            while chunk := f.read(65536): yield chunk
    return Response(gen(), 200, mimetype=mime,
                    headers={"Accept-Ranges":"bytes","Content-Length":str(size),"Cache-Control":"no-cache"})


@app.route("/api/rclone/remotes")
def api_rclone_remotes():
    if not auth_ok(): abort(401)
    return jsonify({"remotes": rclone_remotes()})


@app.route("/api/rclone/upload", methods=["POST"])
def api_rclone_upload():
    if not auth_ok(): abort(401)
    body   = request.json or {}
    remote = body.get("remote","")
    dest   = body.get("dest","NDBot")
    rel    = body.get("rel","")
    if not remote:
        return jsonify({"ok":False,"error":"未指定远端"}), 400
    source = safe_path(rel) if rel else DOWNLOAD_DIR
    dst    = f"{remote}:{dest}" + (f"/{Path(rel).parent}" if rel else "")
    import uuid as _u, datetime as _dt
    task = {"id":_u.uuid4().hex[:8],
            "ts":_dt.datetime.now(_dt.timezone.utc).isoformat(),
            "status":"queued","type":"sync",
            "rclone_src":str(source),"rclone_dst":dst,
            "reply_chat":None,"reply_msg":None}
    r.lpush("dl:queue", json.dumps(task))
    r.hset("dl:tasks", task["id"], json.dumps(task))
    return jsonify({"ok":True,"task_id":task["id"]})


# ── HTML ─────────────────────────────────────────────────────
LOGIN_HTML = """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NDBot v1.0501</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,sans-serif;background:#080810;color:#dde1f0;
     display:flex;align-items:center;justify-content:center;min-height:100vh}
.box{background:#0f0f1a;border:1px solid #1e1e35;border-radius:12px;
     padding:48px 40px;width:320px;text-align:center}
h1{font-size:20px;color:#818cf8;margin-bottom:6px;font-weight:700}
p{font-size:12px;color:#555;margin-bottom:28px}
input{width:100%;padding:11px 14px;background:#080810;border:1px solid #333;
      border-radius:7px;color:#dde1f0;font-size:14px;margin-bottom:14px;outline:none;
      transition:border .2s}
input:focus{border-color:#818cf8}
button{width:100%;padding:11px;background:#818cf8;color:#fff;border:none;
       border-radius:7px;font-size:14px;cursor:pointer;transition:background .2s}
button:hover{background:#6366f1}
.err{color:#f87171;font-size:12px;margin-top:10px;display:none}
</style></head><body>
<div class="box">
  <div style="display:flex;align-items:center;justify-content:center;gap:10px;margin-bottom:4px">
        <img src="/static/ndbot_logo.jpg" style="width:40px;height:40px;border-radius:8px;object-fit:cover">
        <h1>NDBot v1.0501</h1>
      </div>
  <p style="color:#666;font-size:11px;margin-bottom:4px">v1.0501 · by AiPo</p><p>请输入访问密码</p>
  <input type="password" id="pw" placeholder="密码" onkeydown="if(event.key==='Enter')doLogin()">
  <button onclick="doLogin()">进入控制台</button>
  <div class="err" id="err">密码错误，请重试</div>
</div>
</body></html>"""

APP_JS = r"""
// ── 全局状态 ──────────────────────────────────────────────
var currentPanel='dashboard', taskFilter='', taskSort='ts', taskOrder='desc';
var fileDir='', filePage=1, autoTimer=null;
window._fileList=[];

// ── 主题 ──────────────────────────────────────────────────
function setTheme(t){
  document.documentElement.setAttribute('data-theme',t);
  localStorage.setItem('nd-theme',t);
  document.querySelectorAll('.tdot').forEach(d=>d.classList.remove('on'));
  document.querySelectorAll('.t-'+t).forEach(d=>d.classList.add('on'));
}
(function(){ setTheme(localStorage.getItem('nd-theme')||'dark'); })();

// ── 面板切换（接收 el 参数，不依赖全局 event 对象）────────
function showPanel(name, el){
  currentPanel=name;
  document.querySelectorAll('.panel').forEach(p=>p.classList.remove('on'));
  document.querySelectorAll('.nav-item').forEach(n=>n.classList.remove('on'));
  var panel=document.getElementById('panel-'+name);
  if(panel) panel.classList.add('on');
  if(el) el.classList.add('on');
  if(name==='dashboard') loadDash();
  if(name==='tasks')     loadTasks();
  if(name==='files'){    buildDirTabs(); loadFiles(); }
  if(name==='rclone')    loadRemotes();
}

// ── Toast ─────────────────────────────────────────────────
function toast(msg,type){
  var el=document.getElementById('toast');
  el.textContent=msg; el.className='toast show '+(type||'ok');
  setTimeout(function(){ el.className='toast'; }, 3000);
}

// ── 仪表盘 ────────────────────────────────────────────────
async function loadDash(){
  var s=await fetch('/api/stats').then(function(r){return r.json();}).catch(function(){return null;});
  if(!s) return;
  document.getElementById('dq').textContent=s.queue;
  document.getElementById('dr').textContent=s.running;
  document.getElementById('dd').textContent=s.done;
  document.getElementById('df').textContent=s.failed;
  document.getElementById('dfl').textContent=s.files;
  document.getElementById('dsz').textContent=s.total_size;
  document.getElementById('ddir').textContent=s.save_dir;
  var d=s.disk;
  document.getElementById('dused').textContent=d.used;
  document.getElementById('dfree').textContent=d.free;
  document.getElementById('dtotal').textContent=d.total;
  document.getElementById('dpct').textContent=d.pct+'%';
  var bar=document.getElementById('dbar');
  bar.style.width=d.pct+'%';
  bar.className='disk-fill'+(d.pct>90?' danger':d.pct>70?' warn':'');
}

// ── 任务列表 ──────────────────────────────────────────────
function setFilter(btn,f){
  taskFilter=f;
  document.querySelectorAll('.fbtn').forEach(function(b){b.classList.remove('on');});
  btn.classList.add('on');
  loadTasks();
}
function sortBy(col){
  if(taskSort===col) taskOrder=taskOrder==='desc'?'asc':'desc';
  else { taskSort=col; taskOrder='desc'; }
  loadTasks();
}
async function loadTasks(){
  var url='/api/tasks?status='+taskFilter+'&sort='+taskSort+'&order='+taskOrder;
  var tasks=await fetch(url).then(function(r){return r.json();}).catch(function(){return[];});
  var ICONS={queued:'⏳ 队列',running:'🔄 下载中',done:'✅ 完成',failed:'❌ 失败',delete:'🗑 删除'};
  var html='';
  for(var i=0;i<Math.min(tasks.length,100);i++){
    var t=tasks[i];
    var urlSafe=(t.url||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    html+='<tr>'
      +'<td><code>'+t.id+'</code></td>'
      +'<td>'+(t.platform||t.type||'-')+'</td>'
      +'<td>'+(t.action||'-')+'</td>'
      +'<td title="'+urlSafe+'">'+(urlSafe.substring(0,42))+'</td>'
      +'<td><span class="badge '+(t.status||'')+'">'+(ICONS[t.status]||t.status||'-')+'</span></td>'
      +'<td>'+((t.ts||'').substring(11,19))+'</td>'
      // data-id 避免字符串拼接 onclick，彻底消除引号转义问题
      +'<td><button class="btn btn-ghost btn-sm task-del-btn" data-id="'+t.id+'">🗑</button></td>'
      +'</tr>';
  }
  document.getElementById('task-body').innerHTML=html;
  // 事件委托：从 data-id 读取，不用 onclick 字符串
  document.getElementById('task-body').onclick=function(e){
    var btn=e.target.closest('.task-del-btn');
    if(btn) cleanTasks('id', btn.getAttribute('data-id'));
  };
}
async function cleanTasks(mode,id){
  var labels={all:'全部',done:'已完成',failed:'失败',id:'此条'};
  if(!confirm('确认清理'+labels[mode]+'任务记录？')) return;
  var res=await fetch('/api/tasks/clean',{method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({mode:mode,id:id||''})
  }).then(function(r){return r.json();});
  toast('已清理 '+res.removed+' 条记录');
  loadTasks(); if(currentPanel==='dashboard') loadDash();
}

// ── 文件浏览 ──────────────────────────────────────────────
var DIRS=['','youtube','xcom','bilibili','instagram','tiktok','telegram','generic'];
var DIR_LABELS={'':'全部',youtube:'YouTube',xcom:'X.com',bilibili:'Bilibili',
                instagram:'Instagram',tiktok:'TikTok',telegram:'Telegram',generic:'其他'};

function buildDirTabs(){
  document.getElementById('dir-tabs').innerHTML=DIRS.map(function(d){
    return '<button class="dir-tab'+(d===fileDir?' on':'')+'" data-dir="'+d+'">'+DIR_LABELS[d]+'</button>';
  }).join('');
  document.getElementById('dir-tabs').onclick=function(e){
    var btn=e.target.closest('button[data-dir]');
    if(btn) switchDir(btn.getAttribute('data-dir'));
  };
}
function switchDir(d){ fileDir=d; filePage=1; buildDirTabs(); loadFiles(); }

async function loadFiles(){
  var sort=document.getElementById('fsort').value;
  var order=document.getElementById('forder').value;
  var url='/api/files?dir='+fileDir+'&sort='+sort+'&order='+order+'&page='+filePage+'&per=30';
  var data=await fetch(url).then(function(r){return r.json();}).catch(function(){return{files:[],total:0};});
  window._fileList=data.files;

  var ICONS={video:'🎬',audio:'🎵',image:'🖼',text:'📝',other:'📄'};
  document.getElementById('file-grid').innerHTML=data.files.map(function(f,idx){
    var icon=ICONS[f.type]||'📄';
    var isMedia=(f.type==='video'||f.type==='audio'||f.type==='image');
    var streamUrl='/api/files/stream?rel='+encodeURIComponent(f.rel);
    var pre=(f.type==='image')
      ? '<img class="fpreview img-lazy" src="'+streamUrl+'" loading="lazy">'
      : '<div class="fthumb">'+icon+'</div>';
    return '<div class="file-card" data-idx="'+idx+'">'
      +pre
      +'<div class="finfo">'
      +'<div class="fname" title="'+f.name.replace(/"/g,'&quot;')+'">'+f.name.replace(/</g,'&lt;').replace(/>/g,'&gt;')+'</div>'
      +'<div class="fmeta">'+f.size+'</div>'
      +'</div>'
      +'<div class="factions">'
      +(isMedia?'<button class="btn btn-ghost btn-sm fc-prev">▶ 预览</button>':'')
      +'<button class="btn btn-primary btn-sm fc-dl">⬇ 下载</button>'
      +'<button class="btn btn-danger btn-sm fc-del">🗑</button>'
      +'</div></div>';
  }).join('')||'<div style="color:var(--tx2);padding:20px">暂无文件</div>';

  // 事件委托
  document.getElementById('file-grid').onclick=function(e){
    var card=e.target.closest('.file-card');
    if(!card) return;
    var f=window._fileList[parseInt(card.dataset.idx)];
    if(!f) return;
    if(e.target.classList.contains('fc-prev')) previewFile(f);
    if(e.target.classList.contains('fc-dl'))   dlFile(f.rel,f.name);
    if(e.target.classList.contains('fc-del'))  delFile(f.rel,card);
  };

  // 分页
  var tp=Math.ceil(data.total/30); var pg='';
  if(tp>1){
    pg+='<button class="pager-btn" data-pg="'+(filePage-1)+'" '+(filePage<=1?'disabled':'')+'>‹</button>';
    for(var i=Math.max(1,filePage-2);i<=Math.min(tp,filePage+2);i++){
      pg+='<button class="pager-btn'+(i===filePage?' on':'')+'" data-pg="'+i+'">'+i+'</button>';
    }
    pg+='<button class="pager-btn" data-pg="'+(filePage+1)+'" '+(filePage>=tp?'disabled':'')+'>›</button>';
    pg+='<span style="font-size:11px;color:var(--tx2);margin-left:6px">共 '+data.total+' 个</span>';
  }
  document.getElementById('pager').innerHTML=pg;
  document.getElementById('pager').onclick=function(e){
    var btn=e.target.closest('[data-pg]');
    if(btn && !btn.disabled) goPage(parseInt(btn.getAttribute('data-pg')));
  };
}

function goPage(p){ filePage=p; loadFiles(); }

function previewFile(f){
  var mc=document.getElementById('modal-body');
  var src='/api/files/stream?rel='+encodeURIComponent(f.rel);
  if(f.type==='video'){
    var ext=f.name.split('.').pop().toLowerCase();
    if(ext==='mkv'){
      mc.innerHTML='<div style="padding:40px;text-align:center;color:var(--tx2)">'
        +'<div style="font-size:48px;margin-bottom:12px">🎬</div>'
        +'<div style="margin-bottom:6px;word-break:break-all">'+f.name.replace(/</g,'&lt;')+'</div>'
        +'<div style="font-size:12px;margin-bottom:16px">MKV 格式浏览器不支持在线播放</div>'
        +'<button class="btn btn-primary" id="mkv-dl">⬇ 下载到本地播放</button></div>';
      document.getElementById('mkv-dl').onclick=function(){ dlFile(f.rel,f.name); };
    } else {
      mc.innerHTML='<video controls autoplay style="max-width:80vw;max-height:70vh">'
        +'<source src="'+src+'" type="'+(f.mime||'video/mp4')+'">'
        +'<source src="'+src+'">'
        +'<p style="color:var(--tx2)">浏览器不支持此格式，请<a href="'+src+'" download>下载</a>后播放</p>'
        +'</video>';
    }
  } else if(f.type==='audio'){
    mc.innerHTML='<audio controls autoplay style="width:360px">'
      +'<source src="'+src+'" type="'+(f.mime||'audio/mpeg')+'">'
      +'<source src="'+src+'"></audio>';
  } else if(f.type==='image'){
    mc.innerHTML='<img src="'+src+'" style="max-width:80vw;max-height:70vh">';
  }
  document.getElementById('modal-name').textContent=f.name;
  document.getElementById('modal').classList.add('open');
}

function closeModal(){
  document.getElementById('modal').classList.remove('open');
  document.getElementById('modal-body').innerHTML='';
}

function dlFile(rel,name){
  var a=document.createElement('a');
  a.href='/api/files/download?rel='+encodeURIComponent(rel);
  a.download=name; a.click();
}

async function delFile(rel,card){
  if(!confirm('确认删除此文件？不可撤销。')) return;
  if(card){ card.style.opacity='.3'; card.style.pointerEvents='none'; }
  var res=await fetch('/api/files/delete',{method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({rel:rel})
  }).then(function(r){return r.json();}).catch(function(){return{ok:false};});
  if(res.ok){
    toast('删除任务已提交');
    setTimeout(loadFiles,1500);
  } else {
    if(card){ card.style.opacity='1'; card.style.pointerEvents='auto'; }
    toast('删除失败：'+(res.error||'未知错误'),'err');
  }
}

// ── 云盘转存 ──────────────────────────────────────────────
async function loadRemotes(){
  var data=await fetch('/api/rclone/remotes').then(function(r){return r.json();}).catch(function(){return{remotes:[]};});
  var sel=document.getElementById('rc-remote');
  sel.innerHTML=data.remotes.length
    ? data.remotes.map(function(r){return '<option value="'+r+'">'+r+'</option>';}).join('')
    : '<option value="">未找到配置（请先配置 rclone.conf）</option>';
}

async function doRclone(){
  var remote=document.getElementById('rc-remote').value;
  var dest=document.getElementById('rc-dest').value.trim()||'NDBot';
  var rel=document.getElementById('rc-rel').value.trim();
  if(!remote){ toast('请选择云盘远端','err'); return; }
  var res=await fetch('/api/rclone/upload',{method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({remote:remote,dest:dest,rel:rel})
  }).then(function(r){return r.json();}).catch(function(){return{ok:false};});
  if(res.ok){
    document.getElementById('rc-res').innerHTML='✅ 转存任务已提交，任务 ID：<code>'+res.task_id+'</code>';
    toast('转存任务已提交');
  } else {
    document.getElementById('rc-res').textContent='❌ 失败：'+(res.error||'未知错误');
    toast('提交失败','err');
  }
}

// ── 自动刷新 ──────────────────────────────────────────────
function toggleAuto(){
  var on=document.getElementById('auto-chk').checked;
  if(on) autoTimer=setInterval(function(){ if(currentPanel==='dashboard') loadDash(); },5000);
  else { clearInterval(autoTimer); autoTimer=null; }
}

// ── 初始化 ────────────────────────────────────────────────
loadDash();
setInterval(function(){ if(currentPanel==='dashboard') loadDash(); },10000);
"""

MAIN_HTML = """<!DOCTYPE html>
<html lang="zh" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NDBot v1.0501 控制台</title>
<style>
[data-theme="dark"]{
  --bg:#080810;--sf:#0f0f1a;--sf2:#161625;--bd:#1e1e35;
  --tx:#dde1f0;--tx2:#666;--ac:#818cf8;--ac2:#6366f1;
  --green:#4ade80;--red:#f87171;--yellow:#fbbf24;--blue:#60a5fa;}
[data-theme="light"]{
  --bg:#f0f2f8;--sf:#fff;--sf2:#f5f5ff;--bd:#e0e0ef;
  --tx:#1a1a2e;--tx2:#777;--ac:#4f46e5;--ac2:#3730a3;
  --green:#16a34a;--red:#dc2626;--yellow:#d97706;--blue:#2563eb;}
[data-theme="terminal"]{
  --bg:#000;--sf:#0a0a0a;--sf2:#111;--bd:#1a3a1a;
  --tx:#00ff41;--tx2:#007a1f;--ac:#00ff41;--ac2:#00cc33;
  --green:#00ff41;--red:#ff4444;--yellow:#ffff00;--blue:#00ffff;}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,-apple-system,sans-serif;background:var(--bg);
     color:var(--tx);min-height:100vh;transition:background .3s,color .3s}
::-webkit-scrollbar{width:5px;height:5px}
::-webkit-scrollbar-track{background:var(--bg)}
::-webkit-scrollbar-thumb{background:var(--bd);border-radius:3px}
.layout{display:grid;grid-template-columns:190px 1fr;min-height:100vh}
.sidebar{background:var(--sf);border-right:1px solid var(--bd);
         padding:0;position:sticky;top:0;height:100vh;overflow-y:auto;
         display:flex;flex-direction:column}
.logo{padding:18px 16px 14px;border-bottom:1px solid var(--bd)}
.logo h1{font-size:15px;color:var(--ac);font-weight:700}
.logo p{font-size:11px;color:var(--tx2);margin-top:2px}
.nav-sec{padding:10px 16px 4px;font-size:10px;color:var(--tx2);
         text-transform:uppercase;letter-spacing:.08em}
.nav-item{display:flex;align-items:center;gap:9px;padding:9px 16px;
          cursor:pointer;font-size:13px;color:var(--tx2);
          border-left:2px solid transparent;transition:all .15s;user-select:none}
.nav-item:hover,.nav-item.on{color:var(--tx);background:var(--sf2);border-left-color:var(--ac)}
.nav-item .ico{font-size:15px;flex-shrink:0}
.theme-row{padding:14px 16px;border-top:1px solid var(--bd);margin-top:auto;
           display:flex;gap:8px;align-items:center}
.theme-row span{font-size:11px;color:var(--tx2)}
.tdot{width:18px;height:18px;border-radius:50%;cursor:pointer;
      border:2px solid transparent;transition:border .2s;flex-shrink:0}
.tdot.on{border-color:var(--tx)}
.t-dark{background:linear-gradient(135deg,#0f0f1a,#818cf8)}
.t-light{background:linear-gradient(135deg,#f0f2f8,#4f46e5)}
.t-term{background:linear-gradient(135deg,#000,#00ff41)}
.main{padding:20px;overflow-y:auto;min-width:0}
.topbar{display:flex;align-items:center;gap:10px;margin-bottom:18px;flex-wrap:wrap}
.topbar h2{font-size:17px;font-weight:600;flex:1;min-width:0}
.btn{padding:6px 13px;border-radius:6px;border:none;cursor:pointer;
     font-family:inherit;font-size:12px;font-weight:500;
     display:inline-flex;align-items:center;gap:5px;transition:all .15s;white-space:nowrap}
.btn-primary{background:var(--ac);color:#fff}.btn-primary:hover{background:var(--ac2)}
.btn-ghost{background:transparent;color:var(--tx2);border:1px solid var(--bd)}
.btn-ghost:hover{color:var(--tx);border-color:var(--ac)}
.btn-danger{background:transparent;color:var(--red);border:1px solid var(--red)}
.btn-danger:hover{background:var(--red);color:#fff}
.btn-sm{padding:3px 9px;font-size:11px}
.panel{display:none}.panel.on{display:block}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin-bottom:18px}
.card{background:var(--sf);border:1px solid var(--bd);border-radius:9px;padding:14px}
.card .num{font-size:26px;font-weight:700;color:var(--ac);font-family:monospace}
.card .lbl{font-size:11px;color:var(--tx2);margin-top:3px}
.disk-card{background:var(--sf);border:1px solid var(--bd);border-radius:9px;
           padding:16px;margin-bottom:18px}
.disk-bar{height:7px;background:var(--sf2);border-radius:4px;margin:10px 0 7px}
.disk-fill{height:100%;border-radius:4px;background:var(--ac);transition:width .5s}
.disk-fill.warn{background:var(--yellow)}.disk-fill.danger{background:var(--red)}
.disk-info{display:flex;gap:16px;font-size:12px;color:var(--tx2)}
.disk-path{font-size:11px;color:var(--tx2);margin-top:8px;word-break:break-all;font-family:monospace}
.box{background:var(--sf);border:1px solid var(--bd);border-radius:9px;overflow:hidden;margin-bottom:16px}
.box-tb{display:flex;gap:7px;padding:10px;border-bottom:1px solid var(--bd);flex-wrap:wrap;align-items:center}
.fbtn{padding:3px 11px;border-radius:14px;border:1px solid var(--bd);
      background:transparent;color:var(--tx2);cursor:pointer;font-size:11px;
      font-family:inherit;transition:all .15s}
.fbtn.on{background:var(--ac);color:#fff;border-color:var(--ac)}
table{width:100%;border-collapse:collapse;font-size:12px}
th{padding:7px 10px;text-align:left;color:var(--tx2);border-bottom:1px solid var(--bd);
   white-space:nowrap;cursor:pointer;user-select:none}
th:hover{color:var(--tx)}
td{padding:8px 10px;border-bottom:1px solid var(--sf2);
   max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
tr:last-child td{border-bottom:none}
tr:hover td{background:var(--sf2)}
.badge{display:inline-block;padding:1px 7px;border-radius:12px;font-size:10px;font-weight:600}
.badge.queued{background:#1f293766;color:#9ca3af}
.badge.running{background:#1e3a5f66;color:var(--blue)}
.badge.done{background:#14532d66;color:var(--green)}
.badge.failed{background:#7f1d1d66;color:var(--red)}
.badge.delete{background:#4a1d4a66;color:#c084fc}
code{font-family:monospace;font-size:11px;color:var(--ac)}
.dir-tabs{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:14px}
.dir-tab{padding:4px 12px;border-radius:14px;border:1px solid var(--bd);
         background:transparent;color:var(--tx2);cursor:pointer;font-size:12px;
         font-family:inherit;transition:all .15s}
.dir-tab.on{background:var(--ac);color:#fff;border-color:var(--ac)}
.file-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:9px}
.file-card{background:var(--sf2);border:1px solid var(--bd);border-radius:8px;
           overflow:hidden;transition:border-color .15s}
.file-card:hover{border-color:var(--ac)}
.fpreview{width:100%;height:110px;object-fit:cover;display:block;background:#000}
.fthumb{width:100%;height:110px;display:flex;align-items:center;
        justify-content:center;font-size:34px;background:var(--sf)}
.finfo{padding:7px 9px}
.fname{font-size:11px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;margin-bottom:2px}
.fmeta{font-size:10px;color:var(--tx2)}
.factions{display:flex;gap:3px;padding:0 9px 8px}
.factions .btn{flex:1;justify-content:center}
.pager{display:flex;gap:5px;align-items:center;padding:12px;justify-content:center}
.pager-btn{padding:3px 9px;border-radius:4px;border:1px solid var(--bd);
           background:transparent;color:var(--tx2);cursor:pointer;font-family:inherit;font-size:11px}
.pager-btn:hover,.pager-btn.on{background:var(--ac);color:#fff;border-color:var(--ac)}
.pager-btn:disabled{opacity:.4;cursor:default}
.form-box{background:var(--sf);border:1px solid var(--bd);border-radius:9px;
          padding:18px;max-width:480px;margin-bottom:14px}
.form-row{margin-bottom:12px}
.form-row label{display:block;font-size:12px;color:var(--tx2);margin-bottom:5px}
.form-row input,.form-row select{
  width:100%;padding:8px 11px;background:var(--sf2);
  border:1px solid var(--bd);border-radius:6px;color:var(--tx);
  font-family:inherit;font-size:13px;outline:none;transition:border .2s}
.form-row input:focus,.form-row select:focus{border-color:var(--ac)}
.modal-bg{display:none;position:fixed;inset:0;background:#000b;z-index:100;
          align-items:center;justify-content:center}
.modal-bg.open{display:flex}
.modal{background:var(--sf);border:1px solid var(--bd);border-radius:12px;
       max-width:92vw;max-height:92vh;overflow:auto;padding:20px;position:relative}
.modal-close{position:absolute;top:10px;right:12px;background:transparent;
             border:none;color:var(--tx2);cursor:pointer;font-size:20px;line-height:1}
.toast{position:fixed;bottom:22px;right:22px;background:var(--sf);
       border:1px solid var(--bd);border-radius:8px;padding:10px 16px;
       font-size:13px;z-index:200;opacity:0;transform:translateY(60px);
       transition:all .3s;pointer-events:none}
.toast.show{opacity:1;transform:translateY(0)}
.toast.ok{border-color:var(--green);color:var(--green)}
.toast.err{border-color:var(--red);color:var(--red)}
select.sm{padding:5px 8px;border-radius:5px;border:1px solid var(--bd);
          background:var(--sf2);color:var(--tx);font-family:inherit;font-size:12px}
@media(max-width:600px){
  .layout{grid-template-columns:1fr}
  .sidebar{height:auto;position:relative;flex-direction:row;flex-wrap:wrap}
  .theme-row{margin-top:0;border-top:none;border-left:1px solid var(--bd)}
}
</style>
</head>
<body>
<div class="layout">

<aside class="sidebar">
  <div class="logo"><div style="display:flex;align-items:center;justify-content:center;gap:10px;margin-bottom:4px">
        <img src="/static/ndbot_logo.jpg" style="width:40px;height:40px;border-radius:8px;object-fit:cover">
        <h1>NDBot</h1>
      </div><p>资源下载机器人</p></div>
  <div class="nav-sec">监控</div>
  <!-- nav-item 通过 onclick 传递 el 引用，避免使用全局 event 对象 -->
  <div class="nav-item on"  onclick="showPanel('dashboard',this)"><span class="ico">📊</span>仪表盘</div>
  <div class="nav-item"     onclick="showPanel('tasks',this)">    <span class="ico">📋</span>任务列表</div>
  <div class="nav-sec">文件</div>
  <div class="nav-item"     onclick="showPanel('files',this)">    <span class="ico">📁</span>文件浏览</div>
  <div class="nav-sec">云盘</div>
  <div class="nav-item"     onclick="showPanel('rclone',this)">   <span class="ico">☁️</span>云盘转存</div>
  <div class="nav-sec">系统</div>
  <div class="nav-item"     onclick="showPanel('settings',this)"> <span class="ico">⚙️</span>设置</div>
  <div style="padding:10px 16px 6px;border-top:1px solid var(--bd)">
    <div style="display:flex;align-items:center;gap:7px">
      <img src="/static/aipo_logo.jpg" style="width:22px;height:22px;border-radius:50%;object-fit:cover;flex-shrink:0">
      <span style="font-size:11px;color:var(--tx2)">by <b style="color:var(--ac)">AiPo</b></span>
    </div>
  </div>
  <div class="theme-row">
    <span>主题</span>
    <div class="tdot t-dark on"  title="深色"  onclick="setTheme('dark')"></div>
    <div class="tdot t-light"    title="浅色"  onclick="setTheme('light')"></div>
    <div class="tdot t-term"     title="终端"  onclick="setTheme('terminal')"></div>
  </div>
</aside>

<main class="main">

<!-- 仪表盘 -->
<div class="panel on" id="panel-dashboard">
  <div class="topbar"><h2>📊 仪表盘</h2>
    <button class="btn btn-ghost" onclick="loadDash()">🔄 刷新</button>
  </div>
  <div class="cards">
    <div class="card"><div class="num" id="dq">-</div><div class="lbl">⏳ 队列</div></div>
    <div class="card"><div class="num" id="dr">-</div><div class="lbl">🔄 进行中</div></div>
    <div class="card"><div class="num" id="dd">-</div><div class="lbl">✅ 完成</div></div>
    <div class="card"><div class="num" id="df">-</div><div class="lbl">❌ 失败</div></div>
    <div class="card"><div class="num" id="dfl">-</div><div class="lbl">📁 文件数</div></div>
    <div class="card"><div class="num" id="dsz">-</div><div class="lbl">💾 总大小</div></div>
  </div>
  <div class="disk-card">
    <div style="display:flex;justify-content:space-between">
      <b style="font-size:13px">磁盘空间</b>
      <span id="dpct" style="font-size:12px;color:var(--tx2)"></span>
    </div>
    <div class="disk-bar"><div class="disk-fill" id="dbar" style="width:0"></div></div>
    <div class="disk-info">
      <span>已用 <b id="dused">-</b></span>
      <span>可用 <b id="dfree">-</b></span>
      <span>总计 <b id="dtotal">-</b></span>
    </div>
    <div class="disk-path">📂 保存位置：<span id="ddir">-</span></div>
  </div>
</div>

<!-- 任务列表 -->
<div class="panel" id="panel-tasks">
  <div class="topbar"><h2>📋 任务列表</h2>
    <button class="btn btn-danger" onclick="cleanTasks('failed')">🗑 清理失败</button>
    <button class="btn btn-danger" onclick="cleanTasks('done')">🗑 清理完成</button>
    <button class="btn btn-danger" onclick="cleanTasks('all')">🗑 清理全部</button>
    <button class="btn btn-ghost"  onclick="loadTasks()">🔄 刷新</button>
  </div>
  <div class="box">
    <div class="box-tb">
      <button class="fbtn on" onclick="setFilter(this,'')">全部</button>
      <button class="fbtn"    onclick="setFilter(this,'running')">🔄 进行中</button>
      <button class="fbtn"    onclick="setFilter(this,'queued')">⏳ 队列</button>
      <button class="fbtn"    onclick="setFilter(this,'done')">✅ 完成</button>
      <button class="fbtn"    onclick="setFilter(this,'failed')">❌ 失败</button>
    </div>
    <table>
      <thead><tr>
        <th onclick="sortBy('id')">ID</th>
        <th onclick="sortBy('platform')">平台</th>
        <th onclick="sortBy('action')">格式</th>
        <th>URL</th>
        <th onclick="sortBy('status')">状态</th>
        <th onclick="sortBy('ts')">时间</th>
        <th>操作</th>
      </tr></thead>
      <tbody id="task-body"></tbody>
    </table>
  </div>
</div>

<!-- 文件浏览 -->
<div class="panel" id="panel-files">
  <div class="topbar"><h2>📁 文件浏览</h2>
    <select class="sm" id="fsort" onchange="loadFiles()">
      <option value="mtime">按时间</option>
      <option value="name">按名称</option>
      <option value="size">按大小</option>
    </select>
    <select class="sm" id="forder" onchange="loadFiles()">
      <option value="desc">降序</option>
      <option value="asc">升序</option>
    </select>
    <button class="btn btn-ghost" onclick="loadFiles()">🔄 刷新</button>
  </div>
  <div class="dir-tabs" id="dir-tabs"></div>
  <div class="file-grid" id="file-grid"></div>
  <div class="pager" id="pager"></div>
</div>

<!-- 云盘转存 -->
<div class="panel" id="panel-rclone">
  <div class="topbar"><h2>☁️ 云盘转存</h2></div>
  <div class="form-box">
    <div class="form-row"><label>选择云盘远端</label>
      <select id="rc-remote"><option value="">加载中...</option></select></div>
    <div class="form-row"><label>云盘目标目录</label>
      <input type="text" id="rc-dest" value="NDBot"></div>
    <div class="form-row"><label>指定文件路径（留空=同步全部）</label>
      <input type="text" id="rc-rel" placeholder="如：youtube/xxx.mp4"></div>
    <button class="btn btn-primary" onclick="doRclone()">☁️ 开始转存</button>
  </div>
  <div id="rc-res" style="font-size:13px;color:var(--tx2)"></div>
</div>

<!-- 设置 -->
<div class="panel" id="panel-settings">
  <div class="topbar"><h2>⚙️ 设置</h2></div>
  <div class="form-box">
    <div style="font-size:13px;font-weight:600;margin-bottom:12px">主题</div>
    <div style="display:flex;gap:18px">
      <div style="text-align:center;cursor:pointer" onclick="setTheme('dark')">
        <div class="tdot t-dark" id="ts-dark" style="width:28px;height:28px;margin:0 auto 4px"></div>
        <div style="font-size:11px;color:var(--tx2)">深色</div>
      </div>
      <div style="text-align:center;cursor:pointer" onclick="setTheme('light')">
        <div class="tdot t-light" id="ts-light" style="width:28px;height:28px;margin:0 auto 4px"></div>
        <div style="font-size:11px;color:var(--tx2)">浅色</div>
      </div>
      <div style="text-align:center;cursor:pointer" onclick="setTheme('terminal')">
        <div class="tdot t-term" id="ts-term" style="width:28px;height:28px;margin:0 auto 4px"></div>
        <div style="font-size:11px;color:var(--tx2)">终端</div>
      </div>
    </div>
  </div>
  <div class="form-box" style="margin-top:0">
    <div style="font-size:13px;font-weight:600;margin-bottom:12px">自动刷新</div>
    <label style="display:flex;align-items:center;gap:10px;cursor:pointer;font-size:13px">
      <input type="checkbox" id="auto-chk" onchange="toggleAuto()">
      每 5 秒自动刷新仪表盘
    </label>
  </div>
</div>

</main>
</div>

<!-- 媒体预览 modal -->
<div class="modal-bg" id="modal" onclick="if(event.target===this)closeModal()">
  <div class="modal">
    <button class="modal-close" onclick="closeModal()">✕</button>
    <div id="modal-body" style="min-width:280px;min-height:80px"></div>
    <div id="modal-name" style="font-size:11px;color:var(--tx2);margin-top:10px;text-align:center;word-break:break-all"></div>
  </div>
</div>

<div class="toast" id="toast"></div>

<script src="/static/app.js" defer></script>
</body></html>"""


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
