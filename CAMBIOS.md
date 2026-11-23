# Qué he cambiado respecto a tu base (y por qué)

## 1. Fallos que impedían que funcionase
| Fallo en la base | Efecto | Arreglo |
|---|---|---|
| `st.set_page_config` llamado dos veces (`app.py`) | Streamlit lanza excepción nada más entrar | Una sola llamada |
| CSS que oculta la barra lateral en móvil, con **todos** los controles dentro | En el móvil no se podía cambiar nada | Todo en la página principal, en pasos |
| Contraseña del jurado escrita en el código | Visible en el repositorio | `APP_PASSWORD` por secrets/entorno (opcional) |
| Geolocalización recargando la página entera | Se perdía la sesión y pedía la contraseña otra vez; en A→B la ubicación se pisaba; el respaldo por IP era impreciso y enviaba la IP a un tercero | `get_geolocation` sin recarga; sin respaldo por IP |
| Los árboles solo contaban si marcabas «Mostrar arbolado» | Por defecto la sombra valía 0 para todas las rutas | Siempre se usa el índice; la casilla solo pinta el mapa de calor |
| Sombra normalizada en 0-60 sobre conteos acumulados por punto | Saturaba siempre: la sombra no influía | Densidad local ponderada por altura, calibrada con zonas reales |
| POIs contados una vez **por cada punto de muestreo** | Conteos inflados que dependían de la longitud | Cada POI cuenta una vez |
| Pesos 0-10 sin normalizar en la media geométrica | Puntuaciones del orden de 1e50 | Pesos normalizados: puntuación 1-100 |
| Lluvia solo **filtraba** la ruta directa | Salía un error si la ruta no pasaba cerca de un refugio | El planificador busca una ruta con parada cubierta (y amplía la búsqueda) |
| «Refugio manual» marcado solo con calor/frío/UV y obligatorio | Al mediodía en verano casi todo fallaba | Calor/frío/UV solo **pesan**; obligatorio solo con lluvia o si lo pide el usuario |
| Ningún museo/biblioteca tenía horario reconocible; `datetime.now()` del servidor (UTC) | «Abierto ahora» siempre sí; horas erróneas en la nube | Horarios estimados por categoría y día + hora de Madrid |
| `Museos.geo` ≠ `museos.geo` en Linux/Docker | Museos, monumentos y bibliotecas no se cargaban | Búsqueda de ficheros sin distinguir mayúsculas |
| `fuentes.json`: 12 % sin latitud/longitud | Fuentes descartadas | Se convierten desde UTM |
| Fallback de ruta sin parada duplicaba los km; el circular dibujaba un triángulo sobre edificios | Datos falsos | Corregido; sin triángulos inventados |
| Historial nunca se guardaba; `components.html` escribía en cada rerun | Favoritos/historial vacíos o duplicados | `storage.py` idempotente, la sesión es la fuente de verdad |
| Voz lanzada desde otro marco | Chrome/Safari la bloquean (sin gesto del usuario) | Botón dentro del propio iframe |
| Progreso GPS = distancia en línea recta origen→actual / origen→destino | Mal en rutas con curvas; división por cero en circulares | Progreso sobre el recorrido real |
| `st.warning` dentro de funciones cacheadas | Avisos repetidos | Los avisos viajan en el resultado |
| Selector de estación («otono» sin ñ) y calor solo en algunas estaciones | Septiembre a 32 °C no avisaba | Umbrales por temperatura real; 28 °C todo el año |
| `.gitignore` sin `secrets.toml`; Dockerfile como root, sin healthcheck; fichero llamado `DockerFile` | Riesgo de subir claves; la plataforma no lo detecta | Corregido (se llama `Dockerfile`) |

## 2. Novedades
- **`planner.py`**: paseo circular o A→B con 1-3 paradas, 3 alternativas distintas, comparación con la ruta directa, punto lateral para que
  el regreso no repita calle, y *«Repetir»* un paseo guardado con el clima y los horarios de ahora.
- **Perfiles** con ritmo propio y movilidad reducida (evita escaleras, límite de desnivel); texto grande; simulación de clima para la demo.
- **Modo paseo en vivo** (GPS) con el tramo recorrido en gris, instrucciones, voz, pantalla activa y simulador.
- **Emergencias**: 112, farmacias, salud, desfibriladores, aseos, bancos, calidad del aire y polen.
- **PDF** con mapa esquemático, **compartir** (Google/Apple Maps con paradas, WhatsApp), búsqueda de **direcciones**.
- **Altimetría** desde ORS (sin llamadas extra) o Open-Meteo; se elimina Open-Elevation (poco fiable) y su clave.

## 3. Eficiencia
| | Antes | Ahora |
|---|---|---|
| Arbolado | CSV de 75 MB, >10 s, cientos de MB en memoria, copia por cada rerun | `.npz` de 1 MB, 0,07 s, un solo objeto compartido |
| Sombra de una ruta | haversine contra 800.000 árboles por cada punto | 4 lecturas por punto (2.000 consultas ≈ 2 ms) |
| Horarios | `iterrows` fila a fila en cada interacción | Vectorizado |
| Rutas | Se recalculaban al tocar cualquier control | Solo al pulsar «Crear paseo»; las candidatas en paralelo |
| Dependencias | `pyproj` + otras | Solo numpy para UTM e índice |

## 4. Lo que NO he podido comprobar aquí (sin red ni navegador)
Pruébalo antes de la demo: 1) el aspecto real en el móvil; 2) rutas con tu clave de ORS; 3) el permiso de GPS (`streamlit-js-eval`);
4) la descarga del PDF (`fpdf2`); 5) Overpass/Open-Meteo en vivo. Los 45 tests y la prueba de humo (que ejecuta `app.py` completa con un
Streamlit simulado y los datos reales) sí pasan.

## 5. Decisiones que he tomado por ti (cámbialas en `config.py`)
Ritmos (3,3 / 5,0 / 2,7 km/h), 5 min por parada, horarios estimados, **centros de mayores como interés pero no como refugio**
(exigen carné), exclusión de «instalaciones deportivas / asesoramiento / juvenil» como refugio, y umbral de calor en 28 °C.
