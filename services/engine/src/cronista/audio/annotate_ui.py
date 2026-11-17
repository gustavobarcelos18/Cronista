# ruff: noqa: E501
"""Página local para anotar o gabarito sem escrever CSV à mão.

Gera um HTML único com o vídeo (proxy) e **sugestões já prontas** vindas da análise (falas do Whisper, risadas e
gritos do classificador). Você assiste, aceita, corrige o texto e marca o que faltou; o CSV sai pronto no formato
de `gabarito.py`. Nada de servidor: abre direto no navegador.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from cronista.domain.frames import FPS, frame_to_seconds
from cronista.gabarito import CLASSES

AUDIO_CLASSES_UI = ["fala", "risada", "exclamacao", "teclado", "respiracao", "farm"]
VISUAL_CLASSES_UI = ["menu", "loading", "idle", "hud_oculto"]
CLASSES_UI = AUDIO_CLASSES_UI + VISUAL_CLASSES_UI


def build_suggestions(
    events: list[tuple[str, int, int, float, str | None]],
    classes: list[str] | None = None,
    thumbs: Callable[[int], str | None] | None = None,
) -> list[dict[str, object]]:
    """(tipo, início, fim, confiança, texto) → sugestões em segundos, só as classes anotáveis.

    `thumbs(quadro)` devolve a miniatura (data URI) do meio de um candidato visual; sem ela não há miniatura.
    """
    allowed = classes if classes is not None else AUDIO_CLASSES_UI
    out: list[dict[str, object]] = []
    for kind, start, end, conf, quote in events:
        if kind not in allowed or (kind != "fala" and kind not in VISUAL_CLASSES_UI and conf < 0.3):
            continue
        thumb = thumbs((start + max(end, start)) // 2) if thumbs and kind in VISUAL_CLASSES_UI else None
        out.append(
            {
                **({"thumb": thumb} if thumb else {}),
                "cls": kind,
                "start": round(frame_to_seconds(start), 2),
                "end": round(frame_to_seconds(max(end, start + FPS // 2)), 2),
                "note": quote or "",
                "conf": round(conf, 2),
            }
        )
    return out


def render_annotator(video: Path, suggestions: list[dict[str, object]], title: str) -> str:
    data = json.dumps(
        {"video": video.resolve().as_uri(), "title": title, "classes": CLASSES_UI, "sug": suggestions},
        ensure_ascii=False,
    ).replace("</", "<\\/")
    descriptions = json.dumps({c: CLASSES[c] for c in CLASSES_UI}, ensure_ascii=False)
    return _PAGE.replace("__DATA__", data).replace("__DESC__", descriptions)


_PAGE = r"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><title>Gabarito</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{--bg:#fff;--fg:#1a1a1a;--mut:#666;--line:#ddd;--acc:#2563eb;--ok:#15803d;--sug:#f5f7ff}
@media(prefers-color-scheme:dark){:root{--bg:#161618;--fg:#eee;--mut:#999;--line:#333;--acc:#6ea0ff;--ok:#4ade80;--sug:#1d2030}}
body{margin:0;background:var(--bg);color:var(--fg);font:14px system-ui,sans-serif;display:grid;grid-template-columns:minmax(0,1.1fr) minmax(0,1fr);height:100vh}
@media(max-width:900px){body{grid-template-columns:1fr;height:auto}}
.left{padding:12px;border-right:1px solid var(--line)}.right{padding:12px;overflow:auto}
video{width:100%;background:#000;border-radius:6px}
button{font:inherit;padding:6px 10px;border:1px solid var(--line);background:transparent;color:var(--fg);border-radius:6px;cursor:pointer}
button:hover{border-color:var(--acc)}button.p{background:var(--acc);color:#fff;border-color:var(--acc)}
.bar{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0;align-items:center}
.mut{color:var(--mut)}.kbd{font-family:monospace;border:1px solid var(--line);border-radius:4px;padding:0 4px;font-size:12px}
.row{border:1px solid var(--line);border-radius:6px;padding:8px;margin:6px 0}.row.sug{background:var(--sug);border-style:dashed}
.row.done{border-color:var(--ok)}.row .top{display:flex;gap:6px;align-items:center;flex-wrap:wrap}
input[type=text]{width:100%;box-sizing:border-box;padding:6px;margin-top:6px;border:1px solid var(--line);border-radius:6px;background:transparent;color:var(--fg);font:inherit}
.t{font-family:monospace;cursor:pointer;color:var(--acc)}
select{font:inherit;background:transparent;color:var(--fg);border:1px solid var(--line);border-radius:6px;padding:4px}
h1{font-size:16px;margin:0 0 6px}
</style></head><body>
<div class="left">
<h1 id="ttl"></h1>
<video id="v" controls preload="metadata"></video>
<div class="bar"><span class="mut">Trecho atual:</span> <b id="cur">—</b>
<button id="bi">Início <span class="kbd">I</span></button><button id="bo">Fim <span class="kbd">O</span></button></div>
<div class="bar" id="cls"></div>
<p class="mut">Passo a passo: toque o vídeo, aperte <span class="kbd">I</span> onde começa e <span class="kbd">O</span> onde termina,
depois a classe (ou o número dela). <span class="kbd">Espaço</span> pausa, <span class="kbd">←</span>/<span class="kbd">→</span> pulam 5 s.
<b>Sons curtos</b> (respiração, tecla, risada): ouça em câmera lenta (<span class="kbd">-</span> diminui a velocidade),
aperte só <span class="kbd">I</span> um pouco antes do som e depois a classe: o fim fica 1 s depois. Ajuste fino: <span class="kbd">,</span> e <span class="kbd">.</span> voltam/avançam 0,1 s; <span class="kbd">Shift</span>+setas, 0,5 s.
As caixas tracejadas à direita são <b>sugestões da análise</b>: confirme com ✓, corrija o texto ou apague com ✕.</p>
</div>
<div class="right">
<div class="bar"><button class="p" id="save">Baixar CSV</button><button id="copy">Copiar CSV</button>
<span class="mut" id="stat"></span></div>
<div id="rows"></div>
</div>
<script>
const D=__DATA__, DESC=__DESC__, KEY="gabarito:"+D.video;
const $=id=>document.getElementById(id), v=$("v");
let rows=[], mark={s:null,e:null};
$("ttl").textContent=D.title; v.src=D.video;
function fmt(t){const m=Math.floor(t/60),s=(t-m*60).toFixed(1).padStart(4,"0");return m+":"+s}
function load(){try{const s=localStorage.getItem(KEY);if(s)return JSON.parse(s)}catch(e){}return D.sug.map(x=>({...x,sug:true,ok:false}))}
function persist(){try{localStorage.setItem(KEY,JSON.stringify(rows))}catch(e){}}
rows=load();
function draw(){
  rows.sort((a,b)=>a.start-b.start);
  const box=$("rows");box.innerHTML="";
  rows.forEach((r,i)=>{
    const d=document.createElement("div");d.className="row"+(r.sug&&!r.ok?" sug":"")+(r.ok?" done":"");
    const sel=D.classes.map(c=>`<option ${c==r.cls?"selected":""}>${c}</option>`).join("");
    d.innerHTML=`<div class="top"><span class="t" data-i="${i}">${fmt(r.start)} → ${fmt(r.end)}</span>${r.thumb?`<img src="${r.thumb}" style="height:48px;border-radius:4px">`:""}
      <select data-c="${i}">${sel}</select>${r.sug?`<span class="mut">sugestão${r.conf?" ("+Math.round(r.conf*100)+"%)":""}</span>`:""}
      <span style="flex:1"></span><button data-k="${i}">✓</button><button data-x="${i}">✕</button></div>
      <input type="text" data-n="${i}" placeholder="${r.cls=="fala"?"o que você disse, palavra por palavra":"nota (opcional)"}" value="${(r.note||"").replace(/"/g,"&quot;")}">`;
    box.appendChild(d)});
  const n=rows.filter(r=>!r.sug||r.ok).length;
  $("stat").textContent=n+" confirmadas, "+(rows.length-n)+" sugestões pendentes";
  persist();
}
$("rows").addEventListener("click",e=>{const t=e.target;
  if(t.dataset.i!==undefined){const r=rows[+t.dataset.i];v.currentTime=Math.max(0,r.start-.5);v.play();const stop=()=>{if(v.currentTime>=r.end){v.pause();v.removeEventListener("timeupdate",stop)}};v.addEventListener("timeupdate",stop)}
  if(t.dataset.k!==undefined){rows[+t.dataset.k].ok=true;draw()}
  if(t.dataset.x!==undefined){rows.splice(+t.dataset.x,1);draw()}});
$("rows").addEventListener("input",e=>{const t=e.target;if(t.dataset.n!==undefined){rows[+t.dataset.n].note=t.value;rows[+t.dataset.n].ok=true;persist()}});
$("rows").addEventListener("change",e=>{const t=e.target;if(t.dataset.c!==undefined){rows[+t.dataset.c].cls=t.value;rows[+t.dataset.c].ok=true;draw()}});
function show(){$("cur").textContent=(mark.s==null?"?":fmt(mark.s))+" → "+(mark.e==null?"?":fmt(mark.e))}
function setI(){mark.s=v.currentTime;if(mark.e!=null&&mark.e<=mark.s)mark.e=null;show()}
function setO(){mark.e=v.currentTime;if(mark.s==null)mark.s=Math.max(0,mark.e-3);show()}
function add(cls){if(mark.s!=null&&mark.e==null)mark.e=mark.s+1;
  if(mark.s==null||mark.e==null||mark.e<=mark.s){alert("Marque o início (I) e o fim (O) antes.");return}
  const near=D.sug.find(x=>x.cls=="fala"&&x.start<mark.e&&x.end>mark.s);
  rows.push({cls,start:mark.s,end:mark.e,note:cls=="fala"&&near?near.note:"",ok:true});mark={s:null,e:null};show();draw();}
$("bi").onclick=setI;$("bo").onclick=setO;
D.classes.forEach((c,i)=>{const b=document.createElement("button");b.title=DESC[c];b.innerHTML=c+(i<9?' <span class="kbd">'+(i+1)+'</span>':'');b.onclick=()=>add(c);$("cls").appendChild(b)});
document.addEventListener("keydown",e=>{if(["INPUT","SELECT","TEXTAREA"].includes(e.target.tagName))return;
  if(e.key=="i"||e.key=="I")setI();else if(e.key=="o"||e.key=="O")setO();
  else if(/^[1-9]$/.test(e.key)&&+e.key<=D.classes.length)add(D.classes[+e.key-1]);
  else if(e.key==" "){e.preventDefault();v.paused?v.play():v.pause()}
  else if(e.key=="ArrowLeft")v.currentTime-=e.shiftKey?.5:5;else if(e.key=="ArrowRight")v.currentTime+=e.shiftKey?.5:5;
  else if(e.key==",")v.currentTime-=.1;else if(e.key==".")v.currentTime+=.1;
  else if(e.key=="-")v.playbackRate=Math.max(.25,v.playbackRate-.25);else if(e.key=="+"||e.key=="=")v.playbackRate=Math.min(2,v.playbackRate+.25);});
function csv(){const q=s=>'"'+String(s||"").replace(/"/g,'""')+'"';
  return "inicio,fim,classe,nota\n"+rows.filter(r=>!r.sug||r.ok).map(r=>[fmt(r.start),fmt(r.end),r.cls,q(r.note)].join(",")).join("\n")+"\n"}
$("save").onclick=()=>{const a=document.createElement("a");a.href=URL.createObjectURL(new Blob(["﻿"+csv()],{type:"text/csv"}));a.download="gabarito.csv";a.click()};
$("copy").onclick=()=>navigator.clipboard.writeText(csv()).then(()=>alert("CSV copiado"));
show();draw();
</script></body></html>
"""
