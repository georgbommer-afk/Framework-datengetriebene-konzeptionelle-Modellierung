# ruff: noqa: E501
"""Lokaler, netzwerkfreier Pan-/Zoom-Viewer für bereits validierte SVGs."""

from base64 import b64encode
from html import escape

import streamlit as st


def svg_zoom_viewer(svg_text: str, beschriftung: str, *, hoehe: int = 520) -> None:
    """Zeigt ein validiertes SVG in einem isolierten, modernen Streamlit-Iframe."""
    titel = escape(beschriftung)
    dokument = f"""<!doctype html>
<html lang="de"><head><meta charset="utf-8"><style>
html,body{{height:100%;margin:0;font:14px Calibri,Arial,sans-serif;color:#1f2937}}
.viewer{{height:100%;border:1px solid #d6d6d6;border-radius:8px;overflow:hidden;box-sizing:border-box}}
.toolbar{{height:44px;display:flex;gap:6px;align-items:center;padding:0 10px;background:#f7f7f7;border-bottom:1px solid #ddd;box-sizing:border-box}}
.toolbar strong{{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}.toolbar span{{flex:1}}
button{{border:1px solid #aaa;border-radius:5px;background:white;padding:5px 10px;cursor:pointer}}
.viewport{{position:relative;height:calc(100% - 44px);overflow:hidden;cursor:grab;background:white;touch-action:none}}
.viewport.dragging{{cursor:grabbing;user-select:none}}.canvas{{position:absolute;left:0;top:0;transform-origin:0 0}}
.canvas svg{{display:block;max-width:none!important;width:auto;height:auto}}
</style></head><body><div class="viewer" aria-label="{titel}"><div class="toolbar"><strong>{titel}</strong><span></span>
<button type="button" data-action="minus" aria-label="Verkleinern">−</button><button type="button" data-action="plus" aria-label="Vergrößern">+</button>
<button type="button" data-action="reset">Einpassen</button></div><div class="viewport"><div class="canvas">{svg_text}</div></div></div>
<script>(()=>{{const viewport=document.querySelector('.viewport'),canvas=document.querySelector('.canvas'),svg=canvas.querySelector('svg');
let scale=1,tx=0,ty=0,dragging=false,startX=0,startY=0,startTx=0,startTy=0;
const bounds=()=>{{const vb=svg.viewBox&&svg.viewBox.baseVal;if(vb&&vb.width>0&&vb.height>0)return{{x:vb.x,y:vb.y,w:vb.width,h:vb.height}};const box=svg.getBBox();return{{x:box.x,y:box.y,w:box.width||1,h:box.height||1}}}};
const draw=()=>canvas.style.transform=`translate(${{tx}}px,${{ty}}px) scale(${{scale}})`;
const fit=()=>{{const b=bounds(),pad=24;scale=Math.max(.1,Math.min(4,(viewport.clientWidth-pad)/b.w,(viewport.clientHeight-pad)/b.h));tx=(viewport.clientWidth-b.w*scale)/2-b.x*scale;ty=(viewport.clientHeight-b.h*scale)/2-b.y*scale;draw()}};
const zoom=factor=>{{const old=scale,cx=viewport.clientWidth/2,cy=viewport.clientHeight/2,mx=(cx-tx)/old,my=(cy-ty)/old;scale=Math.min(6,Math.max(.1,old*factor));tx=cx-mx*scale;ty=cy-my*scale;draw()}};
document.querySelector('[data-action="plus"]').onclick=()=>zoom(1.2);document.querySelector('[data-action="minus"]').onclick=()=>zoom(1/1.2);document.querySelector('[data-action="reset"]').onclick=fit;
viewport.addEventListener('wheel',e=>{{e.preventDefault();zoom(e.deltaY<0?1.1:1/1.1)}},{{passive:false}});viewport.addEventListener('pointerdown',e=>{{dragging=true;startX=e.clientX;startY=e.clientY;startTx=tx;startTy=ty;viewport.classList.add('dragging');viewport.setPointerCapture(e.pointerId)}});
viewport.addEventListener('pointermove',e=>{{if(!dragging)return;tx=startTx+e.clientX-startX;ty=startTy+e.clientY-startY;draw()}});viewport.addEventListener('pointerup',()=>{{dragging=false;viewport.classList.remove('dragging')}});requestAnimationFrame(fit)}})();</script></body></html>"""
    quelle = "data:text/html;base64," + b64encode(dokument.encode("utf-8")).decode("ascii")
    st.iframe(quelle, height=hoehe)
