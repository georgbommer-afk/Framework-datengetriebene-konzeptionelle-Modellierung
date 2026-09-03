"""Lokaler, netzwerkfreier Pan-/Zoom-Viewer für bereits validierte SVGs."""

from html import escape

import streamlit.components.v1 as components


def svg_zoom_viewer(svg_text: str, beschriftung: str, *, hoehe: int = 520) -> None:
    """Bettet ein internes SVG in einen isolierten Viewer mit Zoom, Pan und Scrollbars ein."""
    titel = escape(beschriftung)
    components.html(
        f"""
        <div class="svg-viewer" aria-label="{titel}">
          <div class="toolbar">
            <strong>{titel}</strong>
            <span></span>
            <button type="button" data-action="minus" aria-label="Verkleinern">−</button>
            <button type="button" data-action="plus" aria-label="Vergrößern">+</button>
            <button type="button" data-action="reset">Zurücksetzen</button>
          </div>
          <div class="viewport"><div class="canvas">{svg_text}</div></div>
        </div>
        <style>
          .svg-viewer {{ border: 1px solid #d6d6d6; border-radius: .5rem; overflow: hidden; }}
          .toolbar {{ display:flex; gap:.4rem; align-items:center; padding:.45rem .65rem;
                      background:#f7f7f7; border-bottom:1px solid #ddd; }}
          .toolbar span {{ flex:1; }}
          .toolbar button {{ border:1px solid #aaa; border-radius:.3rem; background:white;
                             padding:.25rem .65rem; cursor:pointer; }}
          .viewport {{ height:{max(320, hoehe - 54)}px; overflow:auto; cursor:grab;
                       background:white; }}
          .viewport.dragging {{ cursor:grabbing; user-select:none; }}
          .canvas {{ transform-origin:0 0; width:max-content; min-width:100%; padding:1rem; }}
          .canvas svg {{ display:block; max-width:none !important; height:auto; }}
        </style>
        <script>
          (() => {{
            const root = document.currentScript.previousElementSibling.previousElementSibling;
            const viewport = root.querySelector('.viewport');
            const canvas = root.querySelector('.canvas');
            let scale = 1, dragging = false, x = 0, y = 0, left = 0, top = 0;
            const draw = () => canvas.style.transform = `scale(${{scale}})`;
            const zoom = delta => {{ scale = Math.min(4, Math.max(.25, scale * delta)); draw(); }};
            root.querySelector('[data-action="plus"]').onclick = () => zoom(1.2);
            root.querySelector('[data-action="minus"]').onclick = () => zoom(1 / 1.2);
            root.querySelector('[data-action="reset"]').onclick = () => {{
              scale = 1; draw(); viewport.scrollTo(0, 0);
            }};
            viewport.addEventListener('wheel', event => {{
              event.preventDefault(); zoom(event.deltaY < 0 ? 1.1 : 1 / 1.1);
            }}, {{passive:false}});
            viewport.addEventListener('pointerdown', event => {{
              dragging = true; x = event.clientX; y = event.clientY;
              left = viewport.scrollLeft; top = viewport.scrollTop;
              viewport.classList.add('dragging'); viewport.setPointerCapture(event.pointerId);
            }});
            viewport.addEventListener('pointermove', event => {{
              if (!dragging) return;
              viewport.scrollLeft = left - (event.clientX - x);
              viewport.scrollTop = top - (event.clientY - y);
            }});
            viewport.addEventListener('pointerup', () => {{
              dragging = false; viewport.classList.remove('dragging');
            }});
          }})();
        </script>
        """,
        height=hoehe,
        scrolling=False,
    )
