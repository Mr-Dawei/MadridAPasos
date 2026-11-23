# 🌳 MadridAPasos
**Rutas que respiran contigo.** Aplicación web que crea paseos a pie por Madrid con **sombra, fuentes y sitios de interés**,
adaptados al clima en tiempo real, pensada para personas mayores y jóvenes (móvil primero, también en ordenador).

## Qué hace
- **Paseo circular** (sales y vuelves) o **de A a B**, con **de 1 a 3 paradas** según el tiempo elegido (15–120 min).
- **Perfiles**: tranquilo, activo y movilidad reducida (ritmo, desnivel y pendientes distintos; evita escaleras).
- **Clima real** (Open-Meteo). Lluvia (> 1 mm/h) o «quiero techo» ⇒ la ruta pasa **sí o sí** por un museo, biblioteca o centro
  cultural abierto. Calor (≥ 28 °C, todo el año), frío (< 8 °C) o UV alto (≥ 6,5) ⇒ el refugio, la sombra y las fuentes pesan más.
- **Puntuación explicada** en pantalla (7 criterios) y comparación con la ruta directa.
- **Modo paseo**: sigue tu GPS, pinta de gris lo ya recorrido, muestra el progreso y lee las indicaciones en voz alta.
  El botón **«Simular paseo»** permite hacer la demo sin salir a la calle.
- Abrir en **Google Maps / Apple Maps**, compartir por **WhatsApp**, **PDF** imprimible, **favoritos e historial**
  (solo en el navegador del usuario: no hay servidor ni cuentas).
- **Emergencias**: 112, farmacias, centros de salud, desfibriladores, aseos, bancos, calidad del aire y polen.
- **Texto grande** y botones amplios pensados para personas mayores.

## Puesta en marcha
```bash
python -m venv .venv
.venv\Scripts\activate            # Windows  (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
python -m streamlit run app.py
```
La geolocalización del navegador solo funciona en `localhost` o por **HTTPS** (Streamlit Cloud y Hugging Face lo son).

## Configuración (claves y contraseña — nunca en el código)
Copia `.streamlit/secrets.toml.example` a `.streamlit/secrets.toml` (ya está en `.gitignore`) o usa variables de entorno:

| Variable | Para qué | ¿Obligatoria? |
|---|---|---|
| `ORS_API_KEY` | OpenRouteService: instrucciones y altimetría de mejor calidad | No (sin ella usa el servidor público FOSSGIS) |
| `APP_PASSWORD` | Pantalla de acceso (p. ej. para el jurado) | No (vacía = sin contraseña) |

> ⚠️ Si alguna clave estuvo escrita en versiones anteriores del código o en el historial de git, **regenérala**.

## Datos (`data/`)
`parques.geo`, `monumentos.geo`, `museos.geo`, `bibliotecas.geo`, `centros_culturales.geo`, `centros_mayores.geo`, `fuentes.json`
(datos.madrid.es) y `arbolado_malla.npz`. Los nombres se buscan **sin distinguir mayúsculas** (en Linux/Docker `Museos.geo` ≠ `museos.geo`).

El arbolado original (`arbolado.csv`, 75 MB, 800.000 árboles) se convierte **una vez** en un índice de 1 MB que carga en ~0,1 s:
```bash
python tools/preparar_arbolado.py data/arbolado.csv      # genera data/arbolado_malla.npz
```
Se sube el `.npz` al repositorio; el CSV queda fuera (`.gitignore`). `Api_metereorologia.api` es la especificación Swagger de la API del
Ayuntamiento, no contiene datos de clima, y no se usa.

## Despliegue
**Streamlit Community Cloud (lo más rápido):** sube el proyecto a GitHub → *New app* → `app.py` → *Advanced settings → Secrets* y pega
`secrets.toml.example`. **Docker:**
```bash
docker build -t madridapasos .
docker run -p 8501:8501 -e ORS_API_KEY=... -e APP_PASSWORD=... madridapasos
```
**Hugging Face Spaces (Docker):** crea un Space de tipo Docker y añade al principio de este README
`---\ntitle: MadridAPasos\nsdk: docker\napp_port: 8501\n---`.

## Cómo se puntúa un paseo
Media geométrica ponderada (pesos normalizados) de 7 criterios en [0, 1] → puntuación 1-100. Cada POI se cuenta **una vez**.

| Criterio | Cómo se mide | Tranquilo | Activo | Mov. reducida |
|---|---|:-:|:-:|:-:|
| Sombra | Densidad de arbolado ponderada por altura en ≤ 25 m de la ruta (≥ 12 árboles medianos = sombra completa) | 9 | 5 | 7 |
| Refugio | Parada con techo abierta + refugios a ≤ 150 m | 7 | 4 | 9 |
| Fuentes | Fuentes operativas a ≤ 60 m, por km | 8 | 6 | 8 |
| Interés | POIs a ≤ 80 m ponderados por categoría + paradas | 4 | 9 | 5 |
| Ajuste al tiempo | Distancia vs. la que da el tiempo elegido | 5 | 7 | 4 |
| Desnivel *(fijo)* | Ascenso por km (ORS o Open-Meteo) | 8 | 3 | 10 |
| Pendientes *(fijo)* | Fracción del recorrido con pendiente > 6 % | 7 | 5 | 10 |

Calor/UV/frío/lluvia reajustan los pesos. **Reglas duras:** lluvia o techo pedido ⇒ al menos una parada con techo abierta;
movilidad reducida ⇒ ascenso ≤ 30 m. Si una opción no las cumple se avisa, nunca se deja al usuario sin resultado.

**Cómo se genera:** candidatos por geometría rápida (anillo/elipse) → combinaciones → las K mejores se trazan con el servicio de rutas
(en paralelo) y se re-puntúan con la ruta real. Con una sola parada se añade un punto lateral para que el regreso no repita la calle.

## Estructura
| Módulo | Responsabilidad |
|---|---|
| `app.py` | Interfaz Streamlit (planificador, resultado, guardados, emergencias, ajustes) |
| `ui_components.py` | CSS, tarjetas, mapa, **modo paseo en vivo**, compartir y voz |
| `planner.py` · `scoring.py` | Generación de paseos · puntuación multicriterio |
| `routing.py` | ORS → FOSSGIS → línea recta, altimetría y búsqueda de direcciones |
| `spatial.py` | Índice de arbolado (malla + imagen integral, consultas O(1)) |
| `data_loader.py` · `geo_utils.py` | Carga de datos y clima · geometría, UTM, horarios |
| `emergencias.py` · `storage.py` · `pdf_export.py` | Servicios cercanos · favoritos/historial · PDF |
| `config.py` | Parámetros, categorías y claves |

## Pruebas
```bash
python -m unittest discover -s tests -v      # 45 pruebas; no necesitan Streamlit ni conexión
```
Incluye una prueba de humo que ejecuta `app.py` completa con un Streamlit simulado (carga, paseo, lluvia, modo paseo, favoritos…).

## Guion de demo (3 minutos)
1. Mapa inicial: **mapa de calor de sombra** de la ciudad. 2. *Circular · Tranquilo · 45 min* → 2 paradas y % de sombra.
3. *De A a B* Sol → Retiro: la tarjeta muestra los **puntos de sombra ganados** frente a la ruta directa.
4. *Ajustes → Clima → Lluvia*: otro paseo; **todas** las opciones pasan por un sitio con techo abierto. 5. Perfil *Movilidad reducida*.
6. **▶ Empezar → Simular paseo**: se pinta de gris lo recorrido. 7. PDF, WhatsApp y **Emergencias**.

## Limitaciones conocidas
- Los feeds oficiales **no traen horarios estructurados**: los de museos, bibliotecas y centros culturales son estimados por categoría y día
  (`config.HORARIOS_DEFECTO`), se muestran como «orientativos» con enlace a la ficha oficial, y los festivos pueden cambiarlos.
- El monte de la Casa de Campo solo tiene arbolado inventariado en las zonas ajardinadas.
- Se usan servicios públicos gratuitos (FOSSGIS, Photon, Overpass, Open-Meteo): para uso intensivo conviene una clave de ORS y servidores propios.
- Si el navegador recarga la página durante un paseo, el seguimiento vuelve a empezar (la posición se recalcula con el siguiente GPS).
- Los centros de mayores se muestran como interés, no como refugio (exigen carné de socio).
