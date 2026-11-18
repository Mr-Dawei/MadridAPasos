# -*- coding: utf-8 -*-
"""Componentes UI: geolocalización, compartir, TTS, progreso GPS."""
import urllib.parse
import streamlit as st
import streamlit.components.v1 as components


def boton_geolocalizacion():
    """Botón JS que escribe ?user_lat=..&user_lon=.. en la URL y recarga."""
    js = """
    <button id="btn-geo" style="padding:10px 18px;font-size:15px;border-radius:999px;
            border:none;background:#0A84FF;color:white;font-weight:600;cursor:pointer;">
        📍 Usar mi ubicación
    </button>
    <div id="msg" style="font-size:12px;color:#666;margin-top:6px;"></div>
    <script>
      document.getElementById('btn-geo').addEventListener('click', () => {
        const msg = document.getElementById('msg');
        msg.textContent = 'Obteniendo ubicación…';
        if (!navigator.geolocation) { msg.textContent = 'Navegador sin GPS.'; return; }
        navigator.geolocation.getCurrentPosition(
          (pos) => {
            const url = new URL(window.parent.location.href);
            url.searchParams.set('user_lat', pos.coords.latitude.toFixed(6));
            url.searchParams.set('user_lon', pos.coords.longitude.toFixed(6));
            window.parent.location.href = url.toString();
          },
          () => {
            msg.textContent = 'Permiso denegado. Probando por IP…';
            fetch('https://ipapi.co/json/').then(r => r.json()).then(d => {
              if (d.latitude && d.longitude) {
                const url = new URL(window.parent.location.href);
                url.searchParams.set('user_lat', d.latitude.toFixed(6));
                url.searchParams.set('user_lon', d.longitude.toFixed(6));
                window.parent.location.href = url.toString();
              } else { msg.textContent = 'No se pudo obtener ubicación.'; }
            }).catch(() => { msg.textContent = 'No se pudo obtener ubicación.'; });
          },
          { enableHighAccuracy: true, timeout: 8000, maximumAge: 60000 }
        );
      });
    </script>
    """
    components.html(js, height=90)


def botones_compartir(origen, destino, km, minutos, origen_nombre, destino_nombre):
    gmaps = (f"https://www.google.com/maps/dir/?api=1"
             f"&origin={origen[0]},{origen[1]}"
             f"&destination={destino[0]},{destino[1]}&travelmode=walking")
    amaps = (f"https://maps.apple.com/?saddr={origen[0]},{origen[1]}"
             f"&daddr={destino[0]},{destino[1]}&dirflg=w")
    texto = urllib.parse.quote(f"Mi ruta en Pasea Madrid: {origen_nombre} → {destino_nombre}, {km:.1f} km, {minutos} min")
    whats = f"https://wa.me/?text={texto}"

    st.markdown(f"""
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px;">
      <a href="{gmaps}" target="_blank" style="text-decoration:none;">
        <button style="padding:9px 16px;border-radius:999px;background:#34C759;color:white;border:none;font-weight:600;cursor:pointer;">
          🗺 Google Maps
        </button></a>
      <a href="{amaps}" target="_blank" style="text-decoration:none;">
        <button style="padding:9px 16px;border-radius:999px;background:#007AFF;color:white;border:none;font-weight:600;cursor:pointer;">
          🍎 Apple Maps
        </button></a>
      <a href="{whats}" target="_blank" style="text-decoration:none;">
        <button style="padding:9px 16px;border-radius:999px;background:#25D366;color:white;border:none;font-weight:600;cursor:pointer;">
          💬 WhatsApp
        </button></a>
    </div>
    """, unsafe_allow_html=True)


def boton_tts(texto):
    if st.button("🔊 Leer en voz alta", use_container_width=True):
        components.html(f"""
        <script>
          const u = new SpeechSynthesisUtterance({texto!r});
          u.lang = 'es-ES';
          window.speechSynthesis.speak(u);
        </script>
        """, height=0)


def barra_progreso_gps(origen, destino):
    """Barra de progreso basada en la posición GPS del usuario."""
    components.html(f"""
    <div style="padding:1rem;background:#F5F5F7;border-radius:14px;margin-top:8px;">
      <div id="lbl" style="font-size:1rem;font-weight:600;margin-bottom:8px;">
        Activa el GPS para ver tu progreso
      </div>
      <div style="background:#e5e5ea;border-radius:999px;height:10px;overflow:hidden;">
        <div id="bar" style="height:100%;width:0%;background:#0A84FF;transition:width 0.3s;"></div>
      </div>
    </div>
    <script>
    const O = [{origen[0]}, {origen[1]}];
    const D = [{destino[0]}, {destino[1]}];
    function dist(a, b) {{
      const R = 6371000, φ1 = a[0]*Math.PI/180, φ2 = b[0]*Math.PI/180;
      const Δφ = (b[0]-a[0])*Math.PI/180, Δλ = (b[1]-a[1])*Math.PI/180;
      const x = Math.sin(Δφ/2)**2 + Math.cos(φ1)*Math.cos(φ2)*Math.sin(Δλ/2)**2;
      return 2*R*Math.atan2(Math.sqrt(x), Math.sqrt(1-x));
    }}
    if (navigator.geolocation) {{
      navigator.geolocation.watchPosition((pos) => {{
        const H = [pos.coords.latitude, pos.coords.longitude];
        const total = dist(O, D), done = dist(O, H);
        const pct = Math.min(100, Math.round(done/total*100));
        document.getElementById('lbl').textContent =
          `Has recorrido el ${{pct}}% (${{Math.round(done)}} m de ${{Math.round(total)}} m)`;
        document.getElementById('bar').style.width = pct + '%';
      }}, () => {{
        document.getElementById('lbl').textContent = 'GPS no disponible';
      }}, {{ enableHighAccuracy: true, maximumAge: 5000 }});
    }}
    </script>
    """, height=110)